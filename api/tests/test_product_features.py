"""Seats on nearby dates, waitlist confirmation chance, and spoken replies."""

import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import config
import db
import flags
import main
import sarvam
import waitlist
from main import app
from seed import seed

DEMO = "2026-11-27"


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    seed(engine)
    monkeypatch.setattr(config, "DEMO_NOW", "2026-11-25T10:00")  # "today" for days-until-travel

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[db.get_session] = override
    main._TTS_CACHE.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    main._TTS_CACHE.clear()


# --- waitlist confirmation chance ------------------------------------------------------------

def test_the_documented_examples():
    assert waitlist.confirm_chance(46, "SL", 2) == 0.59
    assert waitlist.confirm_chance(46, "3A", 2) == 0.40


@pytest.mark.parametrize("wl", [0, -3])
def test_no_waitlist_means_no_estimate(wl):
    assert waitlist.confirm_chance(wl, "SL", 2) is None


def test_longer_waitlists_are_less_likely_to_clear():
    chances = [waitlist.confirm_chance(wl, "SL", 2) for wl in (5, 20, 46, 80, 140)]
    assert chances == sorted(chances, reverse=True) and len(set(chances)) == len(chances)


def test_more_days_left_means_a_better_chance_up_to_ten_days():
    chances = [waitlist.confirm_chance(46, "SL", d) for d in (0, 2, 5, 10)]
    assert chances == sorted(chances) and len(set(chances)) == 4
    assert waitlist.confirm_chance(46, "SL", 30) == waitlist.confirm_chance(46, "SL", 10)  # capped
    assert waitlist.confirm_chance(46, "SL", -2) == waitlist.confirm_chance(46, "SL", 0)  # travel day passed
    assert waitlist.confirm_chance(46, "SL", None) == waitlist.confirm_chance(46, "SL", 0)


def test_estimates_stay_within_0_and_1():
    for wl in (1, 10, 500):
        for cls in ("SL", "3A", "2A"):
            assert 0 <= waitlist.confirm_chance(wl, cls, 3) <= 1


@pytest.mark.parametrize("chance,band", [(0.95, "high"), (0.7, "high"), (0.55, "medium"), (0.4, "medium"), (0.2, "low")])
def test_bands(chance, band):
    assert waitlist.band(chance) == band


def test_search_attaches_the_estimate_to_waitlisted_trains_only(client):
    body = client.get("/search", params={"origin": "SBC", "dest": "HYB", "date": DEMO}).json()
    for o in body["options"] + body["alternatives"]:
        if o["mode"] == "train" and o["status"] == "waitlist":
            assert o["confirm_chance"] == waitlist.confirm_chance(o["waitlist"], o["travel_class"], 2)  # 27 Nov is 2 days out
        else:
            assert o["confirm_chance"] is None  # seats available, or a bus
    assert any(o["confirm_chance"] for o in body["options"])  # the demo route has waitlisted trains


# --- seats on nearby dates -------------------------------------------------------------------

def test_date_strip_covers_the_days_around_the_search(client):
    body = client.get("/search/dates", params={"origin": "SBC", "dest": "HYB", "date": DEMO, "days": 3}).json()
    assert body["source"] == "simulated"
    assert [d["date"] for d in body["days"]] == [f"2026-11-{n}" for n in range(24, 31)]
    early = {d["date"]: d for d in body["days"]}
    assert early["2026-11-24"]["options"] == 0 and early["2026-11-25"]["options"] == 0  # before the seeded range


def test_date_strip_agrees_with_search_on_every_day(client):
    strip = client.get("/search/dates", params={"origin": "SBC", "dest": "HYB", "date": DEMO}).json()["days"]
    for day in strip:
        options = client.get("/search", params={"origin": "SBC", "dest": "HYB", "date": day["date"]}).json()["options"]
        free = [o for o in options if o["status"] == "available"]
        assert day["options"] == len(options), day["date"]
        assert day["with_seats"] == len(free), day["date"]
        assert day["trains_with_seats"] == sum(o["mode"] == "train" for o in free)
        assert day["buses_with_seats"] == sum(o["mode"] == "bus" for o in free)
        assert day["cheapest_with_seats"] == min((o["fare"] for o in free), default=None)


def test_demo_day_has_no_train_seats_from_the_main_station(client):
    strip = client.get("/search/dates", params={"origin": "SBC", "dest": "HYB", "date": DEMO}).json()["days"]
    demo = next(d for d in strip if d["date"] == DEMO)
    assert demo["trains_with_seats"] == 0 and demo["buses_with_seats"] > 0  # the scripted demo


def test_date_strip_errors(client):
    get = lambda **p: client.get("/search/dates", params={"origin": "SBC", "dest": "HYB", "date": DEMO, **p})  # noqa: E731
    assert get(origin="NOPE").status_code == 404
    assert get(dest="BNC").status_code == 400  # same city
    assert get(days=0).status_code == 422 and get(days=8).status_code == 422


# --- spoken replies --------------------------------------------------------------------------

class FakeSarvam:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    async def __call__(self, text, language_code):
        self.calls.append((text, language_code))
        if self.fail:
            raise sarvam.SarvamError("boom", self.fail)
        return b"RIFF-fake-audio"


def test_speak_returns_audio_in_the_right_language(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    r = client.post("/speak", json={"text": "बेंगलुरु से हैदराबाद", "language": "hi-IN"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == b"RIFF-fake-audio"
    client.post("/speak", json={"text": "hello", "language": "kn"})
    client.post("/speak", json={"text": "bonjour", "language": "fr"})  # unsupported: read in Indian English
    assert [c[1] for c in fake.calls] == ["hi-IN", "kn-IN", "en-IN"]


def test_the_same_reply_is_synthesised_once(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    for _ in range(3):
        assert client.post("/speak", json={"text": "same words", "language": "en"}).status_code == 200
    assert len(fake.calls) == 1


def test_load_test_traffic_never_reaches_sarvam(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    monkeypatch.setattr(config, "LOAD_TEST_STUB_DELAY_SECONDS", 0)
    r = client.post("/speak", json={"text": "storm", "language": "hi"}, headers={"X-Load-Test": "1"})
    assert r.status_code == 200 and r.content.startswith(b"RIFF") and fake.calls == []


def test_spoken_replies_pause_at_tatkal_level_2(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    monkeypatch.setattr(flags, "for_user", lambda *a, **k: SimpleNamespace(tatkal_level=2))
    r = client.post("/speak", json={"text": "hi", "language": "en"})
    assert r.status_code == 409 and fake.calls == []


def test_text_only_mode_switches_spoken_replies_off(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    monkeypatch.setattr(flags, "interaction_mode", lambda: "text_only")
    assert client.post("/speak", json={"text": "hi", "language": "en"}).status_code == 409
    assert fake.calls == []


@pytest.mark.parametrize("upstream,expected", [(429, 503), (500, 502), (None, 502)])
def test_sarvam_failures_map_like_voice(client, monkeypatch, upstream, expected):
    monkeypatch.setattr(sarvam, "speak", FakeSarvam(fail=upstream or 0))
    if upstream is None:
        async def unreachable(text, language_code):
            raise sarvam.SarvamError("unreachable")
        monkeypatch.setattr(sarvam, "speak", unreachable)
    assert client.post("/speak", json={"text": "hi", "language": "en"}).status_code == expected


def test_long_text_is_cut_to_the_limit_and_blank_text_rejected(client, monkeypatch):
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    monkeypatch.setattr(config, "TTS_MAX_CHARS", 20)
    client.post("/speak", json={"text": "word " * 50, "language": "en"})
    assert len(fake.calls[0][0]) == 20
    assert client.post("/speak", json={"text": "   ", "language": "en"}).status_code == 400
    assert client.post("/speak", json={"text": "", "language": "en"}).status_code == 422


def test_urgent_travellers_keep_spoken_replies_at_level_2(client, monkeypatch):
    """Same fairness rule as search: the journey date decides whether the visitor is urgent."""
    fake = FakeSarvam()
    monkeypatch.setattr(sarvam, "speak", fake)
    seen = []

    def for_user(user_id, journey_date=None, lang=None):
        seen.append(journey_date)
        urgent = journey_date is not None and (journey_date - dt.date(2026, 11, 25)).days <= 2
        return SimpleNamespace(tatkal_level=0 if urgent else 2)

    monkeypatch.setattr(flags, "for_user", for_user)
    assert client.post("/speak", json={"text": "hi", "language": "en", "date": "2026-11-27"}).status_code == 200
    assert client.post("/speak", json={"text": "hi", "language": "en", "date": "2026-11-30"}).status_code == 409
    assert seen == [dt.date(2026, 11, 27), dt.date(2026, 11, 30)]


# --- release toggles (Flagsmith: tatkal_countdown) --------------------------------------------

def test_release_toggles_are_off_by_default(client):
    assert client.get("/config", params={"date": DEMO}, headers={"X-User-Id": "u1"}).json()["features"] == {"tatkal_countdown": False}


def test_a_release_toggle_follows_the_flags_on_off_state():
    on = flags._resolve(lambda name: (name == "tatkal_countdown", None), False, 2, "identity")
    off = flags._resolve(lambda name: (False, None), False, 2, "identity")
    assert on.features == {"tatkal_countdown": True} and off.features == {"tatkal_countdown": False}
