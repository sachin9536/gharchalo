"""A deterministic benchmark of the two matching strategies.

The same fixed set of requests goes through `exact` and `time_window` (flexible) on the simulated
traveller pool. It measures the ALGORITHM, not user behaviour: how many co-travellers each
strategy finds, and what the extra ones cost (pickup distance, days away, time gap), plus what
a bigger group does to the per-person cab fare. No randomness and nothing is written, so the
numbers are reproducible and tunable: change `matching_config` in Flagsmith and re-run.

    cd api && .venv/bin/python benchmark.py            # defaults, against the configured database
"""

from __future__ import annotations

import datetime as dt
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import matching
import models
from fares import cab_per_person, cab_total_fare, road_km
from seed_data import DEMO_DATE

DEST = "HYB"
EVENING = (dt.time(18), dt.time(22))

# name, pickup station, day offset from the demo day, time window
SCENARIOS: list[tuple[str, str, int, tuple[dt.time, dt.time]]] = [
    ("Same station, same evening", "SBC", 0, EVENING),
    ("Same station, a day later", "SBC", 1, EVENING),
    ("Same station, a day earlier", "SBC", -1, EVENING),
    ("Same station, early morning", "SBC", 0, (dt.time(6), dt.time(9))),
    ("Same station, late night", "SBC", 0, (dt.time(23), dt.time(23, 59))),
    ("Pickup 4 km away (Cantonment)", "BNC", 0, EVENING),
    ("Pickup 5 km away (Yesvantpur)", "YPR", 0, EVENING),
    ("Pickup 11 km away (Baiyappanahalli)", "SMVB", 0, EVENING),
    ("Pickup 28 km away (Bidadi)", "BID", 0, EVENING),
]

ASKER = "benchmark"  # an identity that is not in the traveller pool


def _avg(values: list[float], digits: int = 1) -> float | None:
    return round(mean(values), digits) if values else None


def _fare_each(total: int, matches: int) -> int:
    group = matching.group_size(matches)
    return total if group == 1 else cab_per_person(total, group)


def matching_benchmark(session: Session, config: dict | None = None) -> dict[str, Any]:
    cfg = {**matching.DEFAULT_CONFIG, **(config or {})}
    stations = {s.code: s for s in session.scalars(select(models.Station))}
    dest = stations[DEST]
    rows, rescued, still_empty = [], 0, 0
    flex_only_all: list[matching.Candidate] = []
    savings: list[int] = []

    for name, origin, offset, (start, end) in SCENARIOS:
        day = DEMO_DATE + dt.timedelta(days=offset)
        run = lambda strategy: matching.candidates(  # noqa: E731
            session, user_id=ASKER, origin_code=origin, dest_code=DEST, date=day,
            window_start=start, window_end=end, strategy=strategy, config=cfg,
        )
        exact, flexible = run("exact"), run("time_window")
        found_by_exact = {c.traveller.id for c in exact}
        flex_only = [c for c in flexible if c.traveller.id not in found_by_exact]
        flex_only_all += flex_only

        pickup = stations[origin]
        total = cab_total_fare(road_km((pickup.lat, pickup.lon), (dest.lat, dest.lon)))
        each_exact, each_flex = _fare_each(total, len(exact)), _fare_each(total, len(flexible))
        if len(flexible) > len(exact):
            savings.append(each_exact - each_flex)
        if not exact and flexible:
            rescued += 1
        if not exact and not flexible:
            still_empty += 1

        rows.append({
            "name": name,
            "pickup": {"code": origin, "name": pickup.name},
            "date": day.isoformat(),
            "window": f"{start:%H:%M}-{end:%H:%M}",
            "exact": {"found": len(exact), "group_size": matching.group_size(len(exact)), "fare_each": each_exact},
            "flexible": {
                "found": len(flexible),
                "group_size": matching.group_size(len(flexible)),
                "fare_each": each_flex,
                "avg_pickup_km": _avg([c.pickup_km for c in flexible]),
                "avg_day_shift": _avg([abs(c.day_shift) for c in flexible], 2),
                "avg_time_gap_min": _avg([c.time_gap_min for c in flexible], 0),
            },
            "flexible_only": len(flex_only),
        })

    return {
        "source": "simulated",
        "kind": "algorithm benchmark on the simulated traveller pool (deterministic; not user behaviour)",
        "config": {k: cfg[k] for k in matching.DEFAULT_CONFIG},
        "route": f"Bengaluru -> {dest.city}",
        "scenarios": rows,
        "summary": {
            "scenarios": len(rows),
            "found_by_exact": sum(r["exact"]["found"] for r in rows),
            "found_by_flexible": sum(r["flexible"]["found"] for r in rows),
            "rescued": rescued,  # exact found nobody, flexible found someone
            "still_empty": still_empty,  # neither found anybody
            "extra_matches": len(flex_only_all),  # found only by flexible
            "extra_avg_pickup_km": _avg([c.pickup_km for c in flex_only_all]),
            "extra_avg_day_shift": _avg([abs(c.day_shift) for c in flex_only_all], 2),
            "extra_avg_time_gap_min": _avg([c.time_gap_min for c in flex_only_all], 0),
            "avg_fare_saving_each": round(mean(savings)) if savings else None,
        },
    }


if __name__ == "__main__":
    import db

    with Session(db.engine) as session:
        result = matching_benchmark(session)
    print(f"{result['kind']}\nconfig: {result['config']}\n")
    print(f"{'request':38} {'exact':>5} {'flex':>5} {'flex avg km':>11} {'avg days':>8} {'avg gap':>8} {'fare each (exact -> flex)':>26}")
    for r in result["scenarios"]:
        f = r["flexible"]
        print(
            f"{r['name']:38} {r['exact']['found']:>5} {f['found']:>5} {str(f['avg_pickup_km'] or '-'):>11} "
            f"{str(f['avg_day_shift'] if f['avg_day_shift'] is not None else '-'):>8} "
            f"{(str(int(f['avg_time_gap_min'])) + ' min') if f['avg_time_gap_min'] is not None else '-':>8} "
            f"{'Rs' + str(r['exact']['fare_each']) + ' -> Rs' + str(f['fare_each']):>26}"
        )
    s = result["summary"]
    print(f"\nflexible found {s['found_by_flexible']} vs {s['found_by_exact']} for exact across {s['scenarios']} requests; "
          f"it rescued {s['rescued']} requests where exact found nobody ({s['still_empty']} stayed empty).")
    print(f"The {s['extra_matches']} extra matches were on average {s['extra_avg_pickup_km']} km away, "
          f"{s['extra_avg_day_shift']} days off and {s['extra_avg_time_gap_min']} min apart; "
          f"bigger groups saved about Rs{s['avg_fare_saving_each']} each.")
