"""Tests for Flagsmith integration: Experiments A & B, urgency, /config, /metrics, /experiments/summary, and P1 fault flags."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import config
import flags
import models
from cache import search_cache
from db import get_session
from main import app
from seed import seed
from seed_data import DEMO_DATE

DEMO = DEMO_DATE.isoformat()
EVENING = {"window_start": "18:00", "window_end": "22:00"}


def _user_flags(**overrides) -> flags.UserFlags:
    base = dict(
        tatkal_level=0,
        tatkal_config={"cache_ttl_s": 30, "poll_s_l0": 30, "poll_s_l1": 120},
        max_km=15,
        matching_strategy="exact",
        matching_config={"time_window_min": 120, "date_flex_days": 1, "max_matches": 8},
        interaction_mode="voice",
        urgent=False,
        days_until_travel=5,
        source="identity",
    )
    base.update(overrides)
    return flags.UserFlags(**base)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)
    search_cache.clear()
    flags.reset_for_tests()
    monkeypatch.setattr(config, "ALLOW_FLAG_OVERRIDE", False)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app), engine
    app.dependency_overrides.clear()
    search_cache.clear()
    flags.reset_for_tests()


def test_healthz_reports_flagsmith_defaults_when_unconfigured(env):
    c, _ = env
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["flagsmith"] == "defaults"


def test_urgency_window_respects_demo_now(monkeypatch):
    monkeypatch.setattr(config, "DEMO_NOW", "2026-11-25T10:00:00")
    urgent_27, days_27 = flags.urgency(dt.date(2026, 11, 27))
    urgent_30, days_30 = flags.urgency(dt.date(2026, 11, 30))
    assert urgent_27 is True and days_27 == 2
    assert urgent_30 is False and days_30 == 5


def test_experiment_b_cohorts_and_selection_summary(env, monkeypatch):
    c, engine = env
    cohorts = {"u-5": 5, "u-15": 15, "u-30": 30}
    monkeypatch.setattr(flags, "for_user", lambda uid, d=None, lang=None: _user_flags(max_km=cohorts.get(uid, 15)))

    counts = {}
    search_ids = {}
    first_alt = {}
    for uid, km in cohorts.items():
        r = c.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO}, headers={"X-User-Id": uid})
        assert r.status_code == 200
        body = r.json()
        assert body["max_station_distance_km"] == km
        counts[km] = len(body["alternatives"])
        search_ids[km] = body["search_id"]
        first_alt[km] = body["alternatives"][0]["id"]

    # Seeded demo route SBC -> HYB has 1 / 2 / 3 nearby alternatives at 5 / 15 / 30 km.
    assert counts == {5: 1, 15: 2, 30: 3}

    # Select one alternative in the 15 km cohort.
    sel = c.post(f"/search/{search_ids[15]}/select", json={"service_id": first_alt[15]})
    assert sel.status_code == 200
    assert sel.json()["extra_km"] > 0

    summary = c.get("/experiments/summary").json()
    by_km = {row["cohort_km"]: row for row in summary["station_distance"]}
    assert by_km[5]["selection_rate"] == 0.0
    assert by_km[5]["abandonment_rate"] == 1.0
    assert by_km[15]["selection_rate"] == 1.0
    assert by_km[15]["abandonment_rate"] == 0.0
    assert by_km[15]["avg_extra_km"] > 0

    with Session(engine) as s:
        assert len(s.scalars(select(models.SearchEvent)).all()) == 3
        assert len(s.scalars(select(models.AlternativeSelection)).all()) == 1


def test_experiment_a_ladder_levels_2_and_3_and_urgent_override(env, monkeypatch):
    c, engine = env

    # Level 2 skips multi-leg planning even when requested.
    monkeypatch.setattr(flags, "for_user", lambda uid, d=None, lang=None: _user_flags(tatkal_level=2))
    r2 = c.get(
        "/search",
        params={"origin": "SBC", "dest": "JP", "date": DEMO, "include_connections": True},
        headers={"X-User-Id": "u-normal"},
    )
    assert r2.status_code == 200
    assert r2.json()["connections_paused"] is True
    assert r2.json()["connections"] == []

    # Level 3 serves cached search on the second call and pauses /match without DB writes.
    def fake_flags(uid, d=None, lang=None):
        if uid == "u-urgent":
            return _user_flags(tatkal_level=0, urgent=True, days_until_travel=1)
        return _user_flags(tatkal_level=3, urgent=False, days_until_travel=5)

    monkeypatch.setattr(flags, "for_user", fake_flags)

    first = c.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO}, headers={"X-User-Id": "u-normal"})
    second = c.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO}, headers={"X-User-Id": "u-normal"})
    assert first.json()["served_from"] == "live"
    assert second.json()["served_from"] == "cache"

    paused = c.post(
        "/match",
        json={"user_id": "u-normal", "origin": "SBC", "dest": "HYB", "date": DEMO, **EVENING},
    )
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert paused.json()["match_id"] is None

    # Urgent user receives level-0 override -> normal matching works and writes a MatchEvent.
    urgent = c.post(
        "/match",
        json={"user_id": "u-urgent", "origin": "SBC", "dest": "HYB", "date": DEMO, **EVENING},
    )
    assert urgent.status_code == 200
    assert urgent.json()["paused"] is False
    assert urgent.json()["offered"] == 3

    with Session(engine) as s:
        events = s.scalars(select(models.MatchEvent)).all()
        assert len(events) == 1 and events[0].user_id == "u-urgent"


def test_config_and_prometheus_metrics_endpoints(env, monkeypatch):
    c, _ = env
    monkeypatch.setattr(flags, "for_user", lambda uid, d=None, lang=None: _user_flags(tatkal_level=1, max_km=30))
    cfg = c.get("/config", headers={"X-User-Id": "u-30"})
    assert cfg.status_code == 200
    assert cfg.json()["tatkal_level"] == 1
    assert cfg.json()["poll_s"] == 120
    assert cfg.json()["cohort_km"] == 30

    m = c.get("/metrics")
    assert m.status_code == 200
    text = m.text
    assert "gharchalo_tatkal_level" in text
    assert "gharchalo_http_requests_total" in text


def test_p1_route_fault_and_text_only_fallback(env, monkeypatch):
    c, _ = env

    # Route-specific fault breaks only Bengaluru <-> Hyderabad.
    monkeypatch.setattr(flags, "route_fault_on", lambda: True)
    bad = c.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO})
    bad_rev = c.get("/search", params={"origin": "HYB", "dest": "SBC", "date": DEMO})
    healthy = c.get("/search", params={"origin": "SBC", "dest": "MAA", "date": DEMO})
    assert bad.status_code == 500
    assert bad_rev.status_code == 500
    assert healthy.status_code == 200
    monkeypatch.setattr(flags, "route_fault_on", lambda: False)

    # Sarvam 429 simulation returns 503 without touching Sarvam.
    monkeypatch.setattr(flags, "sarvam_fault_mode", lambda: "429")
    r_429 = c.post("/journey/parse", json={"text": "Bangalore to Hyderabad"})
    assert r_429.status_code == 503
    monkeypatch.setattr(flags, "sarvam_fault_mode", lambda: "none")

    # interaction_mode=text_only blocks /journey/parse with 409 while typed /search still works.
    monkeypatch.setattr(flags, "interaction_mode", lambda: "text_only")
    r_blocked = c.post("/journey/parse", json={"text": "Bangalore to Hyderabad"})
    r_search = c.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO})
    assert r_blocked.status_code == 409
    assert r_search.status_code == 200
