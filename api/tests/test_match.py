import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import matching
import models
from db import get_session
from main import app
from seed import seed
from seed_data import DEMO_DATE

DEMO = DEMO_DATE.isoformat()
EVENING = {"window_start": "18:00", "window_end": "22:00"}


@pytest.fixture()
def env():
    """A fresh seeded database per test: matching writes rows."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app), engine
    app.dependency_overrides.clear()


def _match(c, *, user="browser-1", origin="SBC", dest="HYB", date=DEMO, strategy="exact", **window):
    body = {"user_id": user, "origin": origin, "dest": dest, "date": date, "strategy": strategy, **(window or EVENING)}
    return c.post("/match", json=body)


def test_demo_exact_matches_only_the_same_station(env):
    c, _ = env
    body = _match(c).json()
    assert body["offered"] == 1
    m = body["matches"][0]
    assert (m["traveller_id"], m["pickup"]["code"], m["pickup_km"], m["day_shift"], m["time_gap_min"], m["shift"]) == (
        1, "SBC", 0.0, 0, 0, "exact",
    )
    assert body["suggested_group_size"] == 2  # you plus one


def test_flexible_finds_more_and_reports_what_flexibility_costs(env):
    c, _ = env
    exact = _match(c, strategy="exact").json()
    flexible = _match(c, strategy="time_window").json()
    assert (exact["offered"], flexible["offered"]) == (1, 6)
    rows = [(m["pickup"]["code"], m["pickup_km"], m["day_shift"], m["time_gap_min"], m["shift"]) for m in flexible["matches"]]
    assert rows == [
        ("SBC", 0.0, 0, 0, "exact"),  # the one exact match is still listed first
        ("BNC", 3.7, 0, 0, "flexible"),  # then same-day matches, nearest pickup first
        ("YPR", 5.3, 0, 0, "flexible"),
        ("SMVB", 11.3, 0, 60, "flexible"),  # an hour after your window ends
        ("SBC", 0.0, -1, 0, "flexible"),  # then a day earlier / later
        ("YPR", 5.3, 1, 0, "flexible"),
    ]
    assert flexible["matches"][0]["traveller_id"] == exact["matches"][0]["traveller_id"]
    assert flexible["suggested_group_size"] == 4


def test_own_user_is_never_matched(env):
    c, _ = env
    # u001 (traveller id 1) is a seeded match; asking as u001 must not return themselves.
    body = _match(c, user="u001", strategy="time_window").json()
    assert body["offered"] == 5
    assert 1 not in {m["traveller_id"] for m in body["matches"]}
    assert _match(c, user="u001", strategy="exact").json()["offered"] == 0  # their own row was the only exact match


def test_morning_window_finds_only_morning_travellers(env):
    c, _ = env
    body = _match(c, window_start="05:00", window_end="12:00").json()
    assert body["offered"] == 1
    assert body["matches"][0]["window_start"].startswith("06:00")


def test_window_edges_are_inclusive(env):
    c, _ = env
    # u001's window at SBC ends at 21:00. A window starting exactly then still meets it; a minute later does not.
    touching = _match(c, window_start="21:00", window_end="23:00").json()
    assert [m["traveller_id"] for m in touching["matches"]] == [1]
    assert _match(c, window_start="21:01", window_end="23:00").json()["offered"] == 0


def test_works_on_other_routes(env):
    c, engine = env
    with Session(engine) as s:
        t = s.scalars(select(models.Traveller).where(models.Traveller.id == 100)).one()
    r = _match(
        c, user="someone-else", origin=t.origin_code, dest=t.dest_code, date=t.travel_date.isoformat(),
        window_start=t.window_start.strftime("%H:%M"), window_end=t.window_end.strftime("%H:%M"),
    )
    assert r.status_code == 200
    assert t.id in {m["traveller_id"] for m in r.json()["matches"]}


def test_no_matches_is_a_valid_empty_offer(env):
    c, _ = env
    body = _match(c, date="2030-01-01").json()
    assert body["offered"] == 0 and body["matches"] == []
    assert body["suggested_group_size"] == 1


def test_every_offer_is_logged_with_its_strategy_and_cost(env):
    c, engine = env
    a = _match(c, strategy="exact").json()
    b = _match(c, strategy="time_window", user="browser-2").json()
    empty = _match(c, strategy="exact", date="2030-01-01", user="browser-3").json()
    with Session(engine) as s:
        rows = {e.id: e for e in s.scalars(select(models.MatchEvent))}
    ea, eb, ee = rows[a["match_id"]], rows[b["match_id"]], rows[empty["match_id"]]
    assert (ea.strategy, ea.offered, ea.group_size, ea.avg_pickup_km, ea.avg_day_shift, ea.avg_time_gap_min) == (
        "exact", 1, 2, 0.0, 0.0, 0.0,
    )
    # flexible: pickups 0, 3.7, 5.3, 11.3, 0, 5.3 km; days 0,0,0,0,1,1; gaps 0,0,0,60,0,0
    assert (eb.strategy, eb.offered, eb.group_size, eb.user_id) == ("time_window", 6, 4, "browser-2")
    assert (eb.avg_pickup_km, eb.avg_day_shift, eb.avg_time_gap_min) == (4.27, 0.33, 10.0)
    assert (ee.offered, ee.group_size, ee.avg_pickup_km) == (0, 1, None)  # nothing offered: no cost to average
    assert not any(e.accepted for e in rows.values())


def test_accept_marks_the_offer_and_is_idempotent(env):
    c, engine = env
    match_id = _match(c).json()["match_id"]
    for _ in range(2):
        r = c.post(f"/match/{match_id}/accept")
        assert r.status_code == 200 and r.json() == {"match_id": match_id, "accepted": True}
    with Session(engine) as s:
        assert s.get(models.MatchEvent, match_id).accepted is True


def test_accept_errors(env):
    c, _ = env
    assert c.post("/match/9999/accept").status_code == 404
    empty = _match(c, date="2030-01-01").json()["match_id"]
    assert c.post(f"/match/{empty}/accept").status_code == 409  # nothing to accept


def test_request_validation(env):
    c, _ = env
    assert _match(c, window_start="22:00", window_end="18:00").status_code == 422
    assert _match(c, strategy="magic").status_code == 422
    assert _match(c, user="").status_code == 422
    assert _match(c, user="x" * 65).status_code == 422
    assert _match(c, origin="NOPE").status_code == 404
    assert _match(c, dest="NOPE").status_code == 404
    assert _match(c, origin="SBC", dest="BNC").status_code == 400  # same city
    assert c.post("/match", json={"user_id": "a"}).status_code == 422


def test_long_browser_uuid_is_accepted(env):
    c, _ = env
    assert _match(c, user="3f2b8c1e-9d4a-4e7b-a1c2-5d6e7f8a9b0c").status_code == 200


def test_database_failure_is_a_503():
    class Broken:
        def scalars(self, *a, **k):
            raise OperationalError("select", {}, Exception("connection refused"))

    def override():
        yield Broken()

    app.dependency_overrides[get_session] = override
    try:
        r = _match(TestClient(app))
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


# --- the relaxations are numbers you can tune (Flagsmith: matching_config) ----------------------

D = dt.date(2026, 11, 27)
EVENING_T = (dt.time(18), dt.time(22))


def _count(engine, strategy, **config):
    with Session(engine) as s:
        found = matching.candidates(
            s, user_id="asker", origin_code="SBC", dest_code="HYB", date=D,
            window_start=EVENING_T[0], window_end=EVENING_T[1], strategy=strategy, config=config,
        )
        return sorted(c.traveller.id for c in found)


@pytest.mark.parametrize(
    "strategy,config,expected_ids",
    [
        ("exact", {}, [1]),
        ("exact", {"exact_pickup_km": 4}, [1, 3]),  # + Cantonment (3.7 km)
        ("exact", {"exact_pickup_km": 6}, [1, 2, 3]),  # + Yesvantpur (5.3 km)
        ("time_window", {}, [1, 2, 3, 5, 6, 7]),
        ("time_window", {"flex_pickup_km": 4}, [1, 3, 5]),  # only SBC and Cantonment reach
        ("time_window", {"flex_pickup_km": 30}, [1, 2, 3, 5, 6, 7]),  # no seeded traveller is farther than 11 km
        ("time_window", {"date_flex_days": 0}, [1, 2, 3, 7]),  # no day either side
        ("time_window", {"time_window_min": 0}, [1, 2, 3, 5, 6]),  # u007 is an hour away
        ("time_window", {"max_matches": 2}, [1, 3]),  # the best two: the exact one, then the nearest
    ],
)
def test_relaxations_are_tunable_numbers(env, strategy, config, expected_ids):
    _, engine = env
    assert _count(engine, strategy, **config) == expected_ids


def test_finding_candidates_writes_nothing(env):
    _, engine = env
    with Session(engine) as s:
        before = len(s.scalars(select(models.MatchEvent)).all())
    _count(engine, "time_window")
    with Session(engine) as s:
        assert len(s.scalars(select(models.MatchEvent)).all()) == before
