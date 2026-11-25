import datetime as dt

import pytest
from fastapi.testclient import TestClient

import config
import sarvam
import stations
from journey import build_journey
from main import app

client = TestClient(app)
TODAY = dt.date(2026, 11, 25)


# --- stations -------------------------------------------------------------

@pytest.mark.parametrize(
    "spoken,code",
    [
        ("Bangalore", "SBC"),
        ("bengaluru", "SBC"),
        ("BLR", "SBC"),
        ("बेंगलुरु", "SBC"),
        ("Hyd", "HYB"),
        ("hydrabad", "HYB"),  # STT typo, resolved by close match
        ("हैदराबाद", "HYB"),
        ("Kota", "KOTA"),
        ("  New   Delhi! ", "NDLS"),
    ],
)
def test_resolve_known_aliases(spoken, code):
    assert stations.resolve(spoken).code == code


@pytest.mark.parametrize("spoken", ["Atlantis", "", None, "xyz"])
def test_resolve_unknown_returns_none(spoken):
    assert stations.resolve(spoken) is None


# --- journey validation ---------------------------------------------------

def test_build_journey_happy_path():
    j = build_journey(
        {
            "origin_text": "Bangalore",
            "destination_text": "Hyderabad",
            "date": "2026-11-27",
            "fallback_mode": "shared_cab",
            "language": "HI",
        },
        TODAY,
    )
    assert j.origin.code == "SBC" and j.destination.code == "HYB"
    assert j.date == dt.date(2026, 11, 27)
    assert j.fallback_mode == "shared_cab"
    assert j.language == "hi"
    assert j.missing == [] and j.warnings == []


def test_build_journey_never_trusts_model_codes():
    j = build_journey({"origin_text": "Bangalore", "origin_code": "XXX", "destination_text": "Kota", "date": "2026-11-27"}, TODAY)
    assert j.origin.code == "SBC"


def test_build_journey_reports_missing_and_unknown():
    j = build_journey({"origin_text": "Atlantis", "destination_text": None, "date": "not-a-date"}, TODAY)
    assert set(j.missing) == {"origin", "destination", "date"}
    assert any("Atlantis" in w for w in j.warnings)


def test_build_journey_bad_fallback_defaults_to_train():
    j = build_journey({"origin_text": "Pune", "destination_text": "Delhi", "date": "2026-12-01", "fallback_mode": "teleport"}, TODAY)
    assert j.fallback_mode == "train"


def test_build_journey_warns_on_past_date_and_same_city():
    j = build_journey({"origin_text": "Pune", "destination_text": "poona", "date": "2026-11-01"}, TODAY)
    assert any("past" in w for w in j.warnings)
    assert any("same city" in w for w in j.warnings)


# --- extraction JSON cleanup ---------------------------------------------

def test_strip_to_json_handles_think_blocks_and_fences():
    raw = '<think>hmm {not json}</think>\n```json\n{"origin_text": "Pune", "date": null}\n```'
    assert sarvam._strip_to_json(raw) == {"origin_text": "Pune", "date": None}


def test_strip_to_json_rejects_garbage():
    with pytest.raises(sarvam.SarvamError):
        sarvam._strip_to_json("sorry, I cannot help")


# --- endpoints (Sarvam mocked) -------------------------------------------

def _mock_sarvam(monkeypatch, *, text="Bangalore se Hyderabad 27 November", extraction=None):
    async def fake_transcribe(audio, filename="audio.wav", content_type="audio/wav"):
        return sarvam.Transcript(text=text, language_code="hi-IN")

    async def fake_extract(text, today=None):
        return extraction or {
            "origin_text": "Bangalore",
            "destination_text": "Hyderabad",
            "date": "2026-11-27",
            "fallback_mode": "shared_cab",
            "language": "hi",
        }

    monkeypatch.setattr(sarvam, "transcribe", fake_transcribe)
    monkeypatch.setattr(sarvam, "extract_journey", fake_extract)


def test_voice_happy_path(monkeypatch):
    _mock_sarvam(monkeypatch)
    r = client.post("/voice", files={"file": ("a.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "sarvam"
    assert body["transcript"] == "Bangalore se Hyderabad 27 November"
    assert body["journey"]["origin"]["code"] == "SBC"
    assert body["journey"]["destination"]["code"] == "HYB"
    assert body["journey"]["fallback_mode"] == "shared_cab"


def test_voice_empty_upload_is_400(monkeypatch):
    _mock_sarvam(monkeypatch)
    r = client.post("/voice", files={"file": ("a.wav", b"", "audio/wav")})
    assert r.status_code == 400


def test_voice_no_speech_is_422(monkeypatch):
    _mock_sarvam(monkeypatch, text="")
    r = client.post("/voice", files={"file": ("a.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == 422


def test_voice_oversize_is_413(monkeypatch):
    _mock_sarvam(monkeypatch)
    monkeypatch.setattr(config, "MAX_AUDIO_BYTES", 10)
    r = client.post("/voice", files={"file": ("a.wav", b"x" * 11, "audio/wav")})
    assert r.status_code == 413


@pytest.mark.parametrize("status,expected", [(429, 503), (500, 502), (None, 502)])
def test_voice_sarvam_failure_mapping(monkeypatch, status, expected):
    async def boom(*a, **k):
        raise sarvam.SarvamError("nope", status)

    monkeypatch.setattr(sarvam, "transcribe", boom)
    r = client.post("/voice", files={"file": ("a.wav", b"RIFFfake", "audio/wav")})
    assert r.status_code == expected


def test_load_test_header_bypasses_sarvam(monkeypatch):
    async def must_not_be_called(*a, **k):
        raise AssertionError("Sarvam was called during a load test")

    monkeypatch.setattr(sarvam, "transcribe", must_not_be_called)
    monkeypatch.setattr(sarvam, "extract_journey", must_not_be_called)
    monkeypatch.setattr(config, "LOAD_TEST_STUB_DELAY_SECONDS", 0)
    r = client.post("/voice", files={"file": ("a.wav", b"", "audio/wav")}, headers={"X-Load-Test": "1"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "stub"
    assert body["journey"]["origin"]["code"] == "SBC"


def test_parse_text(monkeypatch):
    _mock_sarvam(monkeypatch)
    r = client.post("/journey/parse", json={"text": "kota jaana hai"})
    assert r.status_code == 200
    assert r.json()["transcript"] == "kota jaana hai"


def test_healthz():
    assert client.get("/healthz").json()["status"] == "ok"


# --- TLS trust -------------------------------------------------------------

def test_custom_ca_bundle_is_added_to_the_default_certificates(monkeypatch):
    import ssl

    import certifi

    system_only = ssl.create_default_context()
    monkeypatch.setattr(config, "SARVAM_CA_BUNDLE", certifi.where())
    client = sarvam._client()
    ctx = client._transport._pool._ssl_context  # the context httpx will actually use
    # Its trust store is the system defaults plus the bundle: at least as many certs as the defaults.
    assert len(ctx.get_ca_certs()) >= len(system_only.get_ca_certs())


def test_missing_ca_bundle_file_fails_loudly(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_CA_BUNDLE", "/nonexistent/ca.pem")
    with pytest.raises(FileNotFoundError):
        sarvam._client()
