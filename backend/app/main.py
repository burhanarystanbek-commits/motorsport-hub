import threading
from datetime import timezone

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select

from . import config
from .db import init_db, make_engine, make_session_factory
from .models import (Championship, DataSource, Driver, Event, Season,
                     StandingEntry, Team)
from .refresh import RefreshInProgress, is_stale, refresh_all, utcnow
from .registry import get_adapters

engine = make_engine()
init_db(engine)
SessionLocal = make_session_factory(engine)
app = FastAPI(title="Motorsport Hub API")


def _iso(d):
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@app.on_event("startup")
def refresh_if_stale():
    """Refresh on app start when cache is older than STALE_AFTER_HOURS (background thread)."""
    def run():
        try:
            refresh_all(SessionLocal, get_adapters(), config.season())
        except RefreshInProgress:
            pass
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/status")
def status():
    with SessionLocal() as db:
        now = utcnow()
        return [{"source": d.slug, "championship": d.championship_slug,
                 "last_success_at": _iso(d.last_success_at), "last_attempt_at": _iso(d.last_attempt_at),
                 "last_error": d.last_error, "stale": is_stale(d, now),
                 "possibly_outdated": d.last_error is not None}
                for d in db.scalars(select(DataSource))]


@app.post("/api/refresh")
def refresh(force: bool = True):
    try:
        reports = refresh_all(SessionLocal, get_adapters(), config.season(), force=force)
    except RefreshInProgress:
        raise HTTPException(409, "A refresh is already running")
    return [r.__dict__ for r in reports]


@app.get("/api/championships")
def championships():
    with SessionLocal() as db:
        return [{"slug": c.slug, "name": c.name, "category": c.category, "official_url": c.official_url}
                for c in db.scalars(select(Championship))]


@app.get("/api/events")
def events(championship: str | None = None, year: int | None = None):
    with SessionLocal() as db:
        q = (select(Event, Season, Championship).join(Season, Event.season_id == Season.id)
             .join(Championship, Season.championship_id == Championship.id).order_by(Event.start_date))
        if championship:
            q = q.where(Championship.slug == championship)
        if year:
            q = q.where(Season.year == year)
        return [{"championship": c.slug, "year": s.year, "round": e.round, "name": e.name,
                 "start_date": e.start_date, "end_date": e.end_date, "retrieved_at": _iso(e.retrieved_at),
                 "sessions": [{"kind": x.kind, "starts_at_utc": _iso(x.starts_at)} for x in e.sessions]}
                for e, s, c in db.execute(q)]


@app.get("/api/standings/{championship}/{year}")
def standings(championship: str, year: int, kind: str = Query("driver")):
    with SessionLocal() as db:
        rows = db.execute(
            select(StandingEntry, Driver, Team).join(Season, StandingEntry.season_id == Season.id)
            .join(Championship, Season.championship_id == Championship.id)
            .outerjoin(Driver, StandingEntry.driver_id == Driver.id)
            .outerjoin(Team, StandingEntry.team_id == Team.id)
            .where(Championship.slug == championship, Season.year == year, StandingEntry.kind == kind)
            .order_by(StandingEntry.position)).all()
        if not rows:
            return {"available": False, "message": "No standings published for this season yet.", "rows": []}
        s0 = rows[0][0]
        ds = db.scalar(select(DataSource).where(DataSource.championship_slug == championship))
        return {"available": True, "after_round": s0.after_round, "retrieved_at": _iso(s0.retrieved_at),
                "source_updated_at": _iso(s0.source_updated_at),
                "possibly_outdated": bool(ds and ds.last_error),
                "rows": [{"position": s.position, "points": s.points, "wins": s.wins,
                          "driver": d.name if d else None, "team": t.name if t else None,
                          "nationality": d.nationality if d else (t.nationality if t else None)}
                         for s, d, t in rows]}
