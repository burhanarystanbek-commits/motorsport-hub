"""Refresh orchestration: staleness, one-refresh-at-a-time, per-source isolation,
validate-then-replace. A failing source never touches existing valid data."""
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from . import config
from .adapters.base import Bundle, SourceAdapter
from .models import (Championship, Circuit, DataSource, Driver, Event, Season,
                     Session, SessionResult, StandingEntry, SyncLog, Team, utcnow)

_lock = threading.Lock()


class RefreshInProgress(Exception):
    pass


@dataclass
class Report:
    source: str
    status: str  # ok | error | skipped
    message: str | None = None
    counts: dict | None = None


def is_stale(ds: DataSource | None, now: datetime, hours: float | None = None) -> bool:
    hours = config.STALE_AFTER_HOURS if hours is None else hours
    if ds is None or ds.last_success_at is None:
        return True
    last = ds.last_success_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last > timedelta(hours=hours)


def _get_or_create(db, model, defaults=None, **keys):
    obj = db.scalar(select(model).filter_by(**keys))
    if obj is None:
        obj = model(**keys, **(defaults or {}))
        db.add(obj)
        db.flush()
    return obj


def _persist(db, ad: SourceAdapter, b: Bundle, now: datetime) -> dict:
    champ = _get_or_create(db, Championship, dict(name=ad.championship_name, category=ad.category,
                                                  official_url=ad.official_url), slug=ad.championship_slug)
    season = _get_or_create(db, Season, championship_id=champ.id, year=b.year)

    def team(t):
        if t is None:
            return None
        o = _get_or_create(db, Team, dict(name=t.name, nationality=t.nationality, kind=t.kind),
                           source=ad.slug, source_key=t.key)
        o.name, o.retrieved_at = t.name, now  # team names change: keep the latest
        return o

    def driver(d):
        if d is None:
            return None
        o = _get_or_create(db, Driver, dict(name=d.name), source=ad.slug, source_key=d.key)
        o.name, o.code, o.nationality, o.retrieved_at = d.name, d.code, d.nationality, now
        return o

    sessions = {}
    for e in b.events:
        c = _get_or_create(db, Circuit, dict(name=e.circuit_name), source=ad.slug, source_key=e.circuit_key)
        c.name, c.locality, c.country, c.retrieved_at = e.circuit_name, e.locality, e.country, now
        ev = _get_or_create(db, Event, dict(source=ad.slug, round=e.round, name=e.name,
                                            start_date=str(e.start_date), end_date=str(e.end_date)),
                            season_id=season.id, source_key=e.key)
        ev.circuit_id, ev.round, ev.name, ev.retrieved_at = c.id, e.round, e.name, now
        ev.start_date, ev.end_date = str(e.start_date), str(e.end_date)
        for s in e.sessions:
            so = _get_or_create(db, Session, event_id=ev.id, kind=s.kind)
            so.starts_at = s.starts_at
            sessions[(e.key, s.kind)] = so

    # Replace-in-place only after everything above validated and flushed.
    if b.standings:
        db.execute(delete(StandingEntry).where(StandingEntry.season_id == season.id))
        for s in b.standings:
            d, t = driver(s.driver), team(s.team)
            db.add(StandingEntry(season_id=season.id, kind=s.kind, class_name=s.class_name,
                                 position=s.position, points=s.points, wins=s.wins,
                                 driver_id=d.id if d else None, team_id=t.id if t else None,
                                 after_round=b.standings_after_round, source=ad.slug,
                                 source_updated_at=b.source_updated_at, retrieved_at=now))
    touched = {k: v for k, v in sessions.items() if any(r.event_key == k[0] and r.session_kind == k[1] for r in b.results)}
    for so in touched.values():
        db.execute(delete(SessionResult).where(SessionResult.session_id == so.id))
    for r in b.results:
        so = sessions.get((r.event_key, r.session_kind))
        if so is None:
            continue
        d, t = driver(r.driver), team(r.team)
        db.add(SessionResult(session_id=so.id, position=r.position, status=r.status,
                             car_number=r.car_number, class_name=r.class_name, grid=r.grid, laps=r.laps,
                             time_text=r.time_text, points=r.points, retrieved_at=now,
                             driver_id=d.id if d else None, team_id=t.id if t else None))
    return {"events": len(b.events), "standings": len(b.standings), "results": len(b.results)}


def refresh_all(session_factory, adapters, year: int, force: bool = False,
                now: datetime | None = None) -> list[Report]:
    if not _lock.acquire(blocking=False):
        raise RefreshInProgress()
    try:
        reports = []
        for ad in adapters:  # one source failing never stops the others
            now_ = now or utcnow()
            with session_factory() as db:
                ds = _get_or_create(db, DataSource, dict(championship_slug=ad.championship_slug), slug=ad.slug)
                if not force and not is_stale(ds, now_):
                    reports.append(Report(ad.slug, "skipped", "cache is fresh"))
                    db.commit()
                    continue
                ds.last_attempt_at = now_
                db.commit()
                try:
                    bundle = ad.fetch(year)
                    if not bundle.events and not bundle.standings:
                        raise ValueError("source returned no events and no standings")
                    prev = db.scalar(select(Event.id).join(Season).join(Championship)
                                     .where(Championship.slug == ad.championship_slug, Season.year == year).limit(1))
                    if prev and not bundle.events:
                        raise ValueError("source returned no events but we already have some")
                    counts = _persist(db, ad, bundle, now_)
                    ds.last_success_at, ds.last_error = now_, None
                    db.add(SyncLog(source_slug=ad.slug, status="ok", counts=counts, started_at=now_))
                    db.commit()
                    reports.append(Report(ad.slug, "ok", counts=counts))
                except Exception as e:  # keep last valid data; record why
                    db.rollback()
                    ds = db.scalar(select(DataSource).where(DataSource.slug == ad.slug))
                    ds.last_error = f"{type(e).__name__}: {e}"
                    db.add(SyncLog(source_slug=ad.slug, status="error", message=ds.last_error, started_at=now_))
                    db.commit()
                    reports.append(Report(ad.slug, "error", ds.last_error))
        return reports
    finally:
        _lock.release()
