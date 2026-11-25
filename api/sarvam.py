"""Sarvam AI client: speech-to-text and journey extraction (chat).

Endpoint paths, auth header and model names follow Sarvam's public docs as we
understood them before the hackathon and have NOT been verified against a live
key yet. Run `python scripts/smoke_sarvam.py` first: it prints Sarvam's own
error body if anything below is wrong. Model names live in .env.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass

import ssl

import httpx
import truststore

import config

log = logging.getLogger("gharchalo.sarvam")


def _client() -> httpx.AsyncClient:
    """HTTP client that still verifies certificates, but against the OS trust
    store (macOS keychain). Behind a corporate VPN/proxy that re-signs HTTPS,
    its root CA lives there and not in Python's bundled certifi list. If the CA
    is only available as a file, set SARVAM_CA_BUNDLE to its path.
    """
    verify: ssl.SSLContext | str
    if config.SARVAM_CA_BUNDLE:
        verify = config.SARVAM_CA_BUNDLE
    else:
        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.AsyncClient(timeout=config.SARVAM_TIMEOUT_SECONDS, verify=verify)


class SarvamError(Exception):
    """Sarvam call failed. `status` is the upstream HTTP status (None = network)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def rate_limited(self) -> bool:
        return self.status == 429


@dataclass
class Transcript:
    text: str
    language_code: str | None


def _headers() -> dict[str, str]:
    if not config.SARVAM_API_KEY:
        raise SarvamError("SARVAM_API_KEY is not set (copy api/.env.example to api/.env)")
    return {"api-subscription-key": config.SARVAM_API_KEY}


def _raise_for_status(resp: httpx.Response, what: str) -> None:
    if resp.is_success:
        return
    body = resp.text[:500]
    raise SarvamError(f"Sarvam {what} failed: HTTP {resp.status_code}: {body}", resp.status_code)


async def transcribe(audio: bytes, filename: str = "audio.wav", content_type: str = "audio/wav") -> Transcript:
    """Audio bytes -> transcript. Language is auto-detected."""
    data = {"model": config.SARVAM_STT_MODEL, "language_code": "unknown"}
    if config.SARVAM_STT_MODE:
        data["mode"] = config.SARVAM_STT_MODE

    started = time.perf_counter()
    try:
        async with _client() as client:
            resp = await client.post(
                f"{config.SARVAM_BASE_URL}/speech-to-text",
                headers=_headers(),
                data=data,
                files={"file": (filename, audio, content_type)},
            )
    except httpx.HTTPError as exc:
        raise SarvamError(f"Sarvam speech-to-text unreachable: {exc!r}") from exc
    log.info("stt status=%s ms=%.0f", resp.status_code, (time.perf_counter() - started) * 1000)
    _raise_for_status(resp, "speech-to-text")

    body = resp.json()
    return Transcript(text=(body.get("transcript") or "").strip(), language_code=body.get("language_code"))


_EXTRACTION_SYSTEM = """You extract travel intent from transcripts of Indian speech (Hindi, Hinglish, \
English, Kannada, Tamil, Telugu, etc.). Reply with ONLY one JSON object, no prose, no markdown.

Keys:
- "origin_text": the departure city exactly as the speaker said it, or null
- "destination_text": the arrival city exactly as the speaker said it, or null
- "date": travel date as YYYY-MM-DD, or null
- "fallback_mode": "shared_cab" if the speaker wants a shared cab when no train is available, \
"any" if they accept any option, otherwise "train"
- "language": ISO 639-1 code of the speaker's language (e.g. "hi", "en", "kn"), or null

Today's date is {today}. Resolve relative dates ("kal" = tomorrow, "parso" = day after tomorrow) \
and dates without a year to the next upcoming occurrence. Never invent values: use null for \
anything not said."""


def _strip_to_json(text: str) -> dict:
    """Models wrap JSON in <think> blocks and code fences; pull the object out."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise SarvamError(f"Extraction returned no JSON object: {text[:200]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SarvamError(f"Extraction returned invalid JSON: {text[:200]!r}") from exc
    if not isinstance(parsed, dict):
        raise SarvamError("Extraction JSON is not an object")
    return parsed


async def extract_journey(text: str, today: dt.date | None = None) -> dict:
    """Transcript -> raw extraction dict (city words, ISO date). Not validated."""
    today = today or dt.date.today()
    payload = {
        "model": config.SARVAM_CHAT_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _EXTRACTION_SYSTEM.format(today=today.isoformat())},
            {"role": "user", "content": text},
        ],
    }
    started = time.perf_counter()
    try:
        async with _client() as client:
            resp = await client.post(
                f"{config.SARVAM_BASE_URL}/v1/chat/completions",
                headers=_headers(),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise SarvamError(f"Sarvam chat unreachable: {exc!r}") from exc
    log.info("chat status=%s ms=%.0f", resp.status_code, (time.perf_counter() - started) * 1000)
    _raise_for_status(resp, "chat")

    try:
        content = resp.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise SarvamError(f"Unexpected chat response shape: {resp.text[:200]!r}") from exc
    return _strip_to_json(content)
