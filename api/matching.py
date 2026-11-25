"""Co-traveller matching over SIMULATED travellers.

Two strategies (a Flagsmith A/B: the `matching_strategy` flag picks one per visitor):

  exact         your pickup STATION, your day, and a time window that overlaps yours.
  time_window   ("flexible") nearby pickup stations within `flex_pickup_km`, +/- `date_flex_days`
                days, and windows widened by `time_window_min` minutes on each side.

Both require the same origin and destination CITY pair (a shared cab drops people anywhere in
the destination city). Every relaxation is a number in the `matching_config` flag, so it can be
tuned live from the Flagsmith dashboard. Each match carries what flexibility cost you: how far
its pickup is from yours, how many days away, and how far apart the time windows are.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from geo import haversine_km
from search import SameCity, StationOut, UnknownStation

Strategy = Literal["exact", "time_window"]

DEFAULT_CONFIG = {
    "max_matches": 8,
    "exact_pickup_km": 0,  # 0 = the very same station
    "flex_pickup_km": 15,  # how far a flexible match's pickup may be from yours
    "date_flex_days": 1,
    "time_window_min": 120,
}

MAX_GROUP = 4  # a cab seats you plus up to three others


class MatchOut(BaseModel):
    traveller_id: int
    name: str
    date: dt.date
    window_start: dt.time
    window_end: dt.time
    pickup: StationOut
    drop: StationOut
    shift: Literal["exact", "flexible"]  # "flexible" = needed some relaxation
    pickup_km: float = 0.0  # this match's pickup station, from yours
    day_shift: int = 0  # their day minus yours (-1, 0, +1 ...)
    time_gap_min: int = 0  # minutes between the two time windows (0 = they overlap)


class MatchResponse(BaseModel):
    source: Literal["simulated"] = "simulated"
    match_id: int | None  # the logged offer; None when matching is paused (tatkal_level 3)
    strategy: Strategy
    offered: int
    suggested_group_size: int  # you + matches, capped at a 4-seat cab
    matches: list[MatchOut]
    paused: bool = False  # tatkal_level 3: matching paused under load (HTTP 200, nothing written)
    retry_after_s: int | None = None


@dataclass(frozen=True)
class Candidate:
    traveller: models.Traveller
    pickup_km: float
    day_shift: int
    time_gap_min: int

    @property
    def is_exact(self) -> bool:
        return self.pickup_km == 0 and self.day_shift == 0 and self.time_gap_min == 0


def _minutes(t: dt.time) -> int:
    return t.hour * 60 + t.minute


def _gap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Minutes between two windows; 0 when they overlap (touching counts: 18-22 meets 22-23)."""
    return max(0, b_start - a_end, a_start - b_end)


def _station_out(s: models.Station) -> StationOut:
    return StationOut(code=s.code, name=s.name, city=s.city)


def group_size(matches: int) -> int:
    return min(MAX_GROUP, 1 + matches)


def candidates(
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
) -> list[Candidate]:
    """Everyone who fits `strategy`, best fit first. Reads only: writes nothing."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    if origin_code not in stations:
        raise UnknownStation(f"Unknown origin station {origin_code!r}")
    if dest_code not in stations:
        raise UnknownStation(f"Unknown destination station {dest_code!r}")
    pickup = stations[origin_code]
    origin_city, dest_city = pickup.city, stations[dest_code].city
    if origin_city == dest_city:
        raise SameCity("Origin and destination are in the same city")

    flexible = strategy == "time_window"
    radius_km = float(cfg["flex_pickup_km"] if flexible else cfg["exact_pickup_km"])
    flex_days = int(cfg["date_flex_days"]) if flexible else 0
    widen = int(cfg["time_window_min"]) if flexible else 0

    rows = session.scalars(
        select(models.Traveller).where(
            models.Traveller.origin_code.in_([c for c, s in stations.items() if s.city == origin_city]),
            models.Traveller.dest_code.in_([c for c, s in stations.items() if s.city == dest_city]),
            models.Traveller.travel_date >= date - dt.timedelta(days=flex_days),
            models.Traveller.travel_date <= date + dt.timedelta(days=flex_days),
            models.Traveller.user_id != user_id,
        )
    )

    want_start, want_end = _minutes(window_start), _minutes(window_end)
    found: list[Candidate] = []
    for t in rows:
        their = stations[t.origin_code]
        km = haversine_km((pickup.lat, pickup.lon), (their.lat, their.lon))
        if km > radius_km + 1e-9:
            continue
        gap = _gap(want_start, want_end, _minutes(t.window_start), _minutes(t.window_end))
        # Each side's window is widened, so a 2 h setting means "within about four hours of each other".
        if gap > 2 * widen:
            continue
        found.append(
            Candidate(t, pickup_km=round(km, 1) if km > 1e-9 else 0.0, day_shift=(t.travel_date - date).days, time_gap_min=gap)
        )

    # Exact fits first, then fewest days away, then closest pickup, then the smallest time gap.
    found.sort(key=lambda c: (not c.is_exact, abs(c.day_shift), c.pickup_km, c.time_gap_min, c.traveller.id))
    return found[: int(cfg["max_matches"])]


def to_out(c: Candidate, stations: dict[str, models.Station]) -> MatchOut:
    t = c.traveller
    return MatchOut(
        traveller_id=t.id,
        name=t.name,
        date=t.travel_date,
        window_start=t.window_start,
        window_end=t.window_end,
        pickup=_station_out(stations[t.origin_code]),
        drop=_station_out(stations[t.dest_code]),
        shift="exact" if c.is_exact else "flexible",
        pickup_km=c.pickup_km,
        day_shift=c.day_shift,
        time_gap_min=c.time_gap_min,
    )


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
    """Find matches, log the offer with what it cost, and return (match_id, matches)."""
    chosen = candidates(
        session,
        user_id=user_id,
        origin_code=origin_code,
        dest_code=dest_code,
        date=date,
        window_start=window_start,
        window_end=window_end,
        strategy=strategy,
        config=config,
    )
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    matches = [to_out(c, stations) for c in chosen]

    n = len(chosen)
    event = models.MatchEvent(
        user_id=user_id,
        strategy=strategy,
        offered=n,
        group_size=group_size(n),
        avg_pickup_km=round(sum(c.pickup_km for c in chosen) / n, 2) if n else None,
        avg_day_shift=round(sum(abs(c.day_shift) for c in chosen) / n, 2) if n else None,
        avg_time_gap_min=round(sum(c.time_gap_min for c in chosen) / n, 1) if n else None,
    )
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
