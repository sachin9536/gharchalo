import datetime as dt
import itertools
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import connections as c
import models
from db import get_session
from geo import haversine_km
from main import app
from seed import seed
from seed_data import DEMO_DATE

DEMO = DEMO_DATE.isoformat()


@pytest.fixture(scope="module")
def world():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with Session(engine) as session:
        stations = {s.code: s for s in session.scalars(select(models.Station))}
    yield TestClient(app), engine, stations
    app.dependency_overrides.clear()


def _services(engine, date):
    start = dt.datetime.combine(date, dt.time.min)
    with Session(engine) as session:
        return list(
            session.scalars(
                select(models.Service).where(
                    models.Service.seats_available > 0,
                    models.Service.depart_at >= start,
                    models.Service.depart_at < start + dt.timedelta(days=2),
                )
            )
        )


def _starts(stations, origin, km):
    d = {code: haversine_km((origin.lat, origin.lon), (s.lat, s.lon)) for code, s in stations.items()}
    return {code: v for code, v in d.items() if v <= km}


def _check(it, *, date, dest_city, starts, stations, real_services):
    """Everything a person following this itinerary would need to be true."""
    legs = it.legs
    assert 1 <= len(legs) <= c.MAX_LEGS
    if len(legs) == 1:
        assert legs[0].mode == "cab"  # a lone train/bus is a direct option, not a connection

    assert legs[0].depart_at.date() == date
    assert legs[0].origin.code in starts
    assert legs[-1].destination.city == dest_city

    cities = [legs[0].origin.city] + [leg.destination.city for leg in legs]
    assert len(cities) == len(set(cities)), f"revisits a city: {cities}"

    waits = 0
    for i, leg in enumerate(legs):
        assert leg.arrive_at > leg.depart_at
        assert leg.duration_minutes == int((leg.arrive_at - leg.depart_at).total_seconds() // 60)
        assert leg.origin.city != leg.destination.city
        if leg.mode == "cab":
            assert leg.estimated and leg.seats_available is None and leg.number is None
            assert dt.time(5, 0) <= leg.depart_at.time() <= dt.time(22, 30)
            assert legs[i - 1].mode != "cab" if i else True  # never two cabs in a row
        else:
            assert not leg.estimated and leg.seats_available and leg.seats_available > 0
            assert (leg.mode, leg.number, leg.depart_at) in real_services  # an actual seeded service
        if i == 0:
            assert leg.wait_before_minutes == 0
            continue
        prev = legs[i - 1]
        assert leg.origin.city == prev.destination.city
        wait = int((leg.depart_at - prev.arrive_at).total_seconds() // 60)
        assert wait == leg.wait_before_minutes
        waits += wait
        assert wait <= c.MAX_LAYOVER_MIN
        if leg.mode == "cab":
            assert wait >= c.CAB_BUFFER_MIN  # the cab picks you up at the station you arrived at
        elif prev.destination.code == leg.origin.code:
            assert wait >= c.MIN_CHANGE_MIN
        else:
            a, b = stations[prev.destination.code], stations[leg.origin.code]
            km = haversine_km((a.lat, a.lon), (b.lat, b.lon))
            assert wait >= c.MIN_CHANGE_MIN + round(km * c.STATION_CHANGE_MIN_PER_KM)
            assert leg.change_note and "Change stations" in leg.change_note

    assert it.total_minutes == int((legs[-1].arrive_at - legs[0].depart_at).total_seconds() // 60)
    assert it.total_minutes <= c.MAX_TOTAL_HOURS * 60
    assert it.waiting_minutes == waits
    assert it.total_fare == sum(leg.fare for leg in legs)
    assert it.changes == len(legs) - 1
    assert set(it.tags) <= {"Fastest", "Cheapest", "Fewest changes"}


# --- the property that matters: every journey we ever produce is followable ----

@pytest.mark.parametrize("date", [DEMO_DATE, dt.date(2026, 11, 29)])
@pytest.mark.parametrize("km", [0, 15, 30])
def test_every_itinerary_for_every_city_pair_obeys_the_timing_rules(world, date, km):
    _, engine, stations = world
    services = _services(engine, date)
    real = {(s.mode, s.number, s.depart_at) for s in services}
    primary = {s.city: s for s in stations.values() if s.is_primary}
    produced = 0
    for o, d in itertools.permutations(primary, 2):
        origin = primary[o]
        starts = _starts(stations, origin, km)
        results = c.plan(stations, services, origin, d, date, starts)
        assert len(results) <= c.RESULTS
        arrivals = [r.arrive_at for r in results]
        assert arrivals == sorted(arrivals)
        for it in results:
            _check(it, date=date, dest_city=d, starts=starts, stations=stations, real_services=real)
            produced += 1
    assert produced > 50  # the property test is not passing vacuously


def test_all_city_pairs_plan_quickly(world):
    _, engine, stations = world
    services = _services(engine, DEMO_DATE)
    primary = {s.city: s for s in stations.values() if s.is_primary}
    started = time.perf_counter()
    for o, d in itertools.permutations(primary, 2):
        c.plan(stations, services, primary[o], d, DEMO_DATE, _starts(stations, primary[o], 30))
    assert time.perf_counter() - started < 5


# --- unit rules ------------------------------------------------------------

def test_cab_departure_window():
    day = dt.date(2026, 11, 27)
    at = lambda h, m=0: dt.datetime.combine(day, dt.time(h, m))
    assert c._cab_departure(at(4, 0)) == at(5, 0)
    assert c._cab_departure(at(10, 15)) == at(10, 15)
    assert c._cab_departure(at(22, 30)) == at(22, 30)
    assert c._cab_departure(at(23, 0)) == dt.datetime.combine(day + dt.timedelta(days=1), dt.time(5, 0))


def test_changing_stations_takes_longer_than_staying(world):
    _, _, stations = world
    assert c._change_minutes(stations["SBC"], stations["SBC"]) == 90
    assert c._change_minutes(stations["SBC"], stations["BNC"]) > 90
    assert c._change_minutes(stations["SBC"], stations["BID"]) > c._change_minutes(stations["SBC"], stations["BNC"])


def test_no_services_means_no_journeys(world):
    _, _, stations = world
    assert c.plan(stations, [], stations["SBC"], "Jaipur", DEMO_DATE) == []


# --- through the API -------------------------------------------------------

def _search(client, origin, dest, km=15, date=DEMO, **extra):
    return client.get(
        "/search", params={"origin": origin, "dest": dest, "date": date, "max_station_distance_km": km, **extra}
    )


def test_route_with_no_direct_service_gets_connections_automatically(world):
    client, _, _ = world
    body = _search(client, "SBC", "JP").json()  # nothing runs Bengaluru -> Jaipur directly
    assert body["options"] == []
    assert body["connections_reason"] == "no_direct"
    assert body["connections"]
    for it in body["connections"]:
        assert len(it["legs"]) >= 2 or it["legs"][0]["mode"] == "cab"
        assert it["legs"][-1]["destination"]["city"] == "Jaipur"


def test_direct_seats_mean_no_connections_unless_requested(world):
    client, _, _ = world
    # Bengaluru -> Hyderabad on the demo day has bus seats, so nothing automatic.
    plain = _search(client, "SBC", "HYB").json()
    assert plain["connections"] == [] and plain["connections_reason"] is None
    asked = _search(client, "SBC", "HYB", include_connections="true").json()
    assert asked["connections_reason"] == "requested"
    assert asked["connections"]
    assert all(len(it["legs"]) >= 2 or it["legs"][0]["mode"] == "cab" for it in asked["connections"])


def test_distance_limit_controls_where_journeys_may_start(world):
    client, _, stations = world
    for km in (0, 5, 15, 30):
        body = _search(client, "SBC", "JP", km=km, include_connections="true").json()
        allowed = {code for code, s in stations.items() if haversine_km((stations["SBC"].lat, stations["SBC"].lon), (s.lat, s.lon)) <= km}
        assert allowed >= {it["legs"][0]["origin"]["code"] for it in body["connections"]}
    far = _search(client, "SBC", "KOTA", km=30, include_connections="true").json()
    started_elsewhere = [it for it in far["connections"] if it["legs"][0]["origin"]["code"] != "SBC"]
    assert started_elsewhere, "30 km should let some journeys start from a nearby station"
    note = started_elsewhere[0]["legs"][0]["change_note"]
    assert note.startswith("Start at ") and "KSR Bengaluru City" in note


def test_no_services_that_day_gives_no_connections(world):
    client, _, _ = world
    body = _search(client, "SBC", "JP", date="2030-01-01").json()
    assert body["connections"] == [] and body["connections_reason"] == "no_direct"


def test_tags_mark_fastest_and_cheapest(world):
    client, _, _ = world
    its = _search(client, "SBC", "JP").json()["connections"]
    assert len(its) > 1
    fastest = min(its, key=lambda i: i["total_minutes"])
    cheapest = min(its, key=lambda i: i["total_fare"])
    assert "Fastest" in fastest["tags"] and "Cheapest" in cheapest["tags"]


# --- boundaries, with hand-built services (the seeded data never hits them) ----

def _svc(n, origin, dest, depart, arrive):
    return models.Service(
        id=n, mode="train", number=f"9{n:04d}", name=f"Test {n}", operator="T", travel_class="SL",
        origin_code=origin, dest_code=dest, depart_at=depart, arrive_at=arrive, fare=500,
        seats_total=10, seats_available=5, waitlist=0,
    )


def _two_trains(stations, arrive_at_station, depart_from_station, wait_minutes):
    """Bengaluru -> Hyderabad, then Hyderabad -> Delhi after `wait_minutes`."""
    first_depart = dt.datetime.combine(DEMO_DATE, dt.time(20, 0))
    first_arrive = first_depart + dt.timedelta(hours=10)
    second_depart = first_arrive + dt.timedelta(minutes=wait_minutes)
    services = [
        _svc(1, "SBC", arrive_at_station, first_depart, first_arrive),
        _svc(2, depart_from_station, "NDLS", second_depart, second_depart + dt.timedelta(hours=20)),
    ]
    return c.plan(stations, services, stations["SBC"], "Delhi", DEMO_DATE)


@pytest.mark.parametrize(
    "arrive_at,depart_from,wait,expected",
    [
        ("HYB", "HYB", 89, False),   # one minute short of the 90-minute change
        ("HYB", "HYB", 90, True),
        ("HYB", "HYB", 600, True),   # exactly the longest wait we accept
        ("HYB", "HYB", 601, False),  # a minute too long
        ("HYB", "SC", 100, False),   # different stations need more than 90 minutes
        ("HYB", "SC", 150, True),
    ],
)
def test_change_and_layover_boundaries(world, arrive_at, depart_from, wait, expected):
    _, _, stations = world
    found = _two_trains(stations, arrive_at, depart_from, wait)
    assert bool(found) is expected
    if found:
        assert [leg.mode for leg in found[0].legs] == ["train", "train"]


def test_waitlisted_trains_are_never_used(world):
    _, engine, stations = world
    # The caller filters seats > 0 (search does); plan trusts that. Prove search really does.
    client = TestClient(app)
    for it in _search(client, "SBC", "JP").json()["connections"]:
        for leg in it["legs"]:
            if leg["mode"] != "cab":
                assert leg["seats_available"] > 0
