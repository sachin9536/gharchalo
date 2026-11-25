"""The exact-vs-flexible matching experiment: benchmark, stored costs and schema top-up.

The expected numbers below are properties of the *seeded* traveller pool (seed.py scripts a
handful of near-misses around Bengaluru -> Hyderabad on 27 Nov). If the seed changes, these
change on purpose and need re-deriving, not loosening.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import benchmark
import db
import models
from main import app
from seed import seed

BODY = {"origin": "SBC", "dest": "HYB", "date": "2026-11-27", "window_start": "18:00", "window_end": "22:00"}


@pytest.fixture()
def world():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[db.get_session] = override
    yield TestClient(app), engine
    app.dependency_overrides.clear()


# --- the benchmark --------------------------------------------------------------------------

EXPECTED = {  # request -> (found by exact, found by flexible)
    "Same station, same evening": (1, 6),
    "Same station, a day later": (0, 5),  # u001 u002 u003 u007 (27 Nov) + u006 (28 Nov); nobody at SBC on the 28th
    "Same station, a day earlier": (1, 5),
    "Same station, early morning": (1, 1),
    "Same station, late night": (0, 6),
    "Pickup 4 km away (Cantonment)": (1, 6),
    "Pickup 5 km away (Yesvantpur)": (1, 6),
    "Pickup 11 km away (Baiyappanahalli)": (0, 6),
    "Pickup 28 km away (Bidadi)": (0, 0),
}


def _run(engine, config=None):
    with Session(engine) as session:
        return benchmark.matching_benchmark(session, config)


def test_benchmark_numbers_on_the_seeded_pool(world):
    _, engine = world
    result = _run(engine)
    got = {r["name"]: (r["exact"]["found"], r["flexible"]["found"]) for r in result["scenarios"]}
    assert got == EXPECTED
    s = result["summary"]
    assert (s["found_by_exact"], s["found_by_flexible"]) == (5, 41)
    assert (s["rescued"], s["still_empty"]) == (3, 1)  # exact found nobody in 4; flexible fixed 3 of them
    assert s["extra_matches"] == 36 == s["found_by_flexible"] - s["found_by_exact"]  # nothing exact found is lost
    assert result["source"] == "simulated"


def test_what_flexibility_costs_is_measured(world):
    _, engine = world
    s = _run(engine)["summary"]
    assert 5 < s["extra_avg_pickup_km"] < 6.5  # the extra matches are a few km away on average
    assert 0.3 < s["extra_avg_day_shift"] < 0.7
    assert s["extra_avg_time_gap_min"] > 0
    first = _run(engine)["scenarios"][0]
    assert first["flexible"]["avg_pickup_km"] == 4.3 and first["flexible"]["avg_day_shift"] == 0.33
    # a bigger group splits the same cab: 2 people -> 4 people
    assert (first["exact"]["group_size"], first["flexible"]["group_size"]) == (2, 4)
    assert first["exact"]["fare_each"] == 2 * first["flexible"]["fare_each"]


def test_the_benchmark_follows_the_tuning_numbers(world):
    _, engine = world
    bidadi = lambda cfg: next(r for r in _run(engine, cfg)["scenarios"] if "Bidadi" in r["name"])["flexible"]["found"]  # noqa: E731
    assert bidadi(None) == 0  # 28 km is beyond the default 15 km reach
    assert bidadi({"flex_pickup_km": 30}) > 0  # widen the reach in Flagsmith and it is found
    wide = _run(engine)["summary"]["found_by_flexible"]
    assert _run(engine, {"date_flex_days": 0})["summary"]["found_by_flexible"] < wide
    # With no pickup reach at all, flexible can still find people at your own station on other days/times,
    # but never anyone at a different one.
    assert _run(engine, {"flex_pickup_km": 0})["summary"]["extra_avg_pickup_km"] == 0.0


def test_the_benchmark_writes_nothing(world):
    _, engine = world
    with Session(engine) as s:
        before = len(s.scalars(select(models.MatchEvent)).all())
    _run(engine)
    with Session(engine) as s:
        assert len(s.scalars(select(models.MatchEvent)).all()) == before


def test_benchmark_endpoint(world):
    client, _ = world
    r = client.get("/experiments/matching-benchmark")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["extra_matches"] == 36
    assert body["config"] == {"max_matches": 8, "exact_pickup_km": 0, "flex_pickup_km": 15, "date_flex_days": 1, "time_window_min": 120}


# --- what each offer costs, as recorded for the experiment ---------------------------------

def _offer(client, user, strategy):
    return client.post("/match", json={**BODY, "user_id": user, "strategy": strategy}, headers={"X-User-Id": user}).json()


def test_the_summary_reports_what_each_strategy_costs(world):
    client, _ = world
    _offer(client, "real-1", "exact")
    _offer(client, "real-2", "time_window")
    rows = {m["strategy"]: m for m in client.get("/experiments/summary", params={"source": "live"}).json()["matching"]}
    assert (rows["exact"]["avg_matches_offered"], rows["exact"]["avg_pickup_km"], rows["exact"]["avg_group_size"]) == (1.0, 0.0, 2.0)
    flex = rows["time_window"]
    assert (flex["avg_matches_offered"], flex["avg_group_size"]) == (6.0, 4.0)
    assert (flex["avg_pickup_km"], flex["avg_day_shift"], flex["avg_time_gap_min"]) == (4.3, 0.33, 10.0)


def test_offers_made_under_the_old_rules_are_excluded_not_blended(world):
    client, engine = world
    _offer(client, "real-1", "exact")
    with Session(engine) as s:  # an offer from before pickup distance existed: group_size is NULL
        s.add(models.MatchEvent(user_id="old-1", strategy="exact", offered=3, accepted=True))
        s.commit()
    body = client.get("/experiments/summary", params={"source": "live"}).json()
    exact = next(m for m in body["matching"] if m["strategy"] == "exact")
    assert exact["offers_with_matches"] == 1 and exact["accepted"] == 0  # the old accepted offer is not counted
    assert body["matching_legacy_offers_excluded"] == 1


# --- topping up an existing database without a reseed --------------------------------------

def test_ensure_columns_adds_missing_columns_and_keeps_the_data():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE match_events (id INTEGER PRIMARY KEY, user_id VARCHAR(64), strategy VARCHAR(24), "
                          "offered INTEGER, accepted BOOLEAN, created_at DATETIME)"))
        conn.execute(text("INSERT INTO match_events (user_id, strategy, offered, accepted) VALUES ('keep-me', 'exact', 3, 1)"))
    added = db.ensure_columns(engine)
    assert sorted(added) == sorted(f"match_events.{c}" for c in ("avg_pickup_km", "avg_day_shift", "avg_time_gap_min", "group_size"))
    assert {c["name"] for c in inspect(engine).get_columns("match_events")} >= {"avg_pickup_km", "group_size"}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT user_id, offered, group_size FROM match_events")).one() == ("keep-me", 3, None)
    assert db.ensure_columns(engine) == []  # a second run changes nothing


def test_ensure_columns_ignores_a_database_without_the_table():
    assert db.ensure_columns(create_engine("sqlite://", poolclass=StaticPool)) == []
