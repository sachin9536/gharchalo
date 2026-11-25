"""Station aliases.

The model never produces station codes: it returns the city words the speaker
used, and this table maps them to a station. A bare city name ("Bangalore")
resolves to that city's primary station; other stations resolve only by their
own name, code or alias. Data lives in seed_data.py (single source of truth,
shared with the database seed).
"""

import difflib
import re
import unicodedata

from seed_data import STATIONS, StationSeed

Station = StationSeed  # public name used by journey.py


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)  # \w keeps Devanagari/Kannada letters
    return re.sub(r"\s+", " ", text).strip()


_BY_ALIAS: dict[str, Station] = {}
for _station in STATIONS:
    _names = [_station.name, _station.code, *_station.aliases]
    if _station.is_primary:
        _names.append(_station.city)
    for _alias in _names:
        _BY_ALIAS[_normalize(_alias)] = _station


def resolve(text: str | None) -> Station | None:
    """Map spoken/typed city words to a station, or None if we can't tell."""
    if not text:
        return None
    key = _normalize(text)
    if not key:
        return None
    if key in _BY_ALIAS:
        return _BY_ALIAS[key]
    # STT sometimes drops or swaps a letter ("hydrabad"): allow a close match.
    close = difflib.get_close_matches(key, _BY_ALIAS.keys(), n=1, cutoff=0.85)
    return _BY_ALIAS[close[0]] if close else None
