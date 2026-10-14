"""Normalized data model.

Every sourced record keeps (source, source_key) and retrieved_at. Series-specific
rules live in Championship.rules (JSON) so a new series needs data, not schema
changes. Entry/EntryDriver/class_name exist for endurance + GT (several drivers
per car, classes); the F1 adapter does not use them yet. NewsArticle is schema only.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Championship(Base):
    __tablename__ = "championship"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))  # open-wheel | endurance | touring
    official_url: Mapped[str | None] = mapped_column(String(200))
    accent_color: Mapped[str | None] = mapped_column(String(9))
    rules: Mapped[dict] = mapped_column(JSON, default=dict)


class Season(Base):
    __tablename__ = "season"
    __table_args__ = (UniqueConstraint("championship_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    championship_id: Mapped[int] = mapped_column(ForeignKey("championship.id"))
    year: Mapped[int] = mapped_column(Integer)


class Circuit(Base):
    __tablename__ = "circuit"
    __table_args__ = (UniqueConstraint("source", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(120))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    name: Mapped[str] = mapped_column(String(160))
    locality: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(80))


class Event(Base):
    __tablename__ = "event"
    __table_args__ = (UniqueConstraint("season_id", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(120))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    circuit_id: Mapped[int | None] = mapped_column(ForeignKey("circuit.id"))
    round: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(160))
    start_date: Mapped[str] = mapped_column(String(10))  # ISO date
    end_date: Mapped[str] = mapped_column(String(10))
    sessions: Mapped[list["Session"]] = relationship(cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "session"
    __table_args__ = (UniqueConstraint("event_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id"))
    kind: Mapped[str] = mapped_column(String(30))  # fp1 fp2 fp3 qualifying sprint_qualifying sprint race
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # UTC; None = time unpublished


class Driver(Base):
    __tablename__ = "driver"
    __table_args__ = (UniqueConstraint("source", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(120))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str | None] = mapped_column(String(8))
    nationality: Mapped[str | None] = mapped_column(String(60))


class Team(Base):
    """Teams, constructors and manufacturers (kind says which)."""
    __tablename__ = "team"
    __table_args__ = (UniqueConstraint("source", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    source_key: Mapped[str] = mapped_column(String(120))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    name: Mapped[str] = mapped_column(String(160))
    nationality: Mapped[str | None] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(20), default="constructor")


class Entry(Base):
    """A car entered in a season (endurance/GT): number, team, class."""
    __tablename__ = "entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    car_number: Mapped[str | None] = mapped_column(String(8))
    class_name: Mapped[str | None] = mapped_column(String(40))


class EntryDriver(Base):
    __tablename__ = "entry_driver"
    __table_args__ = (UniqueConstraint("entry_id", "driver_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entry.id"))
    driver_id: Mapped[int] = mapped_column(ForeignKey("driver.id"))


class SessionResult(Base):
    __tablename__ = "session_result"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("session.id"))
    position: Mapped[int | None] = mapped_column(Integer)  # None = not classified
    status: Mapped[str] = mapped_column(String(60))
    car_number: Mapped[str | None] = mapped_column(String(8))
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("driver.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    class_name: Mapped[str | None] = mapped_column(String(40))
    grid: Mapped[int | None] = mapped_column(Integer)
    laps: Mapped[int | None] = mapped_column(Integer)
    time_text: Mapped[str | None] = mapped_column(String(30))
    points: Mapped[float] = mapped_column(Float, default=0)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StandingEntry(Base):
    """One row of a standings table. kind: driver | constructor | team | manufacturer."""
    __tablename__ = "standing_entry"
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("season.id"))
    kind: Mapped[str] = mapped_column(String(20))
    class_name: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float)
    wins: Mapped[int | None] = mapped_column(Integer)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("driver.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    after_round: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # publisher's own timestamp
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsArticle(Base):
    __tablename__ = "news_article"
    __table_args__ = (UniqueConstraint("url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    championship_id: Mapped[int | None] = mapped_column(ForeignKey("championship.id"))
    headline: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSource(Base):
    __tablename__ = "data_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    championship_slug: Mapped[str] = mapped_column(String(40))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class SyncLog(Base):
    __tablename__ = "sync_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_slug: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20))  # ok | error | skipped
    message: Mapped[str | None] = mapped_column(Text)
    counts: Mapped[dict | None] = mapped_column(JSON)
