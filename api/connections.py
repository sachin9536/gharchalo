"""Multi-leg journeys (train, bus, shared cab) over SIMULATED services.

Used when no train or bus with seats runs the whole way, or on request. Every
rule below exists so that an itinerary a person could actually follow comes
out, not just a chain of rows that happen to share a city:

  * a change at one station needs MIN_CHANGE_MIN; changing between two stations
    of a city adds STATION_CHANGE_MIN_PER_KM per km between them;
  * waits over MAX_LAYOVER_MIN and journeys over MAX_TOTAL_HOURS are dropped;
  * shared cabs leave only between CAB_FIRST and CAB_LAST, CAB_BUFFER_MIN after
    you arrive, and only for hops up to CAB_MAX_ROAD_KM;
  * only services with free seats are used; the first leg leaves on the travel date;
  * no city is visited twice, and there are at most MAX_LEGS legs.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

import models
from fares import cab_per_person, cab_total_fare, road_km
from geo import haversine_km
from schemas import StationOut

MAX_LEGS = 3
MIN_CHANGE_MIN = 90
STATION_CHANGE_MIN_PER_KM = 3
MAX_LAYOVER_MIN = 10 * 60
MAX_TOTAL_HOURS = 40
CAB_BUFFER_MIN = 20
CAB_FIRST = dt.time(5, 0)
CAB_LAST = dt.time(22, 30)
CAB_MAX_ROAD_KM = 450
CAB_SPEED_KMH = 55
CAB_PEOPLE = 3  # fares are quoted as one share of a 3-person cab
MAX_NODES = 50_000  # safety valve on the search
RESULTS = 5
PER_SIGNATURE = 2  # keep the list varied: at most this many per city-and-mode path


class LegOut(BaseModel):
    mode: Literal["train", "bus", "cab"]
    number: str | None
    name: str
    operator: str
    travel_class: str | None
    origin: StationOut
    destination: StationOut
    depart_at: dt.datetime
    arrive_at: dt.datetime
    duration_minutes: int
    fare: int  # INR; for a cab, one share of a 3-person cab (estimate)
    seats_available: int | None  # None for cabs
    estimated: bool
    wait_before_minutes: int  # 0 for the first leg
    change_note: str | None  # e.g. moving between two stations of the same city


class ItineraryOut(BaseModel):
    legs: list[LegOut]
    depart_at: dt.datetime
    arrive_at: dt.datetime
    total_minutes: int
    waiting_minutes: int
    total_fare: int
    changes: int
    tags: list[str]


@dataclass(frozen=True)
class Leg:
    mode: str
    number: str | None
    name: str
    operator: str
    travel_class: str | None
    origin: models.Station
    dest: models.Station
    depart: dt.datetime
    arrive: dt.datetime
    fare: int
    seats: int | None
    estimated: bool = False


def _minutes(delta: dt.timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _station_km(a: models.Station, b: models.Station) -> float:
    return haversine_km((a.lat, a.lon), (b.lat, b.lon))


def _change_minutes(arrived_at: models.Station, departs_from: models.Station) -> int:
    if arrived_at.code == departs_from.code:
        return MIN_CHANGE_MIN
    return MIN_CHANGE_MIN + round(_station_km(arrived_at, departs_from) * STATION_CHANGE_MIN_PER_KM)


def _cab_departure(earliest: dt.datetime) -> dt.datetime:
    if earliest.time() < CAB_FIRST:
        return dt.datetime.combine(earliest.date(), CAB_FIRST)
    if earliest.time() > CAB_LAST:
        return dt.datetime.combine(earliest.date() + dt.timedelta(days=1), CAB_FIRST)
    return earliest


def _service_legs(services: list[models.Service], stations: dict[str, models.Station]) -> list[Leg]:
    """One leg per train/bus; for trains, the cheapest class that still has seats."""
    cheapest: dict[tuple, models.Service] = {}
    for s in services:
        key = (s.mode, s.number, s.depart_at, s.origin_code, s.dest_code)
        if key not in cheapest or s.fare < cheapest[key].fare:
            cheapest[key] = s
    return [
        Leg(
            mode=s.mode, number=s.number, name=s.name, operator=s.operator, travel_class=s.travel_class,
            origin=stations[s.origin_code], dest=stations[s.dest_code], depart=s.depart_at, arrive=s.arrive_at,
            fare=s.fare, seats=s.seats_available,
        )
        for s in cheapest.values()
    ]


def plan(
    stations: dict[str, models.Station],
    services: list[models.Service],
    origin: models.Station,
    dest_city: str,
    date: dt.date,
    start_stations: dict[str, float] | None = None,
) -> list[ItineraryOut]:
    """`services` must already be limited to seats > 0 and to [date, date + 2 days).

    `start_stations` maps station code -> km from `origin` for the stations the
    first leg may leave from (default: only `origin`). Callers pass the stations
    within the user's distance limit, so connections respect the same cohort
    limit as nearby-station alternatives.
    """
    start_stations = start_stations or {origin.code: 0.0}
    start = dt.datetime.combine(date, dt.time.min)
    end_of_travel_day = start + dt.timedelta(days=1)

    legs_by_city: dict[str, list[Leg]] = defaultdict(list)
    for leg in _service_legs(services, stations):
        legs_by_city[leg.origin.city].append(leg)
    for legs in legs_by_city.values():
        legs.sort(key=lambda leg: leg.depart)
    departs_by_city = {city: [leg.depart for leg in legs] for city, legs in legs_by_city.items()}

    primary = {s.city: s for s in stations.values() if s.is_primary}
    cities = list(primary)
    found: list[list[Leg]] = []
    nodes = 0

    def cab_leg(frm: models.Station, to_city: str, ready: dt.datetime, first: bool) -> Leg | None:
        to = primary[to_city]
        km = road_km((frm.lat, frm.lon), (to.lat, to.lon))
        if km > CAB_MAX_ROAD_KM:
            return None
        depart = _cab_departure(ready + dt.timedelta(minutes=CAB_BUFFER_MIN))
        if not first and _minutes(depart - ready) > MAX_LAYOVER_MIN:
            return None
        if first and depart >= end_of_travel_day:
            return None
        arrive = depart + dt.timedelta(minutes=round(km / CAB_SPEED_KMH * 60) + 15)
        return Leg(
            mode="cab", number=None, name=f"Shared cab to {to.city}", operator="Shared cab (estimate)",
            travel_class=None, origin=frm, dest=to, depart=depart, arrive=arrive,
            fare=cab_per_person(cab_total_fare(km), CAB_PEOPLE), seats=None, estimated=True,
        )

    def extend(legs: list[Leg], leg: Leg, visited: frozenset[str]):
        first_depart = legs[0].depart if legs else leg.depart
        if leg.arrive - first_depart > dt.timedelta(hours=MAX_TOTAL_HOURS):
            return
        chain = [*legs, leg]
        if leg.dest.city == dest_city:
            if len(chain) >= 2 or leg.mode == "cab":  # a lone train/bus is a direct option, not a connection
                found.append(chain)
            return
        walk(chain, visited | {leg.dest.city})

    def walk(legs: list[Leg], visited: frozenset[str]):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or len(legs) >= MAX_LEGS:
            return
        first = not legs
        city = origin.city if first else legs[-1].dest.city
        here = origin if first else legs[-1].dest
        ready = start if first else legs[-1].arrive

        candidates = legs_by_city.get(city, [])
        if first:
            options = [l for l in candidates if l.origin.code in start_stations and start <= l.depart < end_of_travel_day]
        else:
            lo = bisect_left(departs_by_city.get(city, []), ready + dt.timedelta(minutes=MIN_CHANGE_MIN))
            options = []
            for l in candidates[lo:]:
                if _minutes(l.depart - ready) > MAX_LAYOVER_MIN:
                    break
                if l.depart >= ready + dt.timedelta(minutes=_change_minutes(here, l.origin)):
                    options.append(l)
        for leg in options:
            if leg.dest.city not in visited:
                extend(legs, leg, visited)

        if not first and legs[-1].mode == "cab":
            return  # never chain two cabs
        for to_city in cities:
            if to_city in visited:
                continue
            cab = cab_leg(here, to_city, ready, first)
            if cab is not None:
                extend(legs, cab, visited)

    walk([], frozenset({origin.city}))
    return _select(found, origin, start_stations)


def _signature(legs: list[Leg]) -> tuple:
    return tuple((l.mode, l.origin.city, l.dest.city) for l in legs)


def _select(found: list[list[Leg]], origin: models.Station, start_stations: dict[str, float]) -> list[ItineraryOut]:
    # Earliest arrival first, then fewer changes, then cheaper.
    ranked = sorted(found, key=lambda legs: (legs[-1].arrive, len(legs), sum(l.fare for l in legs)))
    seen: set[tuple] = set()
    per_signature: dict[tuple, int] = defaultdict(int)
    chosen: list[list[Leg]] = []
    for legs in ranked:
        ident = tuple((l.mode, l.number, l.depart) for l in legs)
        sig = _signature(legs)
        if ident in seen or per_signature[sig] >= PER_SIGNATURE:
            continue
        seen.add(ident)
        per_signature[sig] += 1
        chosen.append(legs)
        if len(chosen) == RESULTS:
            break

    outs = [_to_out(legs, origin, start_stations) for legs in chosen]
    if outs:
        _tag(outs)
    return outs


def _station_out(s: models.Station) -> StationOut:
    return StationOut(code=s.code, name=s.name, city=s.city)


def _to_out(legs: list[Leg], origin: models.Station, start_stations: dict[str, float]) -> ItineraryOut:
    leg_outs: list[LegOut] = []
    waiting = 0
    for i, leg in enumerate(legs):
        wait, note = 0, None
        if i == 0 and leg.origin.code != origin.code:
            note = f"Start at {leg.origin.name}, about {round(start_stations[leg.origin.code])} km from {origin.name}"
        if i > 0:
            prev = legs[i - 1]
            wait = _minutes(leg.depart - prev.arrive)
            waiting += wait
            if prev.dest.code != leg.origin.code:
                note = (
                    f"Change stations: {prev.dest.name} to {leg.origin.name}, "
                    f"about {round(_station_km(prev.dest, leg.origin))} km"
                )
        leg_outs.append(
            LegOut(
                mode=leg.mode,  # type: ignore[arg-type]
                number=leg.number, name=leg.name, operator=leg.operator, travel_class=leg.travel_class,
                origin=_station_out(leg.origin), destination=_station_out(leg.dest),
                depart_at=leg.depart, arrive_at=leg.arrive, duration_minutes=_minutes(leg.arrive - leg.depart),
                fare=leg.fare, seats_available=leg.seats, estimated=leg.estimated,
                wait_before_minutes=wait, change_note=note,
            )
        )
    return ItineraryOut(
        legs=leg_outs,
        depart_at=legs[0].depart,
        arrive_at=legs[-1].arrive,
        total_minutes=_minutes(legs[-1].arrive - legs[0].depart),
        waiting_minutes=waiting,
        total_fare=sum(l.fare for l in legs),
        changes=len(legs) - 1,
        tags=[],
    )


def _tag(outs: list[ItineraryOut]) -> None:
    fastest = min(outs, key=lambda o: o.total_minutes)
    cheapest = min(outs, key=lambda o: o.total_fare)
    fewest = min(outs, key=lambda o: (o.changes, o.total_minutes))
    if len(outs) > 1:
        fastest.tags.append("Fastest")
        cheapest.tags.append("Cheapest")
        if fewest.changes < max(o.changes for o in outs):
            fewest.tags.append("Fewest changes")
