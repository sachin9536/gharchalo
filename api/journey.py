"""Turn the model's raw extraction into a validated journey.

The contract with the rest of the app (CONTRACT.md) is the `Journey` shape.
`missing` lists required fields we could not fill, so the UI can ask for them.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel

import stations

FallbackMode = Literal["train", "shared_cab", "any"]
_FALLBACK_MODES = {"train", "shared_cab", "any"}


class StationRef(BaseModel):
    spoken: str  # the words the speaker used
    code: str | None  # None when the alias table could not resolve it
    name: str | None


class Journey(BaseModel):
    origin: StationRef | None
    destination: StationRef | None
    date: dt.date | None
    fallback_mode: FallbackMode = "train"
    language: str | None = None
    missing: list[str] = []
    warnings: list[str] = []


def _station_ref(spoken: object) -> StationRef | None:
    if not isinstance(spoken, str) or not spoken.strip():
        return None
    station = stations.resolve(spoken)
    return StationRef(
        spoken=spoken.strip(),
        code=station.code if station else None,
        name=station.name if station else None,
    )


def _parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def build_journey(extraction: dict, today: dt.date | None = None) -> Journey:
    today = today or dt.date.today()
    origin = _station_ref(extraction.get("origin_text"))
    destination = _station_ref(extraction.get("destination_text"))
    date = _parse_date(extraction.get("date"))

    fallback = extraction.get("fallback_mode")
    fallback_mode = fallback if fallback in _FALLBACK_MODES else "train"

    language = extraction.get("language")
    language = language.strip().lower() if isinstance(language, str) and language.strip() else None

    missing: list[str] = []
    warnings: list[str] = []

    if origin is None:
        missing.append("origin")
    elif origin.code is None:
        missing.append("origin")
        warnings.append(f"Unknown origin city: {origin.spoken!r}")
    if destination is None:
        missing.append("destination")
    elif destination.code is None:
        missing.append("destination")
        warnings.append(f"Unknown destination city: {destination.spoken!r}")
    if date is None:
        missing.append("date")
    elif date < today:
        warnings.append(f"Date {date.isoformat()} is in the past")

    if origin and destination and origin.code and origin.code == destination.code:
        warnings.append("Origin and destination are the same city")

    return Journey(
        origin=origin,
        destination=destination,
        date=date,
        fallback_mode=fallback_mode,
        language=language,
        missing=missing,
        warnings=warnings,
    )
