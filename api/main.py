import asyncio
from collections import OrderedDict
from typing import Literal
import datetime as dt
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import config
import flags
import benchmark
import experiment_events
import matching
import metrics
import models
import sarvam
import search
from cache import search_cache
from db import engine, ensure_columns, get_session
from geo import haversine_km
from seed_data import DEMO_DATE
from journey import Journey, build_journey

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("gharchalo.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Creates only *missing* tables (the Flagsmith experiment logs) on an existing
    # database, so nobody has to re-seed. Never drops anything.
    try:
        models.Base.metadata.create_all(engine)
        added = ensure_columns()  # tops up older tables with newer columns, without a reseed
        if added:
            log.info("added missing columns: %s", ", ".join(added))
    except Exception as exc:  # database down at boot: requests will report 503 later
        log.warning("could not create tables at startup: %s", type(exc).__name__)
    flags.client()  # start the Flagsmith local-evaluation poller early
    yield
    flags.shutdown()  # send any experiment events still buffered


app = FastAPI(title="GharChalo API", lifespan=lifespan)


# Planted fault (config.FAULT_UNBOUNDED_SEARCH_LOG): grows with every search and is never trimmed.
_search_log: list = []


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        metrics.observe_request(request.method, getattr(route, "path", "unmatched"), status, time.perf_counter() - start)


def user_id_header(x_user_id: str | None = Header(default=None, max_length=64)) -> str | None:
    """Anonymous stable browser id (web/src/user.ts): the Flagsmith identity."""
    return x_user_id.strip() or None if x_user_id else None


class VoiceResponse(BaseModel):
    transcript: str
    language_code: str | None
    journey: Journey
    source: str  # "sarvam" or "stub" (X-Load-Test)


class ParseRequest(BaseModel):
    text: str


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "sarvam_configured": bool(config.SARVAM_API_KEY),
        "flagsmith": flags.status(),
        "express_surge_pricing": config.ENABLE_EXPRESS_SURGE_PRICING,
    }


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.get("/config")
def client_config(date: dt.date | None = None, user_id: str | None = Depends(user_id_header)):
    """What the browser needs to know about its flags. The frontend never talks to
    Flagsmith directly: one source of truth, and no client key to leak."""
    f = flags.for_user(user_id, date)
    return {
        "tatkal_level": f.tatkal_level,
        "poll_s": f.poll_s,
        "interaction_mode": f.interaction_mode,
        "cohort_km": f.max_km,
        "matching_strategy": f.matching_strategy,
        "urgent": f.urgent,
        "flags_source": f.source,
        "allow_override": config.ALLOW_FLAG_OVERRIDE,
        "features": f.features,  # release toggles for this visitor, e.g. {"tatkal_countdown": true}
    }


def _stub_response() -> VoiceResponse:
    """Canned reply for load tests. Same validation path, no Sarvam call."""
    today = dt.date.today()
    date = dt.date(today.year, 11, 27)
    if date < today:
        date = dt.date(today.year + 1, 11, 27)
    extraction = {
        "origin_text": "Bangalore",
        "destination_text": "Hyderabad",
        "date": date.isoformat(),
        "fallback_mode": "shared_cab",
        "language": "hi",
    }
    return VoiceResponse(
        transcript="Mujhe 27 November ko Bangalore se Hyderabad jaana hai. Train nahi mili toh shared cab dekhna.",
        language_code="hi-IN",
        journey=build_journey(extraction, today),
        source="stub",
    )


def _http_error(exc: sarvam.SarvamError) -> HTTPException:
    # 503 for rate limits so clients (and later, NuBi) can tell "Sarvam is
    # throttling us" apart from a generic upstream failure.
    status = 503 if exc.rate_limited else 502
    return HTTPException(status_code=status, detail=str(exc))


async def _voice_gate() -> None:
    """Flag-controlled behaviour in front of every Sarvam call.

    interaction_mode=text_only  -> voice is switched off (409, not a 5xx: it is a decision, not a failure)
    sarvam_fault_mode=429|timeout|error -> simulated outage (roadmap incident 3). Never touches real Sarvam quota.
    """
    if flags.interaction_mode() == "text_only":
        raise HTTPException(status_code=409, detail="Voice search is paused right now. Please type your journey.")
    mode = flags.sarvam_fault_mode()
    if mode == "429":
        log.error("sarvam upstream error: HTTP 429 rate limited (sarvam_fault_mode=429)")
        raise HTTPException(status_code=503, detail="Sarvam rate limit (429) [simulated by sarvam_fault_mode]")
    if mode == "timeout":
        log.error("sarvam upstream error: request timed out (sarvam_fault_mode=timeout)")
        await asyncio.sleep(config.SIMULATED_SARVAM_TIMEOUT_SECONDS)
        raise HTTPException(status_code=502, detail="Sarvam request timed out [simulated by sarvam_fault_mode]")
    if mode == "error":
        log.error("sarvam upstream error: HTTP 500 unavailable (sarvam_fault_mode=error)")
        raise HTTPException(status_code=502, detail="Sarvam returned 500 [simulated by sarvam_fault_mode]")


# --------------------------------------------------------------------------- spoken replies (Bulbul)

TTS_LANGUAGES = {"hi", "bn", "kn", "ml", "mr", "od", "pa", "ta", "te", "gu", "en"}
_TTS_CACHE: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_TTS_CACHE_MAX = 64
# 0.1 s of 16 kHz mono silence: what load-test traffic gets instead of a real Sarvam call.
_SILENT_WAV = (
    b"RIFF" + (36 + 3200).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
    + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (16000).to_bytes(4, "little")
    + (32000).to_bytes(4, "little") + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
    + b"data" + (3200).to_bytes(4, "little") + bytes(3200)
)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = "en"  # "hi", "hi-IN", "en" ... (falls back to English for unsupported ones)
    date: dt.date | None = None  # the journey's date, so urgent travellers keep level 0 as in search


def _tts_language(value: str) -> str:
    base = value.strip().lower().split("-")[0]
    return f"{base if base in TTS_LANGUAGES else 'en'}-IN"


@app.post("/speak", responses={200: {"content": {"audio/wav": {}}}})
async def speak(
    body: SpeakRequest,
    user_id: str | None = Depends(user_id_header),
    x_load_test: str | None = Header(default=None),
):
    """Read a short reply aloud. Returns WAV audio.

    Load-test traffic gets silence and never reaches Sarvam. Tatkal level 2+ switches spoken replies
    off (the roadmap's "skip TTS" step); text-only mode and simulated Sarvam outages apply as for /voice.
    """
    text = " ".join(body.text.split())[: config.TTS_MAX_CHARS]
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    if x_load_test == "1":
        await asyncio.sleep(config.LOAD_TEST_STUB_DELAY_SECONDS / 4)
        return Response(content=_SILENT_WAV, media_type="audio/wav")
    if flags.for_user(user_id, body.date).tatkal_level >= 2:
        raise HTTPException(status_code=409, detail="Spoken replies are paused during peak Tatkal demand.")
    await _voice_gate()

    language = _tts_language(body.language)
    key = (text, language)
    audio = _TTS_CACHE.get(key)
    if audio is None:
        try:
            audio = await sarvam.speak(text, language)
        except sarvam.SarvamError as exc:
            raise _http_error(exc) from exc
        _TTS_CACHE[key] = audio
        if len(_TTS_CACHE) > _TTS_CACHE_MAX:
            _TTS_CACHE.popitem(last=False)
    else:
        _TTS_CACHE.move_to_end(key)
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/voice", response_model=VoiceResponse)
async def voice(
    file: UploadFile = File(...),
    x_load_test: str | None = Header(default=None),
):
    await _voice_gate()
    if x_load_test == "1":
        await asyncio.sleep(config.LOAD_TEST_STUB_DELAY_SECONDS)
        return _stub_response()

    audio = await file.read(config.MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio) > config.MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large")

    try:
        transcript = await sarvam.transcribe(
            audio,
            filename=file.filename or "audio.wav",
            content_type=file.content_type or "audio/wav",
        )
        if not transcript.text:
            raise HTTPException(status_code=422, detail="No speech detected in the recording")
        extraction = await sarvam.extract_journey(transcript.text)
    except sarvam.SarvamError as exc:
        raise _http_error(exc) from exc

    return VoiceResponse(
        transcript=transcript.text,
        language_code=transcript.language_code,
        journey=build_journey(extraction),
        source="sarvam",
    )


@app.post("/journey/parse", response_model=VoiceResponse)
async def parse_text(body: ParseRequest):
    """Same extraction on text (used when the user corrects the transcript)."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    await _voice_gate()  # it calls Sarvam chat, so text_only mode must not route through it
    try:
        extraction = await sarvam.extract_journey(text)
    except sarvam.SarvamError as exc:
        raise _http_error(exc) from exc
    return VoiceResponse(
        transcript=text,
        language_code=None,
        journey=build_journey(extraction),
        source="sarvam",
    )


@app.get("/stations", response_model=list[search.StationOut])
def list_stations(session: Session = Depends(get_session)):
    """Each city's main station: the choices for the typed-search form."""
    try:
        rows = session.scalars(
            select(models.Station).where(models.Station.is_primary).order_by(models.Station.city)
        )
        return [search.StationOut(code=s.code, name=s.name, city=s.city) for s in rows]
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc


FAULTY_CITIES = {"Bengaluru", "Hyderabad"}


def _is_faulty_route(session: Session, origin_code: str, dest_code: str) -> bool:
    """route_fault_sbc_hyb (test-only flag): Bengaluru <-> Hyderabad fails, both directions."""
    o, d = session.get(models.Station, origin_code), session.get(models.Station, dest_code)
    return bool(o and d and {o.city, d.city} == FAULTY_CITIES)


@app.get("/search/dates", response_model=search.DateStrip)
def search_dates(
    origin: str,
    dest: str,
    date: dt.date,
    days: int = Query(3, ge=1, le=7),
    session: Session = Depends(get_session),
):
    """Direct availability from the preferred station on the days around `date` (SIMULATED data)."""
    try:
        return search.date_strip(session, origin.strip().upper(), dest.strip().upper(), date, days)
    except search.UnknownStation as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except search.SameCity as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc


@app.get("/search", response_model=search.SearchResponse)
def search_journeys(
    origin: str,
    dest: str,
    date: dt.date,
    # Demo/dev override only (honoured when ALLOW_FLAG_OVERRIDE=1). Normally Flagsmith's
    # max_station_distance_km cohort (5 / 15 / 30) decides, per user.
    max_station_distance_km: int | None = Query(None, ge=0, le=search.MAX_ALTERNATIVE_KM),
    include_connections: bool = False,
    user_id: str | None = Depends(user_id_header),
    x_load_test: str | None = Header(default=None),
    session: Session = Depends(get_session),
):
    start = time.perf_counter()
    f = flags.for_user(user_id, date)
    status = 200
    try:
        return _search(session, f, user_id, origin, dest, date, max_station_distance_km, include_connections, x_load_test)
    except HTTPException as exc:
        status = exc.status_code
        raise
    finally:
        metrics.observe_urgency("search", f.urgent, time.perf_counter() - start, status)


def _search(session, f, user_id, origin, dest, date, override_km, include_connections, x_load_test):
    origin_code, dest_code = origin.strip().upper(), dest.strip().upper()
    km = override_km if (override_km is not None and config.ALLOW_FLAG_OVERRIDE) else f.max_km
    level = f.tatkal_level
    # Experiment A ladder: level 1 ignores on-demand multi-leg, level 2+ skips the planner.
    allow_connections = level < 2
    if level >= 1:
        include_connections = False
    key = (origin_code, dest_code, date, km, include_connections, allow_connections)

    try:
        if config.ENABLE_EXPRESS_SURGE_PRICING and _is_faulty_route(session, origin_code, dest_code):
            log.error(
                "express_surge_pricing v2 failed on %s -> %s: ZeroDivisionError: surge denominator is 0 "
                "(deployment regression; rollback gharchalo-api to recover)",
                origin_code,
                dest_code,
            )
            raise HTTPException(
                status_code=500,
                detail="Express surge pricing v2 failed: ZeroDivisionError on corridor SBC<->HYB",
            )
        if flags.route_fault_on() and _is_faulty_route(session, origin_code, dest_code):
            log.error("route search failed: 500 on %s -> %s (feature flag route_fault_sbc_hyb is enabled)", origin_code, dest_code)
            raise HTTPException(status_code=500, detail="Injected test fault (route_fault_sbc_hyb)")

        if level >= 3:
            hit = search_cache.get(key, ttl_seconds=f.cache_ttl_s)
            if hit is not None:
                metrics.search_served.labels("cache").inc()
                metrics.bump("search_cache")
                return hit.model_copy(update={"served_from": "cache", "tatkal_level": level, "search_id": None})

        resp = search.search(session, origin_code, dest_code, date, km, include_connections, allow_connections)
        search.add_confirm_chances(resp, f.days_until_travel)
        resp.tatkal_level = level
        search_cache.set(key, resp.model_copy())
        if config.FAULT_UNBOUNDED_SEARCH_LOG:
            _search_log.append(resp.model_copy(deep=True))
        metrics.search_served.labels("live").inc()
        metrics.bump("search_live")

        if not resp.preferred_station_has_train_seats:
            metrics.alternatives_shown.labels(str(km)).inc(len(resp.alternatives))
            if x_load_test != "1":  # storm traffic is not an experiment participant
                event = models.SearchEvent(
                    user_id=user_id or "",
                    cohort_km=km,
                    origin_code=origin_code,
                    dest_code=dest_code,
                    travel_date=date,
                    alternatives_shown=len(resp.alternatives),
                    beyond_limit=resp.more_alternatives_beyond_limit,
                    tatkal_level=level,
                    urgent=f.urgent,
                )
                session.add(event)
                session.commit()
                resp.search_id = event.id
                if override_km is None or not config.ALLOW_FLAG_OVERRIDE:
                    experiment_events.expose("max_station_distance_km", user_id)
        return resp
    except search.UnknownStation as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except search.SameCity as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc


class SelectRequest(BaseModel):
    service_id: int


class SelectResponse(BaseModel):
    search_id: int
    service_id: int
    station_code: str
    extra_km: float


@app.post("/search/{search_id}/select", response_model=SelectResponse)
def select_alternative(search_id: int, body: SelectRequest, session: Session = Depends(get_session)):
    """Experiment B: the user picked a train from a nearby station."""
    try:
        event = session.get(models.SearchEvent, search_id)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Unknown search {search_id}")
        svc = session.get(models.Service, body.service_id)
        if svc is None:
            raise HTTPException(status_code=404, detail=f"Unknown service {body.service_id}")
        preferred = session.get(models.Station, event.origin_code)
        chosen = session.get(models.Station, svc.origin_code)
        extra = round(haversine_km((preferred.lat, preferred.lon), (chosen.lat, chosen.lon)), 1)
        session.add(
            models.AlternativeSelection(
                search_event_id=event.id, service_id=svc.id, station_code=chosen.code, extra_km=extra
            )
        )
        session.commit()
        metrics.alternatives_selected.labels(str(event.cohort_km)).inc()
        experiment_events.convert("alternative_selected", event.user_id)
        return SelectResponse(search_id=event.id, service_id=svc.id, station_code=chosen.code, extra_km=extra)
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc


def _db_unavailable(exc: SQLAlchemyError) -> HTTPException:
    # Covers an unreachable database and an exhausted connection pool alike.
    logging.getLogger("gharchalo.db").error("database error: %s", type(exc).__name__)
    return HTTPException(status_code=503, detail=f"Database unavailable ({type(exc).__name__})")


class MatchRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    origin: str
    dest: str
    date: dt.date
    window_start: dt.time
    window_end: dt.time
    # Demo/dev override only (ALLOW_FLAG_OVERRIDE=1). Normally Flagsmith's matching_strategy decides.
    strategy: matching.Strategy | None = None

    @model_validator(mode="after")
    def _window_is_ordered(self):
        if self.window_end < self.window_start:
            raise ValueError("window_end must not be before window_start")
        return self


class AcceptResponse(BaseModel):
    match_id: int
    accepted: bool


@app.post("/match", response_model=matching.MatchResponse)
def match(body: MatchRequest, session: Session = Depends(get_session)):
    start = time.perf_counter()
    f = flags.for_user(body.user_id, body.date)
    status = 200
    try:
        return _match(body, f, session)
    except HTTPException as exc:
        status = exc.status_code
        raise
    finally:
        metrics.observe_urgency("match", f.urgent, time.perf_counter() - start, status)


def _match(body: MatchRequest, f: flags.UserFlags, session: Session) -> matching.MatchResponse:
    strategy = body.strategy if (body.strategy and config.ALLOW_FLAG_OVERRIDE) else f.matching_strategy
    if f.tatkal_level >= 3:
        # Paused under load: 200 + paused, nothing written (a 503 would inflate the error rate).
        metrics.match_paused.inc()
        metrics.bump("match_paused")
        return matching.MatchResponse(
            match_id=None, strategy=strategy, offered=0, suggested_group_size=1, matches=[], paused=True, retry_after_s=60
        )
    try:
        match_id, found = matching.find_matches(
            session,
            user_id=body.user_id,
            origin_code=body.origin.strip().upper(),
            dest_code=body.dest.strip().upper(),
            date=body.date,
            window_start=body.window_start,
            window_end=body.window_end,
            strategy=strategy,
            config=f.matching_config,
        )
    except search.UnknownStation as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except search.SameCity as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    metrics.matches_offered.labels(strategy).inc()
    metrics.bump("matches_served")
    if not (body.strategy and config.ALLOW_FLAG_OVERRIDE):
        experiment_events.expose("matching_strategy", body.user_id)
    return matching.MatchResponse(
        match_id=match_id,
        strategy=strategy,
        offered=len(found),
        suggested_group_size=min(4, 1 + len(found)),
        matches=found,
    )


@app.post("/match/{match_id}/accept", response_model=AcceptResponse)
def accept_match(match_id: int, session: Session = Depends(get_session)):
    try:
        event = matching.accept(session, match_id)
    except matching.UnknownMatch as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except matching.AlreadyEmpty as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    metrics.matches_accepted.labels(event.strategy).inc()
    experiment_events.convert("match_accepted", event.user_id)
    return AcceptResponse(match_id=event.id, accepted=event.accepted)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


SIMULATED_PREFIX = "sim-"  # identities used by deploy/experiments/simulate.py


def _scope(column, source: str) -> list:
    """Filter events to real visitors or to simulated ones (identity starts with sim-)."""
    if source == "live":
        return [~column.like(f"{SIMULATED_PREFIX}%")]
    if source == "simulated":
        return [column.like(f"{SIMULATED_PREFIX}%")]
    return []


@app.get("/experiments/matching-benchmark")
def matching_benchmark(session: Session = Depends(get_session)):
    """Both matching strategies on a fixed set of requests: coverage versus what flexibility costs.

    Deterministic and read-only. It uses the live `matching_config` flag, so changing a value in
    Flagsmith changes this result within seconds.
    """
    cfg = flags.for_user("benchmark", DEMO_DATE).matching_config
    try:
        return benchmark.matching_benchmark(session, cfg)
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc


@app.get("/experiments/summary")
def experiments_summary(
    source: Literal["all", "live", "simulated"] = "all",
    session: Session = Depends(get_session),
):
    """Live read-out of both Flagsmith experiments (and the optional matching A/B).

    `source` separates real visitors from simulated ones (identities starting `sim-`) so
    the two are never blended.
    """
    SE, AS, ME = models.SearchEvent, models.AlternativeSelection, models.MatchEvent
    se_scope, me_scope = _scope(SE.user_id, source), _scope(ME.user_id, source)
    try:
        searches = session.execute(
            select(
                SE.cohort_km,
                func.count(SE.id),
                func.sum(case((SE.alternatives_shown > 0, 1), else_=0)),
                func.coalesce(func.sum(SE.alternatives_shown), 0),
            ).where(*se_scope).group_by(SE.cohort_km)
        ).all()
        selections = {
            row[0]: row[1:]
            for row in session.execute(
                select(
                    SE.cohort_km,
                    func.count(func.distinct(AS.search_event_id)),
                    func.count(AS.id),
                    func.avg(AS.extra_km),
                )
                .join(SE, AS.search_event_id == SE.id)
                .where(*se_scope)
                .group_by(SE.cohort_km)
            ).all()
        }
        # Offers made before pickup-distance matching existed (group_size is NULL) ran different
        # rules, so they are left out of the A/B rather than blended into it.
        strategies = session.execute(
            select(
                ME.strategy,
                func.sum(case((ME.offered > 0, 1), else_=0)),
                func.sum(case((ME.accepted, 1), else_=0)),
                func.avg(case((ME.offered > 0, ME.offered))),
                func.avg(case((ME.offered > 0, ME.group_size))),
                func.avg(ME.avg_pickup_km),
                func.avg(ME.avg_day_shift),
                func.avg(ME.avg_time_gap_min),
            )
            .where(ME.group_size.isnot(None), *me_scope)
            .group_by(ME.strategy)
        ).all()
        legacy_offers = (
            session.scalar(select(func.count()).select_from(ME).where(ME.group_size.is_(None), *me_scope)) or 0
        )
        like = lambda col, sim: col.like(f"{SIMULATED_PREFIX}%") if sim else ~col.like(f"{SIMULATED_PREFIX}%")  # noqa: E731
        population = {
            name: {
                label: session.scalar(select(func.count()).select_from(model).where(like(model.user_id, sim))) or 0
                for label, sim in (("live", False), ("simulated", True))
            }
            for name, model in (("search_events", SE), ("match_events", ME))
        }
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc

    station_distance = []
    for cohort, total, with_alts, shown in sorted(searches, key=lambda r: r[0]):
        searches_selected, selected, avg_extra = selections.get(cohort, (0, 0, None))
        with_alts = int(with_alts or 0)
        station_distance.append(
            {
                "cohort_km": cohort,
                "searches": total,
                "searches_with_alternatives": with_alts,
                "alternatives_shown": int(shown),
                "alternatives_selected": selected,
                "selection_rate": _rate(searches_selected, with_alts),
                "avg_extra_km": round(avg_extra, 1) if avg_extra is not None else None,
                # A search that showed alternatives but none was chosen.
                "abandonment_rate": _rate(with_alts - searches_selected, with_alts),
            }
        )

    counts = metrics.local_counts()
    live, cached = counts.get("search_live", 0), counts.get("search_cache", 0)
    return {
        "source": "simulated",  # the railway data is always simulated
        "visitors": source,  # which visitors this read-out covers: all | live | simulated
        "population": population,
        "station_distance": station_distance,
        "degradation": {
            "current_level": flags.environment_level(),
            "searches_live": live,
            "searches_cache": cached,
            "cache_share": _rate(cached, live + cached),
            "matches_served": counts.get("matches_served", 0),
            "matches_paused": counts.get("match_paused", 0),
            "note": "Counters are per API process since its last restart.",
        },
        "matching": [
            {
                "strategy": s,
                "offers_with_matches": int(o or 0),
                "accepted": int(a or 0),
                "acceptance_rate": _rate(int(a or 0), int(o or 0)),
                # What the offers cost on average, over offers that had matches.
                "avg_matches_offered": _round(avg_offered, 1),
                "avg_group_size": _round(avg_group, 1),
                "avg_pickup_km": _round(avg_km, 1),
                "avg_day_shift": _round(avg_days, 2),
                "avg_time_gap_min": _round(avg_gap, 0),
            }
            for s, o, a, avg_offered, avg_group, avg_km, avg_days, avg_gap in strategies
        ],
        "matching_legacy_offers_excluded": legacy_offers,
    }
