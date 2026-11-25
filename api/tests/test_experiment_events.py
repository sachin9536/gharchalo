"""Exposures and conversions sent to Flagsmith's Experiments tab, checked with a fake client."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import config
import db
import flags
import models
from main import app
from seed import seed


class FakeClient:
    """Stands in for the Flagsmith SDK client: records what the app sends it."""

    def __init__(self, fail=False):
        self.fail, self.exposures, self.events = fail, [], []

    def get_identity_flags(self, *a, **k):
        raise RuntimeError("no real evaluation here: the app falls back to its safe defaults")

    def get_experiment_flag(self, feature, identifier, traits=None):
        if self.fail:
            raise RuntimeError("boom")
        self.exposures.append((feature, identifier))

    def track_event(self, event, identifier=None, value=None, traits=None, metadata=None):
        if self.fail:
            raise RuntimeError("boom")
        self.events.append((event, identifier, metadata))


@pytest.fixture()
def world(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)
    fake = FakeClient()
    monkeypatch.setattr(flags, "client", lambda: fake)
    monkeypatch.setattr(config, "ALLOW_FLAG_OVERRIDE", True)

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[db.get_session] = override
    yield TestClient(app), fake, engine
    app.dependency_overrides.clear()


SEARCH = {"origin": "SBC", "dest": "HYB", "date": "2026-11-27"}
MATCH = {**SEARCH, "window_start": "18:00", "window_end": "22:00"}


def _search(c, user, **params):
    return c.get("/search", params={**SEARCH, **params}, headers={"X-User-Id": user})


def _match(c, user, **extra):
    return c.post("/match", json={**MATCH, "user_id": user, **extra}, headers={"X-User-Id": user})


# --- exposure: only when the flag really shaped what the visitor saw ------------------------

def test_search_exposes_the_distance_cohort_when_their_station_is_full(world):
    c, fake, _ = world
    assert _search(c, "u1").json()["alternatives"]  # SBC has no seats on the demo day
    assert fake.exposures == [("max_station_distance_km", "u1")]


def test_no_exposure_when_the_visitors_own_station_has_seats(world):
    c, fake, engine = world
    with Session(engine) as s:
        svc = s.scalars(select(models.Service).where(models.Service.mode == "train", models.Service.seats_available > 0)).first()
    r = c.get("/search", params={"origin": svc.origin_code, "dest": svc.dest_code, "date": svc.depart_at.date().isoformat()},
              headers={"X-User-Id": "u1"})
    assert r.json()["preferred_station_has_train_seats"] is True
    assert fake.exposures == []  # the cohort distance played no part in what they saw


def test_no_exposure_for_a_manual_override_or_load_test_traffic(world):
    c, fake, _ = world
    _search(c, "u1", max_station_distance_km=5)  # a demo override, not the flag
    c.get("/search", params=SEARCH, headers={"X-User-Id": "u2", "X-Load-Test": "1"})
    assert fake.exposures == []


def test_no_exposure_without_an_identity(world):
    c, fake, _ = world
    c.get("/search", params=SEARCH)  # anonymous: nobody to attribute it to
    assert fake.exposures == []


def test_match_exposes_the_strategy_even_when_nobody_was_found(world):
    c, fake, _ = world
    _match(c, "u1")
    _match(c, "u2", date="2030-01-01")  # nothing to offer, but the strategy still applied to them
    assert fake.exposures == [("matching_strategy", "u1"), ("matching_strategy", "u2")]


def test_no_match_exposure_for_a_manual_strategy_override(world):
    c, fake, _ = world
    _match(c, "u1", strategy="time_window")
    assert fake.exposures == []


# --- conversion: what the experiments measure -----------------------------------------------

def test_choosing_a_nearby_station_is_an_alternative_selected_event(world):
    c, fake, _ = world
    body = _search(c, "u1").json()
    pick = body["alternatives"][0]["id"]
    assert c.post(f"/search/{body['search_id']}/select", json={"service_id": pick}).status_code == 200
    assert fake.events == [("alternative_selected", "u1", {"simulated": False})]


def test_accepting_a_group_is_a_match_accepted_event(world):
    c, fake, _ = world
    match_id = _match(c, "u1").json()["match_id"]
    assert c.post(f"/match/{match_id}/accept").status_code == 200
    assert fake.events == [("match_accepted", "u1", {"simulated": False})]


def test_synthetic_visitors_are_tagged_simulated(world):
    c, fake, _ = world
    match_id = _match(c, "sim-7").json()["match_id"]
    c.post(f"/match/{match_id}/accept")
    assert fake.events == [("match_accepted", "sim-7", {"simulated": True})]


def test_a_failed_acceptance_sends_no_conversion(world):
    c, fake, _ = world
    empty = _match(c, "u1", date="2030-01-01").json()["match_id"]
    assert c.post(f"/match/{empty}/accept").status_code == 409
    assert c.post("/match/99999/accept").status_code == 404
    assert fake.events == []


# --- analytics must never break the app -----------------------------------------------------

def test_a_failing_flagsmith_client_never_breaks_a_request(world):
    c, fake, _ = world
    fake.fail = True
    body = _search(c, "u1")
    assert body.status_code == 200
    pick = body.json()["alternatives"][0]["id"]
    assert c.post(f"/search/{body.json()['search_id']}/select", json={"service_id": pick}).status_code == 200
    match = _match(c, "u1")
    assert match.status_code == 200
    assert c.post(f"/match/{match.json()['match_id']}/accept").status_code == 200


def test_without_flagsmith_nothing_is_sent_and_everything_works(monkeypatch):
    import experiment_events

    monkeypatch.setattr(flags, "client", lambda: None)
    experiment_events.expose("max_station_distance_km", "u1")  # no client: silently nothing
    experiment_events.convert("match_accepted", "u1")


# --- where the SDK sends events ---------------------------------------------------------------

@pytest.mark.parametrize(
    "api_url,explicit,expected",
    [
        ("http://localhost:8090/api/v1/", "", "http://localhost:8090/api/"),  # the SDK adds "v1/events" itself
        ("http://localhost:8090/api/v1", "", "http://localhost:8090/api/"),
        ("https://flags.example.com/api/v1/", "", "https://flags.example.com/api/"),
        ("http://localhost:8090/api/v1/", "http://events.internal:9000", "http://events.internal:9000/"),
        ("", "", ""),  # hosted Flagsmith: leave it to the SDK's default endpoint
    ],
)
def test_events_base_url(monkeypatch, api_url, explicit, expected):
    monkeypatch.setattr(config, "FLAGSMITH_API_URL", api_url)
    monkeypatch.setattr(config, "FLAGSMITH_EVENTS_URL", explicit)
    assert flags.events_base_url() == expected


def test_an_unreachable_flagsmith_does_not_slow_requests_down(monkeypatch):
    """Regression: a dead Flagsmith once added ~1.2 s of retries to every request."""
    import datetime as dt
    import logging
    import time

    monkeypatch.setattr(config, "FLAGSMITH_SERVER_KEY", "ser.unreachable")
    monkeypatch.setattr(config, "FLAGSMITH_API_URL", "http://127.0.0.1:9/api/v1/")  # nothing listens on port 9
    monkeypatch.setattr(config, "FLAGSMITH_OFFLINE_FILE", "")
    monkeypatch.setattr(config, "FLAGSMITH_EVENTS", False)
    monkeypatch.setattr(config, "FLAGSMITH_ANALYTICS", False)
    flags.reset_for_tests()
    logging.disable(logging.CRITICAL)
    try:
        flags.for_user("warm-up", dt.date(2026, 11, 30))
        started = time.perf_counter()
        for i in range(20):
            f = flags.for_user(f"u{i}", dt.date(2026, 11, 30))
        per_call_ms = (time.perf_counter() - started) * 1000 / 20
    finally:
        logging.disable(logging.NOTSET)
        flags.shutdown()
    assert per_call_ms < 100, f"{per_call_ms:.0f} ms per flag lookup with Flagsmith down"
    assert f.max_km == 15  # the safe default


def test_the_planted_memory_fault_is_off_by_default_and_grows_only_when_on(world, monkeypatch):
    import main

    c, _, _ = world
    main._search_log.clear()
    _search(c, "u1")
    assert main._search_log == []  # off by default: nothing retained
    monkeypatch.setattr(config, "FAULT_UNBOUNDED_SEARCH_LOG", True)
    for _ in range(3):
        _search(c, "u1")
    assert len(main._search_log) == 3  # on: every search is kept, and nothing ever trims it
    main._search_log.clear()
