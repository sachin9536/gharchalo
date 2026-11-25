"""Seed the database with SIMULATED trains, buses and travellers.

    cd api && .venv/bin/python seed.py        # DROPS and recreates all tables

Deterministic: the same arguments always produce the same rows, so a storm run
or a demo can be repeated exactly.

The scripted demo (Bengaluru -> Hyderabad on DEMO_DATE):
  * every train is full or waitlisted, including all from the main station SBC;
  * the only trains with seats leave from alternative stations at ~4, ~11 and
    ~28 km from SBC, so the 5 / 15 / 30 km cohorts are offered 1 / 2 / 3 of them;
  * a bus from SBC has seats (the "any option" fallback);
  * 3 travellers share the evening on the same route and day, but from three different Bengaluru
    stations, so only one is at the main station: "exact" (your station) finds 1, and the flexible
    strategy (nearby stations, +/- a day, a wider window) finds 6 with their distance and delay measured.
"""

import datetime as dt
import random
from collections import defaultdict

from sqlalchemy import Engine
from sqlalchemy.orm import Session

import models
from geo import haversine_km
from seed_data import (
    BUS_OPERATORS,
    CITY_PAIRS,
    DEFAULT_DAYS,
    DEFAULT_START_DATE,
    DEMO_DATE,
    FIRST_NAMES,
    STATIONS,
    TRAIN_KINDS,
)

N_TRAVELLERS = 300
SERVICES_PER_DIRECTION = 3  # trains, and separately buses, per route direction per day
# (class, seats, INR per km, minimum fare): rough estimates, not real tariffs.
TRAIN_CLASSES = (("SL", 72, 0.55, 150), ("3A", 64, 1.45, 450))
BUS_CLASS = ("AC Sleeper", 36, 2.0, 400)

_BY_CODE = {s.code: s for s in STATIONS}
_BY_CITY: dict[str, list] = defaultdict(list)
for _s in STATIONS:
    _BY_CITY[_s.city].append(_s)
_PRIMARY = {city: next(s for s in group if s.is_primary) for city, group in _BY_CITY.items()}


def _round5(value: float) -> int:
    return int(round(value / 5) * 5)


def _km(origin_city: str, dest_city: str) -> float:
    a, b = _PRIMARY[origin_city], _PRIMARY[dest_city]
    return haversine_km((a.lat, a.lon), (b.lat, b.lon))


def _pick_station(rng: random.Random, city: str, primary_weight: float):
    group = _BY_CITY[city]
    others = [s for s in group if not s.is_primary]
    if others and rng.random() > primary_weight:
        return rng.choice(others)
    return _PRIMARY[city]


def _availability(rng: random.Random, total: int, p_full: float) -> tuple[int, int]:
    """(seats_available, waitlist). Festive season: most trains are sold out."""
    if rng.random() < p_full:
        return 0, rng.randint(3, 120)
    return rng.randint(1, min(30, total)), 0


def _fare(km: float, per_km: float, minimum: int) -> int:
    return max(minimum, _round5(km * per_km))


def _build_templates(rng: random.Random) -> list[dict]:
    """Recurring services: the same train/bus runs every day on its route."""
    templates, numbers = [], set()
    for a, b in CITY_PAIRS:
        for origin_city, dest_city in ((a, b), (b, a)):
            km = _km(origin_city, dest_city)
            for _ in range(SERVICES_PER_DIRECTION):
                number = f"9{rng.randint(1000, 9999)}"
                while number in numbers:
                    number = f"9{rng.randint(1000, 9999)}"
                numbers.add(number)
                templates.append(
                    {
                        "mode": "train",
                        "number": number,
                        "name": f"{origin_city}-{dest_city} {rng.choice(TRAIN_KINDS)}",
                        "operator": "Simulated Railways",
                        "origin": _pick_station(rng, origin_city, 0.7),
                        "dest": _pick_station(rng, dest_city, 0.7),
                        "depart": dt.time(rng.choice([5, 6, 16, 18, 19, 20, 21, 22, 23]), rng.choice([0, 15, 30, 45])),
                        "hours": km * 1.25 / 58 + 0.5,
                        "classes": [(c, total, _fare(km * 1.25, per_km, minimum), 0.55) for c, total, per_km, minimum in TRAIN_CLASSES],
                    }
                )
            if km * 1.2 <= 1100:  # nobody takes a bus Bengaluru -> Delhi
                for _ in range(SERVICES_PER_DIRECTION):
                    cls, total, per_km, minimum = BUS_CLASS
                    templates.append(
                        {
                            "mode": "bus",
                            "number": f"B{rng.randint(1000, 8999)}",
                            "name": f"{origin_city} to {dest_city} AC Sleeper",
                            "operator": rng.choice(BUS_OPERATORS),
                            "origin": _pick_station(rng, origin_city, 0.8),
                            "dest": _pick_station(rng, dest_city, 0.8),
                            "depart": dt.time(rng.choice([18, 19, 20, 21, 22]), rng.choice([0, 30])),
                            "hours": km * 1.2 / 48 + 0.5,
                            "classes": [(cls, total, _fare(km * 1.2, per_km, minimum), 0.2)],
                        }
                    )
    return templates


def _service_rows(rng: random.Random, dates: list[dt.date]) -> list[dict]:
    rows = []
    templates = _build_templates(rng)
    for date in dates:
        for t in templates:
            depart = dt.datetime.combine(date, t["depart"])
            arrive = depart + dt.timedelta(hours=t["hours"])
            for cls, total, fare, p_full in t["classes"]:
                seats, waitlist = _availability(rng, total, p_full)
                rows.append(
                    dict(
                        mode=t["mode"], number=t["number"], name=t["name"], operator=t["operator"],
                        travel_class=cls, origin_code=t["origin"].code, dest_code=t["dest"].code,
                        depart_at=depart, arrive_at=arrive, fare=fare,
                        seats_total=total, seats_available=seats, waitlist=waitlist,
                    )
                )
    return rows


def _apply_demo_services(rng: random.Random, rows: list[dict]) -> list[dict]:
    # 1. Every Bengaluru -> Hyderabad train on the demo date is sold out.
    for r in rows:
        if (
            r["mode"] == "train"
            and r["depart_at"].date() == DEMO_DATE
            and _BY_CODE[r["origin_code"]].city == "Bengaluru"
            and _BY_CODE[r["dest_code"]].city == "Hyderabad"
        ):
            r["seats_available"], r["waitlist"] = 0, rng.randint(30, 140)

    # 2. ...except three scripted trains from stations ~4, ~11 and ~28 km away, and one bus.
    def at(h, m):
        return dt.datetime.combine(DEMO_DATE, dt.time(h, m))

    def svc(mode, number, name, operator, cls, origin, dest, depart, hours, fare, total, seats):
        return dict(
            mode=mode, number=number, name=name, operator=operator, travel_class=cls,
            origin_code=origin, dest_code=dest, depart_at=depart,
            arrive_at=depart + dt.timedelta(hours=hours), fare=fare,
            seats_total=total, seats_available=seats, waitlist=0,
        )

    rows += [
        svc("train", "99101", "Cantonment-Hyderabad Festival Special", "Simulated Railways", "3A", "BNC", "HYB", at(21, 40), 11.5, 1450, 64, 14),
        svc("train", "99102", "Baiyappanahalli-Secunderabad Festival Special", "Simulated Railways", "SL", "SMVB", "SC", at(19, 15), 12.5, 465, 72, 9),
        svc("train", "99103", "Bidadi-Kacheguda Festival Special", "Simulated Railways", "SL", "BID", "KCG", at(18, 30), 13.0, 440, 72, 6),
        svc("bus", "B9001", "Bengaluru to Hyderabad AC Sleeper", "Safar Lines", "AC Sleeper", "SBC", "HYB", at(21, 0), 11.0, 1450, 36, 11),
    ]
    return rows


def _traveller_rows(rng: random.Random, dates: list[dt.date]) -> list[dict]:
    rows: list[dict] = []

    def add(origin: str, dest: str, date: dt.date, start: dt.time, end: dt.time):
        n = len(rows) + 1
        rows.append(
            dict(
                user_id=f"u{n:03d}", name=rng.choice(FIRST_NAMES), origin_code=origin,
                dest_code=dest, travel_date=date, window_start=start, window_end=end,
            )
        )

    t = dt.time
    one_day = dt.timedelta(days=1)
    # The same evening on the demo date from three different stations: only u001 is at SBC (exact fit).
    add("SBC", "HYB", DEMO_DATE, t(17), t(21))
    add("YPR", "KCG", DEMO_DATE, t(18), t(22))
    add("BNC", "HYB", DEMO_DATE, t(19), t(23))
    # Near misses: only the flexible strategy (+/- a day, wider window) finds these.
    add("SBC", "SC", DEMO_DATE, t(6), t(9))
    add("SBC", "HYB", DEMO_DATE - one_day, t(18), t(22))
    add("YPR", "HYB", DEMO_DATE + one_day, t(18), t(22))
    add("SMVB", "HYB", DEMO_DATE, t(23), t(23, 59))

    directed = [pair for a, b in CITY_PAIRS for pair in ((a, b), (b, a))]
    while len(rows) < N_TRAVELLERS:
        origin_city, dest_city = rng.choice(directed)
        date = rng.choice(dates)
        # Keep the scripted demo's counts exact: no random Bengaluru->Hyderabad nearby.
        if origin_city == "Bengaluru" and dest_city == "Hyderabad" and abs((date - DEMO_DATE).days) <= 1:
            continue
        start_hour = rng.randint(5, 20)
        end_hour = min(23, start_hour + rng.randint(3, 5))
        add(
            _pick_station(rng, origin_city, 0.6).code,
            _pick_station(rng, dest_city, 0.6).code,
            date,
            t(start_hour),
            t(end_hour, 59 if end_hour == 23 else 0),
        )
    return rows


def seed(
    engine: Engine,
    *,
    start: dt.date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS,
    rng_seed: int = 42,
) -> dict[str, int]:
    """Drop and recreate all tables, then fill them. Returns row counts."""
    dates = [start + dt.timedelta(days=i) for i in range(days)]
    if DEMO_DATE not in dates:
        raise ValueError(f"demo date {DEMO_DATE} must fall inside the seeded range {dates[0]}..{dates[-1]}")

    rng = random.Random(rng_seed)
    services = _apply_demo_services(rng, _service_rows(rng, dates))
    travellers = _traveller_rows(rng, dates)

    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            models.Station(code=s.code, name=s.name, city=s.city, lat=s.lat, lon=s.lon, is_primary=s.is_primary)
            for s in STATIONS
        )
        session.flush()  # stations first: services/travellers reference them
        session.add_all(models.Service(**r) for r in services)
        session.add_all(models.Traveller(**r) for r in travellers)
        session.commit()

    return {
        "stations": len(STATIONS),
        "trains": sum(r["mode"] == "train" for r in services),
        "buses": sum(r["mode"] == "bus" for r in services),
        "travellers": len(travellers),
    }


def is_seeded(engine: Engine) -> bool:
    """True if the stations table exists and has rows."""
    from sqlalchemy import func, inspect, select

    if not inspect(engine).has_table(models.Station.__tablename__):
        return False
    with Session(engine) as session:
        return bool(session.scalar(select(func.count()).select_from(models.Station)))


def wait_for_database(engine: Engine, timeout_seconds: float) -> None:
    """Containers start in any order: retry until the database accepts connections."""
    import time

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
            return
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            print("  database not ready yet, retrying...")
            time.sleep(2)


if __name__ == "__main__":
    import argparse

    import db

    parser = argparse.ArgumentParser(description="Seed GharChalo's simulated data.")
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="Do nothing if data already exists (safe for container restarts). Without it, tables are dropped.",
    )
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDS", help="Wait up to this long for the database.")
    args = parser.parse_args()

    url = db.engine.url.render_as_string(hide_password=True)
    if args.wait:
        wait_for_database(db.engine, args.wait)
    if args.if_empty and is_seeded(db.engine):
        print(f"{url} already has data; not reseeding.")
    else:
        print(f"Seeding {url} (drops existing tables)...")
        print(seed(db.engine))
