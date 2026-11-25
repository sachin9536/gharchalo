"""Prometheus metrics (GET /metrics) plus small in-process counters for /experiments/summary.

Metric names match the roadmap's measurement table (section 7): request rate,
error rate, p95, cache/live share, matches served, urgent-user p95.
"""

from __future__ import annotations

import threading
from collections import Counter as _Counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

import flags

_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

http_requests = Counter(
    "gharchalo_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
http_latency = Histogram(
    "gharchalo_http_request_duration_seconds", "HTTP latency", ["method", "path"], buckets=_BUCKETS
)
urgency_latency = Histogram(
    "gharchalo_request_duration_by_urgency_seconds",
    "Latency of /search and /match split by urgent_travellers membership",
    ["endpoint", "urgent"],
    buckets=_BUCKETS,
)
urgency_errors = Counter(
    "gharchalo_request_errors_by_urgency_total", "5xx on /search and /match by urgency", ["endpoint", "urgent"]
)
search_served = Counter("gharchalo_search_served_total", "Search responses by source", ["served_from"])
alternatives_shown = Counter(
    "gharchalo_alternatives_shown_total", "Nearby-station alternatives shown", ["cohort_km"]
)
alternatives_selected = Counter(
    "gharchalo_alternatives_selected_total", "Nearby-station alternatives selected", ["cohort_km"]
)
matches_offered = Counter("gharchalo_matches_offered_total", "Match offers", ["strategy"])
matches_accepted = Counter("gharchalo_matches_accepted_total", "Match accepts", ["strategy"])
match_paused = Counter("gharchalo_match_paused_total", "/match calls paused by tatkal_level 3")

tatkal_level = Gauge("gharchalo_tatkal_level", "Environment value of the tatkal_level flag")
tatkal_level.set_function(flags.environment_level)

# In-process mirror for /experiments/summary (Prometheus counters are not meant to be read back).
_local = _Counter()
_local_lock = threading.Lock()


def bump(name: str, amount: int = 1) -> None:
    with _local_lock:
        _local[name] += amount


def local_counts() -> dict[str, int]:
    with _local_lock:
        return dict(_local)


def observe_request(method: str, path: str, status: int, seconds: float) -> None:
    http_requests.labels(method, path, str(status)).inc()
    http_latency.labels(method, path).observe(seconds)


def observe_urgency(endpoint: str, urgent: bool, seconds: float, status: int) -> None:
    label = "true" if urgent else "false"
    urgency_latency.labels(endpoint, label).observe(seconds)
    if status >= 500:
        urgency_errors.labels(endpoint, label).inc()


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
