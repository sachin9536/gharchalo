"""Co-traveller matching over SIMULATED travellers.

Two strategies (the optional Flagsmith experiment; `exact` is the default):
  exact        same origin city, destination city and date; time windows overlap.
  time_window  the same, but +/- `date_flex_days` and each side's window widened
               by `time_window_min` minutes.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from search import SameCity, StationOut, UnknownStation

Strategy = Literal["exact", "time_window"]

DEFAULT_CONFIG = {"time_window_min": 120, "date_flex_days": 1, "max_matches": 8}


class MatchOut(BaseModel):
    traveller_id: int
    name: str
    date: dt.date
    window_start: dt.time
    window_end: dt.time
    pickup: StationOut
    drop: StationOut
    shift: Literal["exact", "flexible"]  # "flexible" = found only thanks to the wider strategy


class MatchResponse(BaseModel):
    source: Literal["simulated"] = "simulated"
    match_id: int | None  # the logged offer; None when matching is paused (tatkal_level 3)
    strategy: Strategy
    offered: int
    suggested_group_size: int  # you + matches, capped at a 4-seat cab
    matches: list[MatchOut]
    paused: bool = False  # tatkal_level 3: matching paused under load (HTTP 200, nothing written)
    retry_after_s: int | None = None


def _minutes(t: dt.time) -> int:
    return t.hour * 60 + t.minute


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end  # inclusive: 18:00-22:00 meets 22:00-23:00


def _station_out(s: models.Station) -> StationOut:
    return StationOut(code=s.code, name=s.name, city=s.city)


def find_matches(
    session: Session,
    *,
    user_id: str,
    origin_code: str,
    dest_code: str,
    date: dt.date,
    window_start: dt.time,
    window_end: dt.time,
    strategy: Strategy,
    config: dict | None = None,
) -> tuple[int, list[MatchOut]]:
    """Log an offer and return (match_id, matches)."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    if origin_code not in stations:
        raise UnknownStation(f"Unknown origin station {origin_code!r}")
    if dest_code not in stations:
        raise UnknownStation(f"Unknown destination station {dest_code!r}")
    origin_city, dest_city = stations[origin_code].city, stations[dest_code].city
    if origin_city == dest_city:
        raise SameCity("Origin and destination are in the same city")

    flexible = strategy == "time_window"
    flex_days = int(cfg["date_flex_days"]) if flexible else 0
    widen = int(cfg["time_window_min"]) if flexible else 0

    candidates = session.scalars(
        select(models.Traveller).where(
            models.Traveller.origin_code.in_([c for c, s in stations.items() if s.city == origin_city]),
            models.Traveller.dest_code.in_([c for c, s in stations.items() if s.city == dest_city]),
            models.Traveller.travel_date >= date - dt.timedelta(days=flex_days),
            models.Traveller.travel_date <= date + dt.timedelta(days=flex_days),
            models.Traveller.user_id != user_id,
        )
    )

    want_start, want_end = _minutes(window_start), _minutes(window_end)
    found: list[tuple[tuple, models.Traveller, bool]] = []
    for t in candidates:
        their_start, their_end = _minutes(t.window_start), _minutes(t.window_end)
        # Widen both sides, so a 2h setting means "within about two hours of each other".
        if not _overlap(want_start - widen, want_end + widen, their_start - widen, their_end + widen):
            continue
        is_exact = t.travel_date == date and _overlap(want_start, want_end, their_start, their_end)
        sort_key = (not is_exact, abs((t.travel_date - date).days), abs(their_start - want_start), t.id)
        found.append((sort_key, t, is_exact))

    found.sort(key=lambda item: item[0])
    chosen = found[: int(cfg["max_matches"])]

    matches = [
        MatchOut(
            traveller_id=t.id,
            name=t.name,
            date=t.travel_date,
            window_start=t.window_start,
            window_end=t.window_end,
            pickup=_station_out(stations[t.origin_code]),
            drop=_station_out(stations[t.dest_code]),
            shift="exact" if is_exact else "flexible",
        )
        for _, t, is_exact in chosen
    ]

    event = models.MatchEvent(user_id=user_id, strategy=strategy, offered=len(matches))
    session.add(event)
    session.commit()
    return event.id, matches


class AlreadyEmpty(Exception):
    """Tried to accept an offer that contained no matches."""


class UnknownMatch(Exception):
    pass


def accept(session: Session, match_id: int) -> models.MatchEvent:
    event = session.get(models.MatchEvent, match_id)
    if event is None:
        raise UnknownMatch(f"Unknown match {match_id}")
    if event.offered == 0:
        raise AlreadyEmpty("This offer had no matches to accept")
    event.accepted = True  # idempotent
    session.commit()
    return event
