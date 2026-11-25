"""The experiments read-out must never blend real visitors with simulated (sim-...) ones."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db import get_session
from main import app
from seed import seed

BODY = {"origin": "SBC", "dest": "HYB", "date": "2026-11-27", "window_start": "18:00", "window_end": "22:00"}


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _offer(c, user, accept=False):
    r = c.post("/match", json={**BODY, "user_id": user}, headers={"X-User-Id": user}).json()
    if accept:
        assert c.post(f"/match/{r['match_id']}/accept", headers={"X-User-Id": user}).status_code == 200
    return r


def _search(c, user):
    return c.get("/search", params={k: BODY[k] for k in ("origin", "dest", "date")}, headers={"X-User-Id": user}).json()


def _rows(c, source):
    return c.get("/experiments/summary", params={"source": source}).json()


def test_real_and_simulated_visitors_are_counted_separately(client):
    for i in range(3):
        _offer(client, f"real-{i}", accept=(i == 0))
    for i in range(5):
        _offer(client, f"sim-x-{i}", accept=(i < 2))

    live, simulated, everyone = _rows(client, "live"), _rows(client, "simulated"), _rows(client, "all")

    assert live["visitors"] == "live" and simulated["visitors"] == "simulated" and everyone["visitors"] == "all"
    offers = lambda body: sum(m["offers_with_matches"] for m in body["matching"])  # noqa: E731
    accepts = lambda body: sum(m["accepted"] for m in body["matching"])  # noqa: E731
    assert (offers(live), accepts(live)) == (3, 1)
    assert (offers(simulated), accepts(simulated)) == (5, 2)
    assert (offers(everyone), accepts(everyone)) == (8, 3)  # the blend is exactly the sum, nothing lost or doubled


def test_population_counts_are_always_split_regardless_of_the_filter(client):
    _offer(client, "real-1")
    _offer(client, "sim-1")
    _offer(client, "sim-2")
    _search(client, "real-1")
    _search(client, "sim-1")
    for source in ("live", "simulated", "all"):
        pop = _rows(client, source)["population"]
        assert pop["match_events"] == {"live": 1, "simulated": 2}
        assert pop["search_events"] == {"live": 1, "simulated": 1}


def test_station_distance_is_filtered_the_same_way(client):
    _search(client, "real-1")
    for i in range(4):
        _search(client, f"sim-{i}")
    count = lambda body: sum(c["searches"] for c in body["station_distance"])  # noqa: E731
    assert count(_rows(client, "live")) == 1
    assert count(_rows(client, "simulated")) == 4
    assert count(_rows(client, "all")) == 5


def test_a_name_merely_containing_sim_is_not_simulated(client):
    # Only the sim- *prefix* marks synthetic traffic; "simon" and "xsim-1" are real people.
    _offer(client, "simon")
    _offer(client, "xsim-1")
    assert sum(m["offers_with_matches"] for m in _rows(client, "live")["matching"]) == 2
    assert _rows(client, "simulated")["matching"] == []


def test_default_covers_everyone_and_bad_values_are_rejected(client):
    _offer(client, "real-1")
    _offer(client, "sim-1")
    default = client.get("/experiments/summary").json()
    assert default["visitors"] == "all"
    assert sum(m["offers_with_matches"] for m in default["matching"]) == 2
    assert client.get("/experiments/summary", params={"source": "everything"}).status_code == 422


def test_the_railway_data_is_always_labelled_simulated(client):
    assert _rows(client, "live")["source"] == "simulated"
