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
