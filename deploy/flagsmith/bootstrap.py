#!/usr/bin/env python3
"""Configure a local Flagsmith for GharChalo, end to end. Safe to run repeatedly.

    docker compose -f deploy/flagsmith/docker-compose.yml up -d
    python3 deploy/flagsmith/bootstrap.py

Creates (only what is missing): an admin user, the GharChalo organisation and project,
the 8 features from FLAGSMITH_SETUP.md, the `urgent_travellers` segment with its
`tatkal_level = 0` override, and a server-side key. Then it writes:

    api/.env.local                      FLAGSMITH_SERVER_KEY / FLAGSMITH_API_URL (git-ignored; api/.env is never touched)
    api/flagsmith_env.json              offline copy of the environment (no-Wi-Fi backup)
    deploy/flagsmith/credentials.txt    dashboard login (git-ignored, local only)

Standard library only. The admin password below protects a Flagsmith that only
listens on your own machine; change it if you ever expose that server.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("FLAGSMITH_URL", "http://localhost:8090").rstrip("/")
API = f"{BASE}/api/v1"
EMAIL = os.environ.get("FLAGSMITH_ADMIN_EMAIL", "admin@gharchalo.local")
PASSWORD = os.environ.get("FLAGSMITH_ADMIN_PASSWORD", "Festive-Rangoli-2026!")
ORG_NAME = PROJECT_NAME = "GharChalo"
ENVIRONMENT = "Development"
SERVER_KEY_NAME = "gharchalo-api"

# Demo identities (open the app with ?as=demo-5km etc.) pinned to one variation with identity
# overrides, so side-by-side demos are exact instead of left to the random split.
DEMO_IDENTITIES = [  # (identity, feature, value)
    ("demo-5km", "max_station_distance_km", 5),
    ("demo-15km", "max_station_distance_km", 15),
    ("demo-30km", "max_station_distance_km", 30),
    ("demo-exact", "matching_strategy", "exact"),
    ("demo-flex", "matching_strategy", "time_window"),
]

# Tuning numbers for the exact-vs-flexible matching A/B (api/matching.py). Exact is strict (your station,
# your day, an overlapping window); flexible relaxes all three. Change them live in the dashboard.
MATCHING_CONFIG = {"max_matches": 8, "exact_pickup_km": 0, "flex_pickup_km": 15, "date_flex_days": 1, "time_window_min": 120}

# name, type, default_enabled, initial value, multivariate options (value, % allocation)
FEATURES = [
    ("tatkal_level", "STANDARD", True, "0", []),
    ("tatkal_config", "STANDARD", True, '{"cache_ttl_s":30,"poll_s_l0":30,"poll_s_l1":120}', []),
    # Control 15 km keeps the remaining 34%; the two variations take 33% each.
    ("max_station_distance_km", "MULTIVARIATE", True, "15", [(5, 33), (30, 33)]),
    ("matching_strategy", "MULTIVARIATE", True, "exact", [("time_window", 50)]),
    ("matching_config", "STANDARD", True, json.dumps(MATCHING_CONFIG), []),
    ("interaction_mode", "STANDARD", True, "voice", []),
    ("route_fault_sbc_hyb", "STANDARD", False, None, []),  # incident toggle: OFF
    ("sarvam_fault_mode", "STANDARD", True, "none", []),  # none | 429 | timeout | error
]


class ApiError(RuntimeError):
    pass


def call(method: str, path: str, body=None, token: str | None = None, headers: dict | None = None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Token {token}"} if token else {}), **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:600]
        raise ApiError(f"{method} {path} -> HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"Cannot reach Flagsmith at {BASE} ({exc.reason}). Is it running?") from None


def results(payload) -> list:
    return payload["results"] if isinstance(payload, dict) and "results" in payload else payload or []


def step(text: str) -> None:
    print(f"==> {text}")


def login() -> str:
    try:
        call("POST", "/auth/users/", {
            "email": EMAIL, "first_name": "Local", "last_name": "Admin", "password": PASSWORD, "re_password": PASSWORD,
        })
        step(f"Created admin user {EMAIL}")
    except ApiError as exc:
        # Already registered on an earlier run: just log in below.
        if "email" not in str(exc).lower() and "exists" not in str(exc).lower() and "password" in str(exc).lower():
            raise
    return call("POST", "/auth/login/", {"email": EMAIL, "password": PASSWORD})["key"]


def find(items: list, name: str):
    return next((i for i in items if i.get("name") == name), None)


def pin_demo_identities(env_key: str, features: dict, token: str) -> None:
    """Pin each demo identity to one value of a multivariate feature.

    The Python SDK's local evaluation honours the override's own value, not a split of
    the variations, so the value is what gets set (the variation rows are kept consistent).
    """
    for identifier, feature_name, wanted in DEMO_IDENTITIES:
        feature = features[feature_name]
        options = {(opt["integer_value"] if opt.get("integer_value") is not None else opt["string_value"]): opt["id"]
                   for opt in feature.get("multivariate_options", [])}
        found = results(call("GET", f"/environments/{env_key}/identities/?q={identifier}", token=token))
        identity = next((i for i in found if i.get("identifier") == identifier), None)
        if not identity:
            identity = call("POST", f"/environments/{env_key}/identities/", {"identifier": identifier}, token)
        base = f"/environments/{env_key}/identities/{identity['id']}/featurestates/"
        state = next((st for st in results(call("GET", base, token=token)) if st.get("feature") == feature["id"]), None)
        if state is None:
            allocations = [
                {"multivariate_feature_option": opt_id, "percentage_allocation": 100 if value == wanted else 0}
                for value, opt_id in options.items()
            ]
            state = call("POST", base, {"feature": feature["id"], "enabled": True, "multivariate_feature_state_values": allocations}, token)
        if state.get("feature_state_value") != wanted:
            call("PUT", f"{base}{state['id']}/", {"feature": feature["id"], "enabled": True, "feature_state_value": wanted}, token)
            step(f"Pinned identity {identifier}: {feature_name} = {wanted}")


def ensure_matching_config(env_key: str, env_id: int, feature: dict, token: str) -> None:
    """Add any tuning keys the dashboard value is missing, keeping values someone already changed."""
    states = results(call("GET", f"/environments/{env_key}/featurestates/?feature={feature['id']}", token=token))
    state = next(st for st in states if st.get("feature_segment") is None and st.get("identity") is None)
    try:
        current = json.loads(state["feature_state_value"])
    except (TypeError, ValueError):
        current = {}
    merged = {**MATCHING_CONFIG, **current}
    if merged != current:
        call("PUT", f"/environments/{env_key}/featurestates/{state['id']}/",
             {"feature": feature["id"], "environment": env_id, "enabled": True, "feature_state_value": json.dumps(merged)}, token)
        step(f"Updated matching_config with: {', '.join(sorted(set(merged) - set(current)))}")


# --------------------------------------------------------------------------------------------
# Flagsmith's Experiments tab, plus the descriptions and tags that explain everything in the UI
# --------------------------------------------------------------------------------------------

# Experiments need keyed variants. The control (the flag's base value) is always keyed "control".
VARIANT_KEYS = {
    ("max_station_distance_km", 5): "reach_5km",
    ("max_station_distance_km", 30): "reach_30km",
    ("matching_strategy", "time_window"): "flexible",
}

METRICS = [  # name, event sent by the app, description
    ("alternative_selected", "alternative_selected", "The visitor chose a train from a nearby station"),
    ("match_accepted", "match_accepted", "The visitor accepted the co-traveller group they were offered"),
]

DATA_NOTE = (
    " Data note: this demo includes synthetic visitors (identities sim-*) who behave identically in every variant, "
    "so any difference, lift or 'chance to win' computed from them is noise, not a finding about real travellers."
)

EXPERIMENTS = [  # feature, name, metric, hypothesis ({control} is filled from the live flag)
    (
        "max_station_distance_km",
        "Station reach: how far to look for another station [demo data]",
        "alternative_selected",
        "When a visitor's own station has no seats, looking further for another station (5 km or 30 km, against the "
        "{control} km control) changes how many of them choose an alternative." + DATA_NOTE,
    ),
    (
        "matching_strategy",
        "Matching: exact vs flexible [demo data]",
        "match_accepted",
        "Flexible matching (nearby pickup stations, plus or minus a day, a wider time window) finds more co-travellers than "
        "exact matching and raises how often a visitor accepts a cab group, at the cost of distance and delay." + DATA_NOTE,
    ),
]

TAGS = {  # label -> colour
    "Experiment A": "#2563EB",
    "Experiment B": "#7C3AED",
    "Matching A/B": "#DB2777",
    "Incident switch": "#DC2626",
    "Config": "#64748B",
}

FEATURE_DOCS = {  # feature -> (tag, description shown in the dashboard)
    "tatkal_level": (
        "Experiment A",
        "Experiment A: the Tatkal degradation ladder. 0 normal | 1 slower result refresh | 2 multi-leg planning off | "
        "3 cached search and co-traveller matching paused. Travellers within 48 hours stay at level 0 through the "
        "urgent_travellers segment. Measured on the system itself: see the app's Experiments page and deploy/experiments/simulate.py.",
    ),
    "tatkal_config": ("Experiment A", "Tuning for the ladder: cache_ttl_s (how long level 3 caches search), poll_s_l0 / poll_s_l1 (seconds between result refreshes)."),
    "max_station_distance_km": (
        "Experiment B",
        "Experiment B (see the Experiments tab: 'Station reach'). How far from their own station a visitor is shown trains with seats "
        "when their station is full. Variants: control, reach_5km, reach_30km. Metric: alternative_selected. "
        "Demo identities demo-5km / demo-15km / demo-30km are pinned by identity override and stay outside the experiment.",
    ),
    "matching_strategy": (
        "Matching A/B",
        "Matching A/B (see the Experiments tab: 'Matching'). control = exact: your station, your day, overlapping time. flexible: nearby "
        "stations, plus or minus a day, a wider window. Metric: match_accepted. Demo identities: demo-exact, demo-flex.",
    ),
    "matching_config": (
        "Matching A/B",
        "The numbers behind exact and flexible matching: exact_pickup_km, flex_pickup_km, date_flex_days, time_window_min, max_matches. "
        "Change them live: the app and its matching benchmark follow within about 10 seconds.",
    ),
    "interaction_mode": ("Config", "voice or text_only. text_only is the fallback when Sarvam is down: the Speak tab is disabled and typed search keeps working."),
    "route_fault_sbc_hyb": ("Incident switch", "Incident switch, for testing: when ON, searches between Bengaluru and Hyderabad return a server error while other routes stay healthy. Turn OFF to recover."),
    "sarvam_fault_mode": ("Incident switch", "Incident switch, for testing: none | 429 | timeout | error simulates Sarvam failing without using real quota. Pair with interaction_mode = text_only."),
}


def option_value(opt: dict):
    for field in ("integer_value", "string_value", "boolean_value"):
        if opt.get(field) is not None:
            return opt[field]
    return None


def ensure_events_warehouse(env_key: str, token: str) -> None:
    """Experiments need somewhere to keep events. On self-hosted Postgres that can be Flagsmith's own database."""
    for conn in results(call("GET", f"/environments/{env_key}/warehouse-connections/", token=token)):
        if conn.get("warehouse_type") == "postgres" and (conn.get("config") or {}).get("source") == "flagsmith_database":
            return
    call("POST", f"/environments/{env_key}/warehouse-connections/",
         {"warehouse_type": "postgres", "name": "flagsmith-database", "config": {"source": "flagsmith_database"}}, token)
    step("Created the events warehouse (Flagsmith's own database)")


def ensure_variant_keys(pid: int, features: dict, token: str) -> None:
    for (feature_name, value), key in VARIANT_KEYS.items():
        feature = features[feature_name]
        for opt in feature.get("multivariate_options", []):
            if option_value(opt) == value and opt.get("key") != key:
                body = {"feature": feature["id"], "type": opt["type"], "key": key,
                        "default_percentage_allocation": opt["default_percentage_allocation"]}
                for field in ("integer_value", "string_value", "boolean_value"):
                    body[field] = opt.get(field)
                call("PUT", f"/projects/{pid}/features/{feature['id']}/mv-options/{opt['id']}/", body, token)
                step(f"Variant {feature_name} = {value} is now keyed {key!r}")


def ensure_metrics(env_key: str, token: str) -> dict[str, int]:
    have = {m["name"]: m["id"] for m in results(call("GET", f"/environments/{env_key}/experiment-metrics/", token=token))}
    for name, event, description in METRICS:
        if name not in have:
            created = call("POST", f"/environments/{env_key}/experiment-metrics/", {
                "name": name, "description": description, "aggregation": "occurrence", "direction": "up",
                "definition": {"version": 1, "event": event}}, token)
            have[name] = created["id"]
            step(f"Created metric {name}")
    return have


def ensure_experiments(env_key: str, pid: int, features: dict, metric_ids: dict[str, int], token: str) -> None:
    """One running experiment per feature. The control value and traffic split are read from the live flag,
    never assumed, so whatever the dashboard currently says is what the experiment starts from."""
    listed = results(call("GET", f"/environments/{env_key}/experiments/", token=token))
    # The list nests the feature as an object; creation takes a plain id.
    existing = {(e["feature"]["id"] if isinstance(e["feature"], dict) else e["feature"]): e for e in listed}
    for feature_name, name, metric, hypothesis in EXPERIMENTS:
        feature = features[feature_name]
        found = existing.get(feature["id"])
        states = results(call("GET", f"/environments/{env_key}/featurestates/?feature={feature['id']}", token=token))
        base = next(st for st in states if st.get("feature_segment") is None and st.get("identity") is None)
        control_value = base["feature_state_value"]
        if found is None:
            value_type = "integer" if isinstance(control_value, int) and not isinstance(control_value, bool) else "string"
            found = call("POST", f"/environments/{env_key}/experiments/", {
                "feature": feature["id"], "name": name, "hypothesis": hypothesis.format(control=control_value),
                "metrics": [{"metric": metric_ids[metric], "expected_direction": "increase"}],
                "experiment_rollout": {
                    "enabled": True, "rollout_percentage": 100,
                    "feature_state_value": {"type": value_type, "value": str(control_value)},
                    "multivariate_feature_state_values": [
                        {"multivariate_feature_option": m["multivariate_feature_option"], "percentage_allocation": m["percentage_allocation"]}
                        for m in base["multivariate_feature_state_values"]],
                    "audience": {"match": "any", "segment_ids": []}},
            }, token)
            step(f"Created experiment {name!r}")
        else:
            wanted = {"name": name, "hypothesis": hypothesis.format(control=control_value)}
            changes = {k: v for k, v in wanted.items() if found.get(k) != v}
            if changes:
                call("PATCH", f"/environments/{env_key}/experiments/{found['id']}/", changes, token)
                step(f"Updated experiment {name!r}: {', '.join(changes)}")
        if found.get("status") == "created":
            call("POST", f"/environments/{env_key}/experiments/{found['id']}/start/", {}, token)
            step(f"Started experiment {name!r}")


def ensure_feature_docs(pid: int, features: dict, token: str) -> None:
    """Tags and descriptions, so the dashboard itself explains each flag."""
    tags = {t["label"]: t["id"] for t in results(call("GET", f"/projects/{pid}/tags/", token=token))}
    for label, color in TAGS.items():
        if label not in tags:
            tags[label] = call("POST", f"/projects/{pid}/tags/", {"label": label, "color": color}, token)["id"]
            step(f"Created tag {label!r}")
    for feature_name, (tag, description) in FEATURE_DOCS.items():
        feature = features[feature_name]
        wanted_tags = sorted({*feature.get("tags", []), tags[tag]})
        if feature.get("description") != description or sorted(feature.get("tags", [])) != wanted_tags:
            call("PATCH", f"/projects/{pid}/features/{feature['id']}/",
                 {"description": description, "tags": wanted_tags}, token)
            step(f"Documented feature {feature_name}")


def main() -> int:
    token = login()

    org = find(results(call("GET", "/organisations/", token=token)), ORG_NAME)
    if not org:
        org = call("POST", "/organisations/", {"name": ORG_NAME}, token)
        step(f"Created organisation {ORG_NAME}")

    projects = results(call("GET", f"/projects/?organisation={org['id']}", token=token))
    project = find(projects, PROJECT_NAME)
    if not project:
        project = call("POST", "/projects/", {"name": PROJECT_NAME, "organisation": org["id"]}, token)
        step(f"Created project {PROJECT_NAME}")
    pid = project["id"]

    envs = results(call("GET", f"/projects/{pid}/environments/", token=token))
    env = find(envs, ENVIRONMENT) or (envs[0] if envs else None)
    if not env:
        env = call("POST", "/environments/", {"name": ENVIRONMENT, "project": pid}, token)
    env_key = env["api_key"]
    step(f"Using environment {env['name']}")

    existing = {f["name"]: f for f in results(call("GET", f"/projects/{pid}/features/?page_size=100", token=token))}
    for name, ftype, enabled, initial, options in FEATURES:
        if name in existing:
            continue
        body = {"name": name, "type": ftype, "default_enabled": enabled, "initial_value": initial}
        if options:
            body["multivariate_options"] = [
                {"type": "int", "integer_value": v, "default_percentage_allocation": pct}
                if isinstance(v, int)
                else {"type": "unicode", "string_value": v, "default_percentage_allocation": pct}
                for v, pct in options
            ]
        existing[name] = call("POST", f"/projects/{pid}/features/", body, token)
        step(f"Created feature {name}")

    pin_demo_identities(env_key, existing, token)
    ensure_matching_config(env_key, env["id"], existing["matching_config"], token)

    ensure_events_warehouse(env_key, token)
    ensure_variant_keys(pid, existing, token)
    metric_ids = ensure_metrics(env_key, token)
    ensure_experiments(env_key, pid, existing, metric_ids, token)
    # Experiments and tags change the feature objects, so read them again before documenting them.
    existing = {f["name"]: f for f in results(call("GET", f"/projects/{pid}/features/?page_size=100", token=token))}
    ensure_feature_docs(pid, existing, token)

    segments = results(call("GET", f"/projects/{pid}/segments/", token=token))
    segment = find(segments, "urgent_travellers")
    if not segment:
        segment = call("POST", f"/projects/{pid}/segments/", {
            "name": "urgent_travellers",
            "description": "Travelling within 48 hours: always full service (tatkal_level 0)",
            "rules": [{"type": "ALL", "rules": [{"type": "ANY", "conditions": [
                {"operator": "EQUAL", "property": "travels_within_48h", "value": "true"}]}]}],
        }, token)
        step("Created segment urgent_travellers")

    tatkal = existing["tatkal_level"]
    try:
        call("POST", f"/environments/{env_key}/features/{tatkal['id']}/create-segment-override/", {
            "enabled": True,
            "feature_state_value": {"type": "int", "integer_value": 0},
            "feature_segment": {"segment": segment["id"]},
        }, token)
        step("Created override: urgent_travellers -> tatkal_level = 0")
    except ApiError as exc:
        if "already" not in str(exc).lower() and "exist" not in str(exc).lower() and "unique" not in str(exc).lower():
            raise
        step("Override urgent_travellers -> tatkal_level already exists")

    keys = results(call("GET", f"/environments/{env_key}/api-keys/", token=token))
    key = find(keys, SERVER_KEY_NAME) or call("POST", f"/environments/{env_key}/api-keys/", {"name": SERVER_KEY_NAME}, token)
    server_key = key["key"]
    step("Server-side key ready")

    # Offline copy: the app can run from this file when there is no network (FLAGSMITH_OFFLINE_FILE).
    document = call("GET", f"/environments/{env_key}/document/", token=token)
    (ROOT / "api" / "flagsmith_env.json").write_text(json.dumps(document, indent=2))

    (ROOT / "api" / ".env.local").write_text(
        "# Written by deploy/flagsmith/bootstrap.py. Local only, git-ignored. api/.env is untouched.\n"
        f"FLAGSMITH_SERVER_KEY={server_key}\n"
        f"FLAGSMITH_API_URL={API}/\n"
        "FLAGSMITH_REFRESH_SECONDS=10\n"
        "DEMO_NOW=2026-11-25T10:00\n"
    )
    (ROOT / "deploy" / "flagsmith" / "credentials.txt").write_text(
        f"Dashboard: {BASE}\nEmail:     {EMAIL}\nPassword:  {PASSWORD}\nProject:   {PROJECT_NAME} / {ENVIRONMENT}\n"
    )

    print(f"\nDone. Flagsmith dashboard: {BASE}  (login in deploy/flagsmith/credentials.txt)")
    print("Restart the API; http://localhost:8000/healthz should now report \"flagsmith\": \"flagsmith\".")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        sys.exit(1)
