"""Settings, read once from the environment (and api/.env if present)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


SARVAM_API_KEY = _get("SARVAM_API_KEY")
SARVAM_BASE_URL = _get("SARVAM_BASE_URL", "https://api.sarvam.ai")

# Model names change over time: override in .env instead of editing code.
SARVAM_STT_MODEL = _get("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_STT_MODE = _get("SARVAM_STT_MODE")  # only sent when set, e.g. "transcribe"
SARVAM_CHAT_MODEL = _get("SARVAM_CHAT_MODEL", "sarvam-105b")

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
