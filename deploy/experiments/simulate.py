#!/usr/bin/env python3
"""Synthetic-visitor run of GharChalo's three Flagsmith experiments. Standard library only.

    python3 deploy/experiments/simulate.py                        # everything, default sizes
    python3 deploy/experiments/simulate.py --scenario matching --visitors 500

WHAT THIS IS, AND IS NOT
  Every visitor here is synthetic (identity `sim-...`). They go through the real HTTP API, so
  Flagsmith assigns them real cohorts/strategies and every event is really stored. But their
  *choices* come from a fixed, variant-independent rule (SELECT_PROBABILITY / ACCEPT_PROBABILITY
  below): a visitor in the 5 km cohort is exactly as likely to pick an alternative as one in the
  30 km cohort. So differences between variants in the output are noise, not findings. This run
  exercises the pipeline (Flagsmith -> app -> database -> read-out); it says nothing about what
  real travellers prefer. Never present it as evidence about people.

  The one measured thing is Experiment A's *system* behaviour (cache use, paused matching,
  latency per Tatkal level), observed on this machine. Latency is local-laptop latency.

Simulated rows are labelled by the `sim-` prefix; /experiments/summary?source=simulated|live
keeps them apart.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The behaviour model. Identical for every variant, on purpose.
SELECT_PROBABILITY = 0.40  # share of visitors who pick a nearby-station alternative when one is shown
ACCEPT_PROBABILITY = 0.30  # share of visitors who accept the co-traveller group they are offered

ROUTE = {"origin": "SBC", "dest": "HYB"}
URGENT_DATE, NORMAL_DATE = "2026-11-27", "2026-11-30"  # within / beyond 48 h of the demo "now"
EVENING = {"window_start": "18:00", "window_end": "22:00"}

FLAGSMITH = os.environ.get("FLAGSMITH_URL", "http://localhost:8090").rstrip("/") + "/api/v1"
ADMIN = (os.environ.get("FLAGSMITH_ADMIN_EMAIL", "admin@gharchalo.local"),
         os.environ.get("FLAGSMITH_ADMIN_PASSWORD", "Festive-Rangoli-2026!"))


def http(base: str, method: str, path: str, body=None, user: str | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if user:
        headers["X-User-Id"] = user
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw), (time.perf_counter() - started) * 1000
        except ValueError:
            return exc.code, None, (time.perf_counter() - started) * 1000


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def table(title: str, header: list[str], rows: list[list]) -> None:
    print(f"\n{title}")
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]
    line = lambda r: "  " + "  ".join(str(x).ljust(w) for x, w in zip(r, widths))  # noqa: E731
    print(line(header))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


# --------------------------------------------------------------------------- Experiment B

def run_distance(api: str, n: int, rng: random.Random, tag: str) -> dict:
    """Which station-distance cohort Flagsmith gives each visitor, and who picks an alternative."""
    def one(i: int):
        uid = f"sim-dist-{tag}-{i}"
        s, body, _ = http(api, "GET", f"/search?origin={ROUTE['origin']}&dest={ROUTE['dest']}&date={URGENT_DATE}"
                          "&include_connections=false", user=uid)
        if s != 200:
            return None
        picked = False
        alts = body.get("alternatives", [])
        if alts and body.get("search_id") is not None and rng.random() < SELECT_PROBABILITY:
            chosen = rng.choice(alts)
            picked = http(api, "POST", f"/search/{body['search_id']}/select", {"service_id": chosen["id"]}, user=uid)[0] == 200
        return body["max_station_distance_km"], len(alts), picked

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = [o for o in pool.map(one, range(n)) if o]
    by = defaultdict(lambda: {"visitors": 0, "saw_alternatives": 0, "picked": 0})
    for km, shown, picked in outcomes:
        d = by[km]
        d["visitors"] += 1
        d["saw_alternatives"] += shown > 0
        d["picked"] += picked
    table("Experiment B: station-distance cohorts (visitors are synthetic and choose identically)",
          ["cohort", "visitors", "saw alternatives", "picked one"],
          [[f"{km} km", d["visitors"], d["saw_alternatives"], d["picked"]] for km, d in sorted(by.items())])
    return {str(k): v for k, v in by.items()}


# --------------------------------------------------------------------------- matching A/B

def run_matching(api: str, n: int, rng: random.Random, tag: str) -> dict:
    """Which strategy Flagsmith gives each visitor, what they are offered, and who accepts."""
    def one(i: int):
        uid = f"sim-match-{tag}-{i}"
        s, body, _ = http(api, "POST", "/match", {"user_id": uid, **ROUTE, "date": URGENT_DATE, **EVENING}, user=uid)
        if s != 200 or body.get("paused"):
            return None
        accepted = False
        if body["offered"] > 0 and body["match_id"] is not None and rng.random() < ACCEPT_PROBABILITY:
            accepted = http(api, "POST", f"/match/{body['match_id']}/accept", user=uid)[0] == 200
        return body["strategy"], body["offered"], accepted

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = [o for o in pool.map(one, range(n)) if o]
    by = defaultdict(lambda: {"visitors": 0, "offered_total": 0, "accepted": 0})
    for strategy, offered, accepted in outcomes:
        d = by[strategy]
        d["visitors"] += 1
        d["offered_total"] += offered
        d["accepted"] += accepted
    table("Matching A/B: exact vs flexible (visitors are synthetic and accept identically)",
          ["strategy", "visitors", "co-travellers offered each", "accepted"],
          [[k, d["visitors"], round(d["offered_total"] / d["visitors"], 1), d["accepted"]] for k, d in sorted(by.items())])
    return dict(by)


# --------------------------------------------------------------------------- Experiment A

class Flagsmith:
    """Just enough admin access to set tatkal_level and put it back."""

    def __init__(self):
        s, body, _ = http(FLAGSMITH, "POST", "/auth/login/", {"email": ADMIN[0], "password": ADMIN[1]})
        if s != 200:
            raise SystemExit(f"Cannot log in to Flagsmith at {FLAGSMITH} ({s}). Is it running, and did bootstrap.py run?")
        self.token = body["key"]
        results = lambda p: p["results"] if isinstance(p, dict) and "results" in p else p  # noqa: E731
        org = results(self.get("/organisations/"))[0]
        project = next(p for p in results(self.get(f"/projects/?organisation={org['id']}")) if p["name"] == "GharChalo")
        self.env = next(e for e in results(self.get(f"/projects/{project['id']}/environments/")) if e["name"] == "Development")
        feature = next(f for f in results(self.get(f"/projects/{project['id']}/features/?page_size=100")) if f["name"] == "tatkal_level")
        self.feature_id = feature["id"]
        self.state = next(st for st in results(self.get(f"/environments/{self.env['api_key']}/featurestates/?feature={self.feature_id}"))
                          if st.get("feature_segment") is None and st.get("identity") is None)

    def get(self, path):
        return http(FLAGSMITH, "GET", path, token=self.token)[1]

    @property
    def level(self) -> int:
        return int(self.get(f"/environments/{self.env['api_key']}/featurestates/{self.state['id']}/")["feature_state_value"])

    def set_level(self, level: int) -> None:
        s, _, _ = http(FLAGSMITH, "PUT", f"/environments/{self.env['api_key']}/featurestates/{self.state['id']}/",
                       {"feature": self.feature_id, "environment": self.env["id"], "enabled": True, "feature_state_value": level},
                       token=self.token)
        if s != 200:
            raise SystemExit(f"Could not set tatkal_level to {level} (HTTP {s})")


def wait_for_level(api: str, level: int, timeout: float = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s, body, _ = http(api, "GET", f"/config?date={NORMAL_DATE}", user="sim-probe")
        if s == 200 and body.get("tatkal_level") == level:
            return True
        time.sleep(2)
    return False


def run_degradation(api: str, n: int, tag: str, levels: list[int]) -> dict:
    """Real system behaviour at each Tatkal level, for urgent and non-urgent travellers."""
    fs = Flagsmith()
    original = fs.level
    report: dict = {}
    rows = []
    try:
        for level in levels:
            fs.set_level(level)
            if not wait_for_level(api, level):
                print(f"  (the app did not report level {level} within 45 s; skipping it)")
                continue
            for group, date in (("urgent (27 Nov)", URGENT_DATE), ("normal (30 Nov)", NORMAL_DATE)):
                def one(i: int):
                    uid = f"sim-{'urg' if date == URGENT_DATE else 'nrm'}-{tag}-L{level}-{i}"
                    s, body, ms = http(api, "GET", f"/search?origin={ROUTE['origin']}&dest={ROUTE['dest']}&date={date}", user=uid)
                    m_status, m_body, _ = http(api, "POST", "/match", {"user_id": uid, **ROUTE, "date": date, **EVENING}, user=uid) \
                        if i % 3 == 0 else (None, None, 0)
                    return s, body or {}, ms, m_status, m_body or {}
                with ThreadPoolExecutor(max_workers=8) as pool:
                    out = list(pool.map(one, range(n)))
                lat = [ms for s, _, ms, _, _ in out if s == 200]
                served = [b.get("served_from") for s, b, *_ in out if s == 200]
                seen = {b.get("tatkal_level") for s, b, *_ in out if s == 200}
                errors = sum(1 for s, *_ in out if s >= 500)
                matches = [mb for _, _, _, ms_, mb in out if ms_ == 200]
                row = {
                    "requests": len(out), "errors_5xx": errors,
                    "p50_ms": round(statistics.median(lat), 1) if lat else None, "p95_ms": round(pct(lat, 95), 1) if lat else None,
                    "cache_share": round(served.count("cache") / len(served), 2) if served else None,
                    "level_seen": sorted(x for x in seen if x is not None),
                    "matching_paused": f"{sum(1 for m in matches if m.get('paused'))}/{len(matches)}",
                }
                report[f"L{level} {group}"] = row
                rows.append([f"L{level}", group, row["requests"], row["errors_5xx"], row["p50_ms"], row["p95_ms"],
                             f"{int((row['cache_share'] or 0) * 100)}%", row["level_seen"], row["matching_paused"]])
    finally:
        fs.set_level(original)
        print(f"\n  tatkal_level restored to {original}.")
    table("Experiment A: Tatkal degradation, measured on this machine (urgent travellers should stay at level 0)",
          ["set", "traffic", "reqs", "5xx", "p50 ms", "p95 ms", "cache", "level seen", "matching paused"], rows)
    return report


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic-visitor run of the GharChalo experiments.")
    ap.add_argument("--base", default="http://localhost:8000", help="GharChalo API (default %(default)s)")
    ap.add_argument("--visitors", type=int, default=300, help="synthetic visitors per experiment (default %(default)s)")
    ap.add_argument("--per-group", type=int, default=60, help="searches per level and traffic group (default %(default)s)")
    ap.add_argument("--scenario", choices=["all", "distance", "matching", "degradation"], default="all")
    ap.add_argument("--seed", type=int, default=int(time.time()) % 100000, help="random seed (printed, so a run can be repeated)")
    args = ap.parse_args()

    api = args.base.rstrip("/")
    if http(api, "GET", "/healthz")[0] != 200:
        print(f"Cannot reach the GharChalo API at {api}. Start it first.", file=sys.stderr)
        return 1
    rng, tag = random.Random(args.seed), str(args.seed)
    print(f"Synthetic run, seed {args.seed}. Visitors are labelled sim-*; choices are variant-independent.")

    report: dict = {"seed": args.seed, "model": {"select_probability": SELECT_PROBABILITY, "accept_probability": ACCEPT_PROBABILITY}}
    if args.scenario in ("all", "distance"):
        report["distance"] = run_distance(api, args.visitors, rng, tag)
    if args.scenario in ("all", "matching"):
        report["matching"] = run_matching(api, args.visitors, rng, tag)
    if args.scenario in ("all", "degradation"):
        report["degradation"] = run_degradation(api, args.per_group, tag, [0, 1, 3])

    (HERE / "last-run.json").write_text(json.dumps(report, indent=2, default=str))
    s, summary, _ = http(api, "GET", "/experiments/summary?source=simulated")
    if s == 200:
        print("\nWhat the app's own read-out now reports for the simulated visitors:")
        print(json.dumps({k: summary[k] for k in ("visitors", "population", "station_distance", "matching")}, indent=2))
    print("\nDone. This was synthetic traffic: label it 'simulated', never as results about real travellers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
