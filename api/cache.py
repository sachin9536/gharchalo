"""Tiny in-process TTL cache for /search at tatkal_level 3.

Redis is explicitly out of scope (roadmap section 5). The TTL is checked on read,
so changing `tatkal_config.cache_ttl_s` in Flagsmith takes effect immediately.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Hashable

MAX_ENTRIES = 1024


class TTLCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._data: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, key: Hashable, ttl_seconds: float) -> Any | None:
        with self._lock:
            item = self._data.get(key)
        if item is None:
            return None
        stored_at, value = item
        if time.monotonic() - stored_at > ttl_seconds:
            return None
        return value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self._max and key not in self._data:
                # Drop the oldest entry; good enough for a demo-sized key space.
                oldest = min(self._data, key=lambda k: self._data[k][0])
                del self._data[oldest]
            self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


search_cache = TTLCache()
