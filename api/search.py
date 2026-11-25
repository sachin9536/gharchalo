"""Journey search over SIMULATED data (trains, buses, shared-cab estimate)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
import waitlist
from connections import ItineraryOut, plan as plan_connections
from fares import CAB_GROUP_SIZES, cab_per_person, cab_total_fare, road_km
from geo import haversine_km
from schemas import StationOut

# Alternatives beyond the user's limit are only *counted* up to this radius.
MAX_ALTERNATIVE_KM = 30


class UnknownStation(Exception):
    pass


class SameCity(Exception):
    pass


class OptionOut(BaseModel):
    id: int
    mode: Literal["train", "bus"]
    number: str
    name: str
    operator: str
    travel_class: str
    origin: StationOut
    destination: StationOut
    depart_at: dt.datetime
    arrive_at: dt.datetime
    duration_minutes: int
    fare: int  # INR, simulated estimate
    status: Literal["available", "waitlist"]
    seats_available: int
    waitlist: int
    distance_km: float | None = None  # alternatives only: preferred station -> this station
    confirm_chance: float | None = None  # waitlisted trains only: rule-of-thumb estimate (waitlist.py)


class CabShare(BaseModel):
    people: int
    per_person: int


class CabEstimate(BaseModel):
    distance_km: int
    total_fare: int
    shares: list[CabShare]
    note: str = "Estimated fare split. Real co-travellers come from /match."


class SearchResponse(BaseModel):
    source: Literal["simulated"] = "simulated"
    origin: StationOut
    destination: StationOut
    date: dt.date
    max_station_distance_km: int
    options: list[OptionOut]  # trains and buses leaving the preferred station
    preferred_station_has_train_seats: bool
    alternatives: list[OptionOut]  # train seats from nearby stations, only when the above is False
    more_alternatives_beyond_limit: int
    cab: CabEstimate
    # Multi-leg journeys (train/bus/shared cab). Filled when nothing direct has
    # seats ("no_direct") or when the caller asks for them ("requested").
    connections: list[ItineraryOut] = []
    connections_reason: Literal["no_direct", "requested"] | None = None
    # Flagsmith fields (additive; older clients can ignore them).
    connections_paused: bool = False  # tatkal_level >= 2 skips the multi-leg planner
    served_from: Literal["live", "cache"] = "live"  # tatkal_level 3 serves a short-lived cache
    tatkal_level: int = 0
    search_id: int | None = None  # logged Experiment B impression; POST /search/{id}/select


class DayAvailability(BaseModel):
    date: dt.date
    options: int  # direct trains and buses from the preferred station that day
    with_seats: int
    trains_with_seats: int
    buses_with_seats: int
    cheapest_with_seats: int | None  # INR, simulated estimate


class DateStrip(BaseModel):
    source: Literal["simulated"] = "simulated"
    origin: StationOut
    destination: StationOut
    center: dt.date
    days: list[DayAvailability]


def add_confirm_chances(resp: "SearchResponse", days_until_travel: int | None) -> "SearchResponse":
    """Attach a waitlist-confirmation estimate to every waitlisted train (buses have no waitlist)."""
    for option in resp.options:
        if option.mode == "train" and option.status == "waitlist":
            option.confirm_chance = waitlist.confirm_chance(option.waitlist, option.travel_class, days_until_travel)
    return resp


def date_strip(session: Session, origin_code: str, dest_code: str, center: dt.date, days: int = 3) -> DateStrip:
    """Direct availability from the preferred station on the days around `center` (one query)."""
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    if origin_code not in stations:
        raise UnknownStation(f"Unknown origin station {origin_code!r}")
    if dest_code not in stations:
        raise UnknownStation(f"Unknown destination station {dest_code!r}")
    origin, dest = stations[origin_code], stations[dest_code]
    if origin.city == dest.city:
        raise SameCity("Origin and destination are in the same city")

    first = center - dt.timedelta(days=days)
    dates = [first + dt.timedelta(days=i) for i in range(2 * days + 1)]
    rows = session.scalars(
        select(models.Service).where(
            models.Service.origin_code == origin.code,
            models.Service.dest_code.in_([c for c, s in stations.items() if s.city == dest.city]),
            models.Service.depart_at >= dt.datetime.combine(dates[0], dt.time.min),
            models.Service.depart_at < dt.datetime.combine(dates[-1] + dt.timedelta(days=1), dt.time.min),
        )
    )
    by_day: dict[dt.date, list[models.Service]] = {d: [] for d in dates}
    for svc in rows:
        by_day[svc.depart_at.date()].append(svc)

    out = []
    for d in dates:
        services = by_day[d]
        free = [s for s in services if s.seats_available > 0]
        out.append(
            DayAvailability(
                date=d,
                options=len(services),
                with_seats=len(free),
                trains_with_seats=sum(s.mode == "train" for s in free),
                buses_with_seats=sum(s.mode == "bus" for s in free),
                cheapest_with_seats=min((s.fare for s in free), default=None),
            )
        )
    return DateStrip(origin=_station_out(origin), destination=_station_out(dest), center=center, days=out)


def _station_out(s: models.Station) -> StationOut:
    return StationOut(code=s.code, name=s.name, city=s.city)


def _option(svc: models.Service, stations: dict[str, models.Station], distance_km: float | None = None) -> OptionOut:
    return OptionOut(
        id=svc.id,
        mode=svc.mode,  # type: ignore[arg-type]
        number=svc.number,
        name=svc.name,
        operator=svc.operator,
        travel_class=svc.travel_class,
        origin=_station_out(stations[svc.origin_code]),
        destination=_station_out(stations[svc.dest_code]),
        depart_at=svc.depart_at,
        arrive_at=svc.arrive_at,
        duration_minutes=int((svc.arrive_at - svc.depart_at).total_seconds() // 60),
        fare=svc.fare,
        status="available" if svc.seats_available > 0 else "waitlist",
        seats_available=svc.seats_available,
        waitlist=svc.waitlist,
        distance_km=None if distance_km is None else round(distance_km, 1),
    )


def _cab_estimate(origin: models.Station, dest: models.Station) -> CabEstimate:
    km = road_km((origin.lat, origin.lon), (dest.lat, dest.lon))
    total = cab_total_fare(km)
    return CabEstimate(
        distance_km=int(round(km)),
        total_fare=total,
        shares=[CabShare(people=n, per_person=cab_per_person(total, n)) for n in CAB_GROUP_SIZES],
    )


def search(
    session: Session,
    origin_code: str,
    dest_code: str,
    date: dt.date,
    max_station_distance_km: int,
    include_connections: bool = False,
    allow_connections: bool = True,
) -> SearchResponse:
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    if origin_code not in stations:
        raise UnknownStation(f"Unknown origin station {origin_code!r}")
    if dest_code not in stations:
        raise UnknownStation(f"Unknown destination station {dest_code!r}")
    origin, dest = stations[origin_code], stations[dest_code]
    if origin.city == dest.city:
        raise SameCity("Origin and destination are in the same city")

    # We travel to the destination *city*: arriving at Secunderabad is fine for Hyderabad.
    dest_codes = [s.code for s in stations.values() if s.city == dest.city]
    day_start = dt.datetime.combine(date, dt.time.min)
    day_end = day_start + dt.timedelta(days=1)

    def on_day(query):
        return query.where(
            models.Service.dest_code.in_(dest_codes),
            models.Service.depart_at >= day_start,
            models.Service.depart_at < day_end,
        ).order_by(models.Service.depart_at, models.Service.id)

    preferred = list(
        session.scalars(on_day(select(models.Service).where(models.Service.origin_code == origin.code)))
    )
    has_train_seats = any(s.mode == "train" and s.seats_available > 0 for s in preferred)

    nearby = {
        s.code: haversine_km((origin.lat, origin.lon), (s.lat, s.lon))
        for s in stations.values()
        if s.code != origin.code
    }
    nearby = {code: km for code, km in nearby.items() if km <= MAX_ALTERNATIVE_KM}

    alternatives: list[OptionOut] = []
    beyond_limit = 0
    if not has_train_seats:
        if nearby:
            candidates = session.scalars(
                on_day(
                    select(models.Service).where(
                        models.Service.mode == "train",
                        models.Service.seats_available > 0,
                        models.Service.origin_code.in_(nearby),
                    )
                )
            )
            shown = []
            for svc in candidates:
                if nearby[svc.origin_code] <= max_station_distance_km:
                    shown.append((nearby[svc.origin_code], svc))
                else:
                    beyond_limit += 1
            shown.sort(key=lambda pair: (pair[0], pair[1].depart_at))
            alternatives = [_option(svc, stations, km) for km, svc in shown]

    # Journeys with changes: only when asked, or when nothing direct has seats.
    reason: Literal["no_direct", "requested"] | None = None
    if not allow_connections:
        reason = None  # degraded: the planner is CPU-heavy (tatkal_level >= 2)
    elif include_connections:
        reason = "requested"
    elif not any(s.seats_available > 0 for s in preferred):
        reason = "no_direct"
    itineraries: list[ItineraryOut] = []
    if reason:
        window = session.scalars(
            select(models.Service).where(
                models.Service.seats_available > 0,
                models.Service.depart_at >= day_start,
                models.Service.depart_at < day_start + dt.timedelta(days=2),
            )
        )
        # The same distance limit as nearby-station alternatives applies to where the first leg may start.
        start_stations = {origin.code: 0.0} | {c: km for c, km in nearby.items() if km <= max_station_distance_km}
        itineraries = plan_connections(stations, list(window), origin, dest.city, date, start_stations)

    return SearchResponse(
        origin=_station_out(origin),
        destination=_station_out(dest),
        date=date,
        max_station_distance_km=max_station_distance_km,
        options=[_option(s, stations) for s in preferred],
        preferred_station_has_train_seats=has_train_seats,
        alternatives=alternatives,
        more_alternatives_beyond_limit=beyond_limit,
        cab=_cab_estimate(origin, dest),
        connections=itineraries,
        connections_reason=reason,
        connections_paused=not allow_connections,
    )
