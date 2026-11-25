import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import models
from db import get_session
from main import app
from seed import seed
from seed_data import DEMO_DATE, STATIONS

DEMO = DEMO_DATE.isoformat()


@pytest.fixture(scope="module")
def client():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app), engine
    app.dependency_overrides.clear()


def _search(c, origin="SBC", dest="HYB", date=DEMO, km=15):
    return c.get("/search", params={"origin": origin, "dest": dest, "date": date, "max_station_distance_km": km})


def test_response_is_labelled_simulated(client):
    c, _ = client
    r = _search(c)
    assert r.status_code == 200
    assert r.json()["source"] == "simulated"


def test_demo_preferred_station_is_full_but_bus_has_seats(client):
    c, _ = client
    body = _search(c).json()
    trains = [o for o in body["options"] if o["mode"] == "train"]
    buses = [o for o in body["options"] if o["mode"] == "bus"]
    assert body["preferred_station_has_train_seats"] is False
    assert trains and all(o["status"] == "waitlist" and o["waitlist"] > 0 for o in trains)
    assert any(o["status"] == "available" for o in buses)
    assert all(o["origin"]["code"] == "SBC" for o in body["options"])


@pytest.mark.parametrize(
    "km,expected",
    [(0, []), (5, ["BNC"]), (15, ["BNC", "SMVB"]), (30, ["BNC", "SMVB", "BID"])],
)
def test_demo_cohorts_see_one_two_three_alternatives(client, km, expected):
    c, _ = client
    body = _search(c, km=km).json()
    assert [a["origin"]["code"] for a in body["alternatives"]] == expected
    assert all(a["status"] == "available" and a["mode"] == "train" for a in body["alternatives"])
    assert body["more_alternatives_beyond_limit"] == 3 - len(expected)


def test_alternatives_carry_distance_sorted_nearest_first(client):
    c, _ = client
    alts = _search(c, km=30).json()["alternatives"]
    distances = [a["distance_km"] for a in alts]
    assert distances == sorted(distances)
    assert distances[0] < 5 < distances[1] < 15 < distances[2] <= 30


def test_alternatives_only_shown_when_preferred_station_has_no_train_seats(client):
    c, engine = client
    # Find any seeded search where the preferred station already has a train with seats.
    city = {s.code: s.city for s in STATIONS}
    with Session(engine) as session:
        svc = session.scalars(
            select(models.Service).where(models.Service.mode == "train", models.Service.seats_available > 0)
        ).first()
    body = _search(c, origin=svc.origin_code, dest=svc.dest_code, date=svc.depart_at.date().isoformat(), km=30).json()
    assert body["preferred_station_has_train_seats"] is True
    assert body["alternatives"] == []
    assert city[svc.origin_code] == body["origin"]["city"]


def test_destination_city_matches_any_of_its_stations(client):
    c, _ = client
    body = _search(c, km=30).json()
    assert {a["destination"]["city"] for a in body["options"] + body["alternatives"]} == {"Hyderabad"}
    assert {a["destination"]["code"] for a in body["alternatives"]} >= {"KCG", "SC"}


def test_cab_estimate_splits_the_fare(client):
    c, _ = client
    cab = _search(c).json()["cab"]
    assert 500 < cab["distance_km"] < 900  # Bengaluru -> Hyderabad by road
    shares = {s["people"]: s["per_person"] for s in cab["shares"]}
    assert set(shares) == {2, 3, 4}
    assert shares[2] > shares[3] > shares[4]
    assert abs(shares[4] * 4 - cab["total_fare"]) <= 20  # rounding only


def test_date_with_no_services_returns_empty_lists(client):
    c, _ = client
    body = _search(c, date="2030-01-01").json()
    assert body["options"] == [] and body["alternatives"] == []
    assert body["preferred_station_has_train_seats"] is False


def test_errors(client):
    c, _ = client
    assert _search(c, origin="NOPE").status_code == 404
    assert _search(c, dest="NOPE").status_code == 404
    assert _search(c, origin="SBC", dest="BNC").status_code == 400  # same city
    assert _search(c, km=31).status_code == 422
    assert c.get("/search", params={"origin": "SBC", "dest": "HYB"}).status_code == 422  # no date


def test_codes_are_case_insensitive(client):
    c, _ = client
    assert _search(c, origin="sbc", dest="hyb").status_code == 200


def test_stations_lists_one_primary_per_city(client):
    c, _ = client
    body = c.get("/stations").json()
    assert len(body) == len({s.city for s in STATIONS})
    assert next(s for s in body if s["city"] == "Bengaluru")["code"] == "SBC"


def test_database_failure_is_a_503_not_a_crash():
    class Broken:
        def scalars(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection refused"))

    def override():
        yield Broken()

    app.dependency_overrides[get_session] = override
    try:
        r = TestClient(app).get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO})
        assert r.status_code == 503
        assert "Database unavailable" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_day_boundaries(client):
    c, _ = client
    # Services on the previous day must not leak into the demo date.
    body = _search(c, km=30).json()
    for o in body["options"] + body["alternatives"]:
        assert dt.datetime.fromisoformat(o["depart_at"]).date() == DEMO_DATE
