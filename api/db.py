from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

import config


def make_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    if url.startswith("sqlite"):
        # Local dev without Docker: DATABASE_URL=sqlite:///gharchalo.db
        # FastAPI runs sync routes in a thread pool, so allow cross-thread use.
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        pool_timeout=config.DB_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )


engine = make_engine()  # lazy: does not connect until first use


def get_session():
    """FastAPI dependency."""
    with Session(engine) as session:
        yield session


# Columns added to existing tables after the first release. create_all() never alters a table
# that already exists, so a database created earlier is topped up here instead of being reseeded
# (which would wipe the experiment events).
_ADDED_COLUMNS = {
    "match_events": [
        ("avg_pickup_km", "FLOAT"),
        ("avg_day_shift", "FLOAT"),
        ("avg_time_gap_min", "FLOAT"),
        ("group_size", "INTEGER"),
    ],
}


def ensure_columns(target: Engine | None = None) -> list[str]:
    """Add any missing columns listed above. Returns what it added. Safe to run on every start."""
    from sqlalchemy import inspect, text

    target = target or engine
    added: list[str] = []
    inspector = inspect(target)
    for table, columns in _ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # a fresh database: seed.py creates the table with every column
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, sql_type in columns:
            if name not in have:
                with target.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                added.append(f"{table}.{name}")
    return added
