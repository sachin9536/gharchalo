import asyncio
import datetime as dt
import logging

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import config
import matching
import models
import sarvam
import search
from db import get_session
from journey import Journey, build_journey

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

app = FastAPI(title="GharChalo API")


class VoiceResponse(BaseModel):
    transcript: str
    language_code: str | None
    journey: Journey
    source: str  # "sarvam" or "stub" (X-Load-Test)
    # Trains and co-traveller matches are added here once /search and /match exist.


class ParseRequest(BaseModel):
    text: str


@app.get("/healthz")
def healthz():
    return {"status": "ok", "sarvam_configured": bool(config.SARVAM_API_KEY)}


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


@app.post("/voice", response_model=VoiceResponse)
async def voice(
    file: UploadFile = File(...),
    x_load_test: str | None = Header(default=None),
):
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


@app.get("/search", response_model=search.SearchResponse)
def search_journeys(
    origin: str,
    dest: str,
    date: dt.date,
    # Temporary query parameter: Flagsmith's station-distance cohort (5 / 15 / 30) replaces it.
    max_station_distance_km: int = Query(15, ge=0, le=search.MAX_ALTERNATIVE_KM),
    include_connections: bool = False,
    session: Session = Depends(get_session),
):
    try:
        return search.search(
            session, origin.strip().upper(), dest.strip().upper(), date, max_station_distance_km, include_connections
        )
    except search.UnknownStation as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except search.SameCity as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    # Temporary request fields: Flagsmith's matching_strategy / matching_config replace them.
    strategy: matching.Strategy = "exact"

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
    try:
        match_id, found = matching.find_matches(
            session,
            user_id=body.user_id,
            origin_code=body.origin.strip().upper(),
            dest_code=body.dest.strip().upper(),
            date=body.date,
            window_start=body.window_start,
            window_end=body.window_end,
            strategy=body.strategy,
        )
    except search.UnknownStation as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except search.SameCity as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _db_unavailable(exc) from exc
    return matching.MatchResponse(
        match_id=match_id,
        strategy=body.strategy,
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
    return AcceptResponse(match_id=event.id, accepted=event.accepted)
