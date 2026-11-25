"""Settings, read once from the environment (and api/.env if present)."""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env.local (written by deploy/flagsmith/bootstrap.py) is read first so it wins; api/.env stays yours.
load_dotenv(Path(__file__).parent / ".env.local")
load_dotenv(Path(__file__).parent / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


SARVAM_API_KEY = _get("SARVAM_API_KEY")
SARVAM_BASE_URL = _get("SARVAM_BASE_URL", "https://api.sarvam.ai")

# Model names change over time: override in .env instead of editing code.
SARVAM_STT_MODEL = _get("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_STT_MODE = _get("SARVAM_STT_MODE")  # only sent when set, e.g. "transcribe"
SARVAM_CHAT_MODEL = _get("SARVAM_CHAT_MODEL", "sarvam-105b")
# Text-to-speech (Bulbul). Empty = Sarvam's current default model and voice, so a renamed model
# cannot break spoken replies the way the retired chat model once did.
SARVAM_TTS_MODEL = _get("SARVAM_TTS_MODEL")  # e.g. bulbul:v3
SARVAM_TTS_SPEAKER = _get("SARVAM_TTS_SPEAKER")  # e.g. priya
TTS_MAX_CHARS = int(_get("TTS_MAX_CHARS", "500"))

# Optional path to a PEM file with your network's root CA (only needed if the
# macOS keychain does not already trust it).
SARVAM_CA_BUNDLE = _get("SARVAM_CA_BUNDLE")

SARVAM_TIMEOUT_SECONDS = float(_get("SARVAM_TIMEOUT_SECONDS", "30"))
MAX_AUDIO_BYTES = int(_get("MAX_AUDIO_BYTES", str(10 * 1024 * 1024)))

# What /voice returns when the request carries `X-Load-Test: 1` (storm traffic
# must never reach the real Sarvam API).
LOAD_TEST_STUB_DELAY_SECONDS = float(_get("LOAD_TEST_STUB_DELAY_SECONDS", "0.8"))

# Database. Pool settings are env-driven on purpose: the DB-pool incident in the
# roadmap is produced by setting DB_POOL_SIZE=2 / DB_MAX_OVERFLOW=0.
DATABASE_URL = _get("DATABASE_URL", "postgresql+psycopg://gharchalo:gharchalo@localhost:5432/gharchalo")
DB_POOL_SIZE = int(_get("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(_get("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT_SECONDS = float(_get("DB_POOL_TIMEOUT_SECONDS", "10"))

# Flagsmith (see flags.py). Empty key -> every flag uses its safe default.
FLAGSMITH_SERVER_KEY = _get("FLAGSMITH_SERVER_KEY")  # server-side key, starts with "ser."
FLAGSMITH_API_URL = _get("FLAGSMITH_API_URL")  # only for self-hosted Flagsmith
FLAGSMITH_REFRESH_SECONDS = int(_get("FLAGSMITH_REFRESH_SECONDS", "10"))  # how fast dashboard changes land
FLAGSMITH_OFFLINE_FILE = _get("FLAGSMITH_OFFLINE_FILE")  # saved environment document (tests / no wifi)
# Sends flag-evaluation counts to Flagsmith, which draws the per-flag charts in its dashboard.
FLAGSMITH_ANALYTICS = _get("FLAGSMITH_ANALYTICS", "1").lower() in ("1", "true", "yes")
# Sends experiment events (who saw which variant, and what they did) to Flagsmith's Experiments tab.
FLAGSMITH_EVENTS = _get("FLAGSMITH_EVENTS", "1").lower() in ("1", "true", "yes")
# Base URL the SDK appends "v1/events" to. Default: derived from FLAGSMITH_API_URL (self-hosted only).
FLAGSMITH_EVENTS_URL = _get("FLAGSMITH_EVENTS_URL")
# How long one call to Flagsmith may take. Kept short and without retries: if Flagsmith is down the
# app must fall back to its defaults at once, not add seconds to every request.
FLAGSMITH_TIMEOUT_SECONDS = int(_get("FLAGSMITH_TIMEOUT_SECONDS", "2"))

# PLANTED FAULT for the NudgeBee incident demo (deploy/incidents/incident.sh oom). Off by default.
# When on, every search response is kept in an in-memory list that is never trimmed: a classic
# unbounded-cache leak that only shows under load and ends in an OOMKilled container.
FAULT_UNBOUNDED_SEARCH_LOG = _get("FAULT_UNBOUNDED_SEARCH_LOG", "0").lower() in ("1", "true", "yes")

# Lets the request override a flag (?max_station_distance_km=, "strategy" on /match).
# Handy for local dev and the existing tests; set to 0 on the demo cluster so
# Flagsmith alone decides cohorts.
ALLOW_FLAG_OVERRIDE = _get("ALLOW_FLAG_OVERRIDE", "1").lower() in ("1", "true", "yes")

# Pretend "now" (ISO, e.g. 2026-11-25T10:00) for the urgent_travellers 48h window.
DEMO_NOW = _get("DEMO_NOW")

# How long a simulated Sarvam timeout (sarvam_fault_mode=timeout) hangs before failing.
SIMULATED_SARVAM_TIMEOUT_SECONDS = float(_get("SIMULATED_SARVAM_TIMEOUT_SECONDS", "5"))

# Intentional buggy release feature (Page 5 Incident 2 / NudgeBee rollback demo).
# False in healthy baseline; True in the faulty release -> 500s on Bengaluru <-> Hyderabad.
ENABLE_EXPRESS_SURGE_PRICING = _get("ENABLE_EXPRESS_SURGE_PRICING", "false").lower() in ("1", "true", "yes")
# Which release this process belongs to (Helm sets it per deployment). Shown in /healthz, an X-Release
# response header and error logs, so incidents can be tied to a release.
RELEASE_VERSION = _get("RELEASE_VERSION", "dev")
