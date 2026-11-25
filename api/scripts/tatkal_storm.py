#!/usr/bin/env python3
"""TatkalStorm: a Tatkal-hour traffic spike against GharChalo. Standard library only.

    python scripts/tatkal_storm.py --base http://gharchalo-api:8000            # in the cluster (deploy/storm/run.sh)
    python scripts/tatkal_storm.py --base http://localhost:8000 --peak-rps 40  # against a dev server

Phases, as on a real Tatkal morning: browse (low, steady) -> spike (ramps up fast at "10:00") ->
sustain (peak) -> cooldown. The load is open-loop: requests are sent on schedule whether or not the
server keeps up, the way real users keep refreshing, so a struggling service shows up as rising
latency, errors and connection failures instead of the generator quietly slowing down.

Traffic mix: 70% search (15% of those ask for journeys with changes, the CPU-heavy planner),
20% co-traveller matching, 10% voice. Every request carries `X-Load-Test: 1`, so voice never
reaches the real Sarvam API and searches are not logged as experiment participants. Identities
start with `sim-storm-`, so any rows they write stay out of the "real visitors" read-out.

This is SIMULATED load on our own infrastructure. Never present its numbers as railway traffic.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

ROUTES = [("SBC", "HYB"), ("SBC", "JP"), ("NDLS", "KOTA"), ("MMCT", "PUNE"), ("HYB", "MMCT"), ("MAS", "SBC")]
DATES = ["2026-11-26", "2026-11-27", "2026-11-28", "2026-11-29"]
WINDOWS = [("06:00", "10:00"), ("12:00", "16:00"), ("18:00", "22:00")]
BOUNDARY = "tatkalstorm"
VOICE_BODY = (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"storm.wav\"\r\n"
              f"Content-Type: audio/wav\r\n\r\nRIFF\r\n--{BOUNDARY}--\r\n").encode()


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.by_phase: dict[str, dict] = defaultdict(lambda: {"samples": [], "sent": 0})  # samples: (status, ms)
        self.window: list[tuple[float, int, float]] = []  # (time, code, ms) for the live line

    def record(self, phase: str, code: int, ms: float) -> None:
        with self.lock:
            self.by_phase[phase]["samples"].append((code, ms))
            self.window.append((time.monotonic(), code, ms))

    def sent(self, phase: str) -> None:
        with self.lock:
            self.by_phase[phase]["sent"] += 1

    def recent(self, seconds: float = 5.0) -> tuple[int, Counter, float | None]:
        cutoff = time.monotonic() - seconds
        with self.lock:
            self.window = [w for w in self.window if w[0] >= cutoff]
            codes = Counter(_bucket(c) for _, c, _ in self.window)
            lat = [ms for _, c, ms in self.window if 200 <= c < 300]
        return len(self.window), codes, (_p95(lat) if lat else None)


def _bucket(code: int) -> str:
    if code == 0:
        return "conn-fail"
    return f"{code // 100}xx"


def _p95(values: list[float]) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def request(base: str, rng: random.Random, n: int, timeout: float) -> tuple[int, float]:
    """One user action. Returns (HTTP status, or 0 for a connection failure/timeout; latency ms)."""
    headers = {"X-Load-Test": "1", "X-User-Id": f"sim-storm-{n % 5000}"}
    roll = rng.random()
    origin, dest = rng.choice(ROUTES)
    date = rng.choice(DATES)
    if roll < 0.70:
        heavy = "true" if rng.random() < 0.15 else "false"
        req = urllib.request.Request(
            f"{base}/search?origin={origin}&dest={dest}&date={date}&include_connections={heavy}", headers=headers)
    elif roll < 0.90:
        start, end = rng.choice(WINDOWS)
        body = json.dumps({"user_id": headers["X-User-Id"], "origin": origin, "dest": dest, "date": date,
                           "window_start": start, "window_end": end}).encode()
        req = urllib.request.Request(f"{base}/match", data=body, method="POST",
                                     headers={**headers, "Content-Type": "application/json"})
    else:
        req = urllib.request.Request(f"{base}/voice", data=VOICE_BODY, method="POST",
                                     headers={**headers, "Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception:  # refused / reset / timeout: the pod is down or overwhelmed
        code = 0
    return code, (time.perf_counter() - started) * 1000


def main() -> int:
    ap = argparse.ArgumentParser(description="Tatkal-hour traffic spike against GharChalo.")
    ap.add_argument("--base", default="http://gharchalo-api:8000")
    ap.add_argument("--browse-rps", type=float, default=5)
    ap.add_argument("--peak-rps", type=float, default=60)
    ap.add_argument("--browse-s", type=int, default=30)
    ap.add_argument("--spike-s", type=int, default=10, help="ramp from browse to peak")
    ap.add_argument("--sustain-s", type=int, default=120)
    ap.add_argument("--cooldown-s", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=64, help="max requests in flight")
    ap.add_argument("--timeout", type=float, default=10)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    phases = [("browse", args.browse_s, args.browse_rps, args.browse_rps),
              ("spike", args.spike_s, args.browse_rps, args.peak_rps),
              ("sustain", args.sustain_s, args.peak_rps, args.peak_rps),
              ("cooldown", args.cooldown_s, args.browse_rps, args.browse_rps)]
    total_s = sum(p[1] for p in phases)
    print(f"TatkalStorm -> {base}  |  peak {args.peak_rps} req/s for {args.sustain_s}s  |  ~{total_s}s total  |  "
          f"SIMULATED load (X-Load-Test: 1)", flush=True)

    stats, rng, n = Stats(), random.Random(args.seed), 0
    in_flight = threading.Semaphore(args.concurrency)
    dropped = Counter()
    stop = threading.Event()

    def reporter() -> None:
        while not stop.wait(5):
            count, codes, p95 = stats.recent()
            line = " ".join(f"{k}={v}" for k, v in sorted(codes.items()))
            print(f"  [{time.strftime('%H:%M:%S')}] last 5s: {count / 5:5.1f} req/s done  {line or '-'}  "
                  f"p95(ok)={'%.0f ms' % p95 if p95 else '-'}  dropped={sum(dropped.values())}", flush=True)

    threading.Thread(target=reporter, daemon=True).start()

    def fire(phase: str, i: int, req_rng: random.Random) -> None:
        try:
            code, ms = request(base, req_rng, i, args.timeout)
            stats.record(phase, code, ms)
        finally:
            in_flight.release()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for name, seconds, rps_from, rps_to in phases:
            print(f"-- phase {name}: {seconds}s, {rps_from:g} -> {rps_to:g} req/s", flush=True)
            phase_start = time.monotonic()
            next_at = phase_start
            while (elapsed := time.monotonic() - phase_start) < seconds:
                rps = rps_from + (rps_to - rps_from) * (elapsed / seconds if seconds else 1)
                next_at += 1.0 / max(rps, 0.1)
                sleep = next_at - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
                if not in_flight.acquire(blocking=False):
                    dropped[name] += 1  # the generator itself is saturated: everything is already in flight
                    continue
                n += 1
                stats.sent(name)
                pool.submit(fire, name, n, random.Random(rng.random()))
    stop.set()

    print("\n=== TatkalStorm summary (simulated load) ===", flush=True)
    print(f"{'phase':10} {'sent':>6} {'2xx':>6} {'4xx':>5} {'5xx':>5} {'conn-fail':>9} {'p50 ms':>8} {'p95 ms':>8}")
    worst = 0.0
    for name, *_ in phases:
        p = stats.by_phase[name]
        codes = Counter(_bucket(c) for c, _ in p["samples"])
        # latency of successful requests only: failures time out and would distort it
        ok_lat = [ms for c, ms in p["samples"] if 200 <= c < 300]
        fail = codes["5xx"] + codes["conn-fail"]
        worst = max(worst, fail / max(1, p["sent"]))
        print(f"{name:10} {p['sent']:>6} {codes['2xx']:>6} {codes['4xx']:>5} {codes['5xx']:>5} {codes['conn-fail']:>9} "
              f"{(statistics.median(ok_lat) if ok_lat else 0):>8.0f} {(_p95(ok_lat) if ok_lat else 0):>8.0f}")
    if sum(dropped.values()):
        print(f"(generator saturated: {sum(dropped.values())} requests not sent because {args.concurrency} were already in flight)")
    print(f"worst phase failure rate (5xx + connection failures): {worst:.0%}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
