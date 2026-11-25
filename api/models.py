"""Tables. Everything here is SIMULATED data (see seed.py); never real availability."""

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Time, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(40), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(default=False)  # the city's main station


class Service(Base):
    """One bookable option on one date: a train class or a bus."""

    __tablename__ = "services"
    __table_args__ = (Index("ix_services_route_date", "origin_code", "dest_code", "depart_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(8))  # "train" | "bus"
    number: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(80))
    operator: Mapped[str] = mapped_column(String(60))
    travel_class: Mapped[str] = mapped_column(String(16))  # SL, 3A, "AC Sleeper"...
    origin_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    dest_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    depart_at: Mapped[dt.datetime] = mapped_column(DateTime)  # local time, no tz
    arrive_at: Mapped[dt.datetime] = mapped_column(DateTime)
    fare: Mapped[int] = mapped_column(Integer)  # INR, an estimate
    seats_total: Mapped[int] = mapped_column(Integer)
    seats_available: Mapped[int] = mapped_column(Integer)
    waitlist: Mapped[int] = mapped_column(Integer, default=0)  # only meaningful when seats_available == 0


class Traveller(Base):
    """A fake user looking for co-travellers (shared cab)."""

    __tablename__ = "travellers"
    __table_args__ = (Index("ix_travellers_route_date", "origin_code", "dest_code", "travel_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(40))
    origin_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    dest_code: Mapped[str] = mapped_column(ForeignKey("stations.code"))
    travel_date: Mapped[dt.date] = mapped_column(Date)
    window_start: Mapped[dt.time] = mapped_column(Time)
    window_end: Mapped[dt.time] = mapped_column(Time)


class MatchEvent(Base):
    """Experiment log: what we offered and whether it was accepted."""

    __tablename__ = "match_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)  # browser-generated UUID
    strategy: Mapped[str] = mapped_column(String(24))
    offered: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC).replace(tzinfo=None)
    )


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class SearchEvent(Base):
    """Experiment B log: one row per search where the preferred station had no train seats
    (the only case where nearby-station alternatives are shown)."""

    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    cohort_km: Mapped[int] = mapped_column(Integer, index=True)
    origin_code: Mapped[str] = mapped_column(String(8))
    dest_code: Mapped[str] = mapped_column(String(8))
    travel_date: Mapped[dt.date] = mapped_column(Date)
    alternatives_shown: Mapped[int] = mapped_column(Integer)
    beyond_limit: Mapped[int] = mapped_column(Integer)
    tatkal_level: Mapped[int] = mapped_column(Integer, default=0)
    urgent: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class AlternativeSelection(Base):
    """Experiment B log: the user picked a train from a nearby station."""

    __tablename__ = "alternative_selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_event_id: Mapped[int] = mapped_column(ForeignKey("search_events.id"), index=True)
    service_id: Mapped[int] = mapped_column(Integer)
    station_code: Mapped[str] = mapped_column(String(8))
    extra_km: Mapped[float] = mapped_column(Float)  # preferred station -> chosen station
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
