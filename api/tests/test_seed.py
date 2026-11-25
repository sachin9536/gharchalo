import datetime as dt

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import models
import stations
from geo import haversine_km
from seed import N_TRAVELLERS, seed
from seed_data import CITY_PAIRS, DEMO_DATE, STATIONS


def _engine():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


@pytest.fixture(scope="module")
def db():
    engine = _engine()
    counts = seed(engine)
    with Session(engine) as session:
        yield session, counts


def _city(code):
    return next(s.city for s in STATIONS if s.code == code)


def _coords(code):
    s = next(s for s in STATIONS if s.code == code)
    return s.lat, s.lon


# --- reference data --------------------------------------------------------

def test_every_city_has_exactly_one_primary_station():
    by_city = {}
    for s in STATIONS:
        by_city.setdefault(s.city, []).append(s)
    for city, group in by_city.items():
        assert sum(s.is_primary for s in group) == 1, city


def test_route_cities_all_exist():
    cities = {s.city for s in STATIONS}
    for a, b in CITY_PAIRS:
        assert a in cities and b in cities


def test_station_codes_unique():
    codes = [s.code for s in STATIONS]
    assert len(codes) == len(set(codes))


def test_city_name_resolves_to_primary_but_other_stations_by_own_name():
    assert stations.resolve("Bangalore").code == "SBC"
    assert stations.resolve("Hyderabad").code == "HYB"
    assert stations.resolve("Secunderabad").code == "SC"
    assert stations.resolve("Yeshwantpur").code == "YPR"
    assert stations.resolve("Delhi").code == "NDLS"


# --- generated data --------------------------------------------------------

def test_counts_and_foreign_keys(db):
    session, counts = db
    assert counts["travellers"] == N_TRAVELLERS
    assert counts["trains"] > 400 and counts["buses"] > 100
    codes = set(session.scalars(select(models.Station.code)))
    for col in (models.Service.origin_code, models.Service.dest_code, models.Traveller.origin_code, models.Traveller.dest_code):
        assert set(session.scalars(select(col))) <= codes


def test_no_service_has_same_origin_and_destination_city(db):
    session, _ = db
    for s in session.scalars(select(models.Service)):
        assert _city(s.origin_code) != _city(s.dest_code)


def test_availability_is_consistent(db):
    session, _ = db
    for s in session.scalars(select(models.Service)):
        assert 0 <= s.seats_available <= s.seats_total
        if s.seats_available > 0:
            assert s.waitlist == 0
        assert s.arrive_at > s.depart_at
        assert s.fare >= 150


def test_train_numbers_cannot_be_mistaken_for_real_ones(db):
    session, _ = db
    for number in session.scalars(select(models.Service.number).where(models.Service.mode == "train")):
        assert number.startswith("9")


def test_seed_is_deterministic():
    def snapshot():
        e = _engine()
        seed(e)
        with Session(e) as s:
            services = s.execute(select(models.Service.number, models.Service.seats_available, models.Service.fare).order_by(models.Service.id)).all()
            people = s.execute(select(models.Traveller.name, models.Traveller.travel_date).order_by(models.Traveller.id)).all()
        return services, people

    assert snapshot() == snapshot()


# --- the scripted demo -----------------------------------------------------

def _blr_to_hyd_trains(session):
    out = []
    for s in session.scalars(select(models.Service).where(models.Service.mode == "train")):
        if s.depart_at.date() == DEMO_DATE and _city(s.origin_code) == "Bengaluru" and _city(s.dest_code) == "Hyderabad":
            out.append(s)
    return out


def test_demo_main_station_trains_are_all_waitlisted(db):
    session, _ = db
    from_sbc = [s for s in _blr_to_hyd_trains(session) if s.origin_code == "SBC"]
    assert from_sbc, "demo needs at least one train from the preferred station"
    assert all(s.seats_available == 0 and s.waitlist > 0 for s in from_sbc)


def test_demo_only_alternative_station_trains_have_seats(db):
    session, _ = db
    with_seats = {s.origin_code for s in _blr_to_hyd_trains(session) if s.seats_available > 0}
    assert with_seats == {"BNC", "SMVB", "BID"}


def test_demo_alternatives_split_the_5_15_30_km_cohorts(db):
    session, _ = db
    sbc = _coords("SBC")
    km = {code: haversine_km(sbc, _coords(code)) for code in ("BNC", "SMVB", "BID")}
    assert km["BNC"] <= 5
    assert 5 < km["SMVB"] <= 15
    assert 15 < km["BID"] <= 30
    # So the cohorts are offered 1, 2 and 3 alternative stations respectively.
    for limit, expected in ((5, 1), (15, 2), (30, 3)):
        assert sum(d <= limit for d in km.values()) == expected


def test_demo_bus_from_preferred_station_has_seats(db):
    session, _ = db
    buses = [
        s for s in session.scalars(select(models.Service).where(models.Service.mode == "bus"))
        if s.depart_at.date() == DEMO_DATE and s.origin_code == "SBC" and _city(s.dest_code) == "Hyderabad"
    ]
    assert any(b.seats_available > 0 for b in buses)


def _overlaps(t, start, end):
    return t.window_start <= end and t.window_end >= start


def test_demo_exactly_three_exact_cab_matches(db):
    session, _ = db
    want_start, want_end = dt.time(18), dt.time(22)
    exact = [
        t for t in session.scalars(select(models.Traveller))
        if t.travel_date == DEMO_DATE
        and _city(t.origin_code) == "Bengaluru"
        and _city(t.dest_code) == "Hyderabad"
        and _overlaps(t, want_start, want_end)
    ]
    assert len(exact) == 3
    assert len({t.origin_code for t in exact}) == 3  # different pickup stations on purpose


def test_demo_flexible_matching_finds_more_than_exact(db):
    session, _ = db
    flexible = [
        t for t in session.scalars(select(models.Traveller))
        if abs((t.travel_date - DEMO_DATE).days) <= 1
        and _city(t.origin_code) == "Bengaluru"
        and _city(t.dest_code) == "Hyderabad"
    ]
    assert len(flexible) == 7


def test_other_routes_have_travellers_too(db):
    session, _ = db
    n = session.scalar(select(func.count()).select_from(models.Traveller))
    assert n == N_TRAVELLERS
    kota = [
        t for t in session.scalars(select(models.Traveller))
        if _city(t.dest_code) == "Kota"
    ]
    assert kota  # the sponsor brief's Bengaluru -> Kota style requests find someone


def test_is_seeded_reflects_state():
    from seed import is_seeded

    engine = _engine()
    assert is_seeded(engine) is False  # no tables yet
    seed(engine)
    assert is_seeded(engine) is True
