"""Every Flagsmith call lives here; no other module imports the SDK.

Design rules (see CONTEXT.md section 8 and the roadmap PDF, section 3):
  * Local evaluation: the SDK downloads the environment document every
    FLAGSMITH_REFRESH_SECONDS and evaluates flags in-process, so a k6 storm
    makes zero calls to Flagsmith per request.
  * Safe defaults: every flag has a default equal to the old hardcoded
    behaviour. No key, no SDK, a network failure or a bad dashboard value all
    fall back to these defaults; flags can never take the API down.
  * Values are validated and clamped here, so the rest of the code can trust them.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import config

log = logging.getLogger("gharchalo.flags")

# name -> (enabled, value). Mirrors what the dashboard should contain.
DEFAULTS: dict[str, tuple[bool, Any]] = {
    # Experiment A: degradation ladder (0 normal ... 3 cache /search, pause /match).
    "tatkal_level": (True, 0),
    "tatkal_config": (True, {"cache_ttl_s": 30, "poll_s_l0": 30, "poll_s_l1": 120}),
    # Experiment B: alternative departure-station tolerance (multivariate 5 / 15 / 30).
    "max_station_distance_km": (True, 15),
    # Optional matching experiment.
    "matching_strategy": (True, "exact"),
    "matching_config": (
        True,
        {"max_matches": 8, "exact_pickup_km": 0, "flex_pickup_km": 15, "date_flex_days": 1, "time_window_min": 120},
    ),
    # P1: text-only fallback when Sarvam is down.
    "interaction_mode": (True, "voice"),
    # P1 test-only fault switches (controlled, reversible incidents).
    "route_fault_sbc_hyb": (False, None),
    "sarvam_fault_mode": (True, "none"),
    # Release toggles: on/off per visitor. Off by default; Flagsmith rolls them out (percentage,
    # situation segments, or everyone) without a deploy, and switching them off is the kill switch.
    "tatkal_countdown": (False, None),
}

RELEASE_FLAGS = ("tatkal_countdown",)

COHORTS = (5, 15, 30)
STRATEGIES = ("exact", "time_window")
INTERACTION_MODES = ("voice", "text_only")
SARVAM_FAULT_MODES = ("none", "429", "timeout", "error")
URGENT_WINDOW = dt.timedelta(hours=48)

_client: Any = None
_client_ready = False
_lock = threading.Lock()


# --------------------------------------------------------------------------- client


def events_base_url() -> str:
    """Where the SDK sends experiment events; "" means its default (Flagsmith's cloud endpoint).

    The SDK appends `v1/events` to this, so for a self-hosted server whose API is
    http://host/api/v1/ it must be http://host/api/ (not .../api/v1/events/).
    """
    if config.FLAGSMITH_EVENTS_URL:
        return config.FLAGSMITH_EVENTS_URL.rstrip("/") + "/"
    api = config.FLAGSMITH_API_URL.rstrip("/")
    if not api:
        return ""
    return (api[: -len("/v1")] if api.endswith("/v1") else api) + "/"


def _build_client() -> Any:
    if not (config.FLAGSMITH_SERVER_KEY or config.FLAGSMITH_OFFLINE_FILE):
        log.info("Flagsmith not configured: using safe defaults")
        return None
    try:
        from flagsmith import Flagsmith
        from flagsmith.models import DefaultFlag
    except ImportError:
        log.warning("flagsmith package is not installed: using safe defaults (pip install -r requirements.txt)")
        return None

    def default_handler(feature_name: str) -> DefaultFlag:
        enabled, value = DEFAULTS.get(feature_name, (False, None))
        if isinstance(value, dict):
            value = json.dumps(value)
        return DefaultFlag(enabled=enabled, value=value)

    kwargs: dict[str, Any] = {"default_flag_handler": default_handler}
    if config.FLAGSMITH_OFFLINE_FILE:
        # Tests and no-wifi demos: evaluate against a saved environment document.
        from flagsmith.offline_handlers import LocalFileHandler

        kwargs.update(offline_mode=True, offline_handler=LocalFileHandler(config.FLAGSMITH_OFFLINE_FILE))
    else:
        if not config.FLAGSMITH_SERVER_KEY.startswith("ser."):
            log.warning("FLAGSMITH_SERVER_KEY should be a server-side key (ser.…) for local evaluation")
        from urllib3.util import Retry

        kwargs.update(
            # Fail fast. The local-evaluation poller refreshes on its own schedule, so a retried
            # request only delays the visitor; the default-flag handler takes over instead.
            request_timeout_seconds=config.FLAGSMITH_TIMEOUT_SECONDS,
            retries=Retry(total=0),
            environment_key=config.FLAGSMITH_SERVER_KEY,
            enable_local_evaluation=True,
            enable_analytics=config.FLAGSMITH_ANALYTICS,
            enable_events=config.FLAGSMITH_EVENTS,
            environment_refresh_interval_seconds=config.FLAGSMITH_REFRESH_SECONDS,
        )
        if config.FLAGSMITH_API_URL:
            kwargs["api_url"] = config.FLAGSMITH_API_URL
        events_url = events_base_url()
        if config.FLAGSMITH_EVENTS and events_url:
            # Self-hosted Flagsmith: events go to our own server, not Flagsmith's cloud endpoint.
            from flagsmith.analytics import EventProcessorConfig

            kwargs["event_processor_config"] = EventProcessorConfig(events_api_url=events_url)
    try:
        return Flagsmith(**kwargs)
    except Exception:
        log.exception("Flagsmith client failed to start: using safe defaults")
        return None


def client() -> Any:
    global _client, _client_ready
    if not _client_ready:
        with _lock:
            if not _client_ready:
                _client = _build_client()
                _client_ready = True
    return _client


def status() -> str:
    """For /healthz: where flag values come from."""
    if client() is None:
        return "defaults"
    return "offline_file" if config.FLAGSMITH_OFFLINE_FILE else "flagsmith"


# --------------------------------------------------------------------------- parsing


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_json(value: Any, default: dict) -> dict:
    if isinstance(value, dict):
        return {**default, **value}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return {**default, **parsed}
        except json.JSONDecodeError:
            log.warning("invalid JSON in flag value: %r", value[:80])
    return dict(default)


def _as_choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text if text in choices else default


Getter = Callable[[str], tuple[bool, Any]]


def _defaults_getter(name: str) -> tuple[bool, Any]:
    return DEFAULTS.get(name, (False, None))


def _sdk_getter(flags_obj: Any) -> Getter:
    def get(name: str) -> tuple[bool, Any]:
        try:
            return bool(flags_obj.is_feature_enabled(name)), flags_obj.get_feature_value(name)
        except Exception:
            return _defaults_getter(name)

    return get


# --------------------------------------------------------------------------- urgency


def now() -> dt.datetime:
    """Wall clock, or DEMO_NOW so the urgent window is predictable on stage."""
    if config.DEMO_NOW:
        try:
            return dt.datetime.fromisoformat(config.DEMO_NOW)
        except ValueError:
            log.warning("DEMO_NOW is not ISO format: %r", config.DEMO_NOW)
    return dt.datetime.now()


def urgency(journey_date: dt.date | None) -> tuple[bool, int | None]:
    """(travels_within_48h, days_until_travel). Measured to the start of the travel day."""
    if journey_date is None:
        return False, None
    current = now()
    days = (journey_date - current.date()).days
    start_of_day = dt.datetime.combine(journey_date, dt.time.min)
    urgent = days >= 0 and (start_of_day - current) <= URGENT_WINDOW
    return urgent, days


# --------------------------------------------------------------------------- public API


@dataclass(frozen=True)
class UserFlags:
    tatkal_level: int
    tatkal_config: dict
    max_km: int
    matching_strategy: str
    matching_config: dict
    interaction_mode: str
    urgent: bool
    days_until_travel: int | None
    source: str  # "identity" | "environment" | "defaults"
    features: dict = field(default_factory=dict)  # release toggle name -> on for this visitor

    @property
    def poll_s(self) -> int:
        key = "poll_s_l1" if self.tatkal_level >= 1 else "poll_s_l0"
        return max(5, _as_int(self.tatkal_config.get(key), 30))

    @property
    def cache_ttl_s(self) -> int:
        return max(1, _as_int(self.tatkal_config.get("cache_ttl_s"), 30))


def _resolve(get: Getter, urgent: bool, days: int | None, source: str) -> UserFlags:
    def value(name: str) -> Any:
        enabled, val = get(name)
        # A disabled remote-config feature means "use the default".
        return val if enabled else DEFAULTS[name][1]

    km = _as_int(value("max_station_distance_km"), 15)
    return UserFlags(
        tatkal_level=max(0, min(3, _as_int(value("tatkal_level"), 0))),
        tatkal_config=_as_json(value("tatkal_config"), DEFAULTS["tatkal_config"][1]),
        max_km=km if km in COHORTS else 15,
        matching_strategy=_as_choice(value("matching_strategy"), STRATEGIES, "exact"),
        matching_config=_as_json(value("matching_config"), DEFAULTS["matching_config"][1]),
        interaction_mode=_as_choice(value("interaction_mode"), INTERACTION_MODES, "voice"),
        urgent=urgent,
        days_until_travel=days,
        source=source,
        features={name: bool(get(name)[0]) for name in RELEASE_FLAGS},
    )


def for_user(user_id: str | None, journey_date: dt.date | None = None, lang: str | None = None) -> UserFlags:
    """Flags for one person. Segment overrides (urgent_travellers) and multivariate
    cohorts are decided by Flagsmith from the identity + traits sent here."""
    urgent, days = urgency(journey_date)
    c = client()
    if c is None:
        return _resolve(_defaults_getter, urgent, days, "defaults")
    try:
        if user_id:
            traits: dict[str, Any] = {"travels_within_48h": urgent}
            if days is not None:
                traits["days_until_travel"] = days
            if lang:
                traits["lang"] = lang
            flags_obj = c.get_identity_flags(identifier=user_id, traits=traits)
            return _resolve(_sdk_getter(flags_obj), urgent, days, "identity")
        # Anonymous traffic (e.g. k6 without an id) still follows environment values.
        return _resolve(_sdk_getter(c.get_environment_flags()), urgent, days, "environment")
    except Exception:
        log.exception("flag evaluation failed: using safe defaults")
        return _resolve(_defaults_getter, urgent, days, "defaults")


def environment(name: str) -> tuple[bool, Any]:
    """(enabled, value) of an environment-level flag (no identity)."""
    c = client()
    if c is None:
        return _defaults_getter(name)
    try:
        return _sdk_getter(c.get_environment_flags())(name)
    except Exception:
        log.exception("environment flag evaluation failed: %s", name)
        return _defaults_getter(name)


def environment_level() -> int:
    enabled, value = environment("tatkal_level")
    return max(0, min(3, _as_int(value, 0))) if enabled else 0


def route_fault_on() -> bool:
    return environment("route_fault_sbc_hyb")[0]


def sarvam_fault_mode() -> str:
    enabled, value = environment("sarvam_fault_mode")
    return _as_choice(value, SARVAM_FAULT_MODES, "none") if enabled else "none"


def interaction_mode() -> str:
    enabled, value = environment("interaction_mode")
    return _as_choice(value, INTERACTION_MODES, "voice") if enabled else "voice"


def shutdown() -> None:
    """Flush buffered experiment events and stop the client's background threads."""
    global _client, _client_ready
    with _lock:
        c, _client, _client_ready = _client, None, False
    if c is not None:
        try:
            c.close()
        except Exception:
            log.exception("Flagsmith client did not close cleanly")


def reset_for_tests() -> None:
    global _client, _client_ready
    with _lock:
        _client, _client_ready = None, False
