import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from . import config
from .db import init_db, make_engine, make_session_factory
from .adapters.base import SourceError
from .live.service import LiveTimingService
from .models import (Championship, DataSource, Driver, Event, Season, Session,
                     SessionResult, StandingEntry, Team)
from .refresh import RefreshInProgress, is_stale, refresh_all, utcnow
from .registry import get_adapters

engine = make_engine()
init_db(engine)
SessionLocal = make_session_factory(engine)
@asynccontextmanager
async def lifespan(_app):
    refresh_if_stale()
    yield


app = FastAPI(title="Motorsport Hub API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["*"])
live = LiveTimingService()
LIVE_SERIES = {"f1"}  # live timing exists only for F1 (OpenF1) for now


def _iso(d):
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


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


def _event_q(db, championship: str, year: int, rnd: int):
    return db.execute(select(Event, Season, Championship).join(Season, Event.season_id == Season.id)
                      .join(Championship, Season.championship_id == Championship.id)
                      .where(Championship.slug == championship, Season.year == year, Event.round == rnd)).first()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/events/{championship}/{year}/{rnd}")
def event_detail(championship: str, year: int, rnd: int):
    """One round with every session and its classified results (race, sprint, qualifying)."""
    with SessionLocal() as db:
        row = _event_q(db, championship, year, rnd)
        if not row:
            raise HTTPException(404, "Event not found")
        e, s, c = row
        sessions = []
        for so in sorted(e.sessions, key=lambda x: (x.starts_at is None, x.starts_at or 0)):
            res = db.execute(select(SessionResult, Driver, Team)
                             .outerjoin(Driver, SessionResult.driver_id == Driver.id)
                             .outerjoin(Team, SessionResult.team_id == Team.id)
                             .where(SessionResult.session_id == so.id)
                             .order_by(SessionResult.position.is_(None), SessionResult.position)).all()
            sessions.append({"kind": so.kind, "starts_at_utc": _iso(so.starts_at),
                             "results": [{"position": r.position, "status": r.status, "car_number": r.car_number,
                                          "driver": d.name if d else None, "driver_code": d.code if d else None,
                                          "team": t.name if t else None, "grid": r.grid, "laps": r.laps,
                                          "time": r.time_text, "points": r.points}
                                         for r, d, t in res]})
        return {"championship": c.slug, "year": s.year, "round": e.round, "name": e.name,
                "start_date": e.start_date, "end_date": e.end_date, "retrieved_at": _iso(e.retrieved_at),
                "live_timing_available": c.slug in LIVE_SERIES, "sessions": sessions}


@app.get("/api/results/{championship}/{year}")
def season_results(championship: str, year: int, kind: str = Query("race")):
    """Winner / pole per round for a season (kind = race | sprint | qualifying)."""
    with SessionLocal() as db:
        rows = db.execute(select(Event, SessionResult, Driver, Team)
                          .join(Season, Event.season_id == Season.id)
                          .join(Championship, Season.championship_id == Championship.id)
                          .join(Session, Session.event_id == Event.id)
                          .join(SessionResult, SessionResult.session_id == Session.id)
                          .outerjoin(Driver, SessionResult.driver_id == Driver.id)
                          .outerjoin(Team, SessionResult.team_id == Team.id)
                          .where(Championship.slug == championship, Season.year == year,
                                 Session.kind == kind, SessionResult.position == 1)
                          .order_by(Event.round)).all()
        return [{"round": e.round, "event": e.name, "driver": d.name if d else None,
                 "team": t.name if t else None, "time": r.time_text} for e, r, d, t in rows]


@app.get("/api/drivers/{championship}/{year}")
def drivers(championship: str, year: int):
    """Drivers who scored or appear in the season standings, with their current team."""
    st = standings(championship, year, "driver")
    return [{"position": r["position"], "name": r["driver"], "team": r["team"],
             "nationality": r["nationality"], "points": r["points"]} for r in st["rows"]]


# ---------------- live timing (F1 only, via OpenF1) ----------------

def _check_live(series: str):
    if series not in LIVE_SERIES:
        raise HTTPException(404, f"Live timing is not available for '{series}' (only: {sorted(LIVE_SERIES)})")


@app.get("/api/live/{series}")
def live_snapshot(series: str, session_key: str = "latest"):
    """Timing tower: position, gap to leader, interval, last/best lap + sectors, tyres, pit stops,
    race control, weather. `session_key=latest` = current/most recent session; any past key replays it."""
    _check_live(series)
    try:
        return live.snapshot(session_key)
    except LookupError as e:
        raise HTTPException(404, str(e))


@app.get("/api/live/{series}/sessions")
def live_sessions(series: str, year: int | None = None, meeting_key: int | None = None):
    _check_live(series)
    try:
        return live.sessions(year, meeting_key)
    except SourceError as e:
        raise HTTPException(502, str(e))


@app.get("/api/live/{series}/laps/{driver_number}")
def live_laps(series: str, driver_number: int, session_key: str = "latest"):
    """Every lap of one driver in the session: lap time, sectors, speed traps, pit-out laps."""
    _check_live(series)
    try:
        return live.laps(session_key, driver_number)
    except (LookupError, SourceError) as e:
        raise HTTPException(404, str(e))


@app.get("/api/live/{series}/stream")
async def live_stream(series: str, request: Request, session_key: str = "latest"):
    """Server-Sent Events: pushes a new snapshot whenever the data changes."""
    _check_live(series)

    async def gen():
        last = None
        while not await request.is_disconnected():
            try:
                snap = await run_in_threadpool(live.snapshot, session_key)
            except LookupError as e:
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                return
            body = json.dumps({k: v for k, v in snap.items() if k != "retrieved_at"}, sort_keys=True)
            if body != last:
                last = body
                yield f"data: {json.dumps(snap)}\n\n"
            else:
                yield ": keep-alive\n\n"
            if snap.get("session", {}).get("status") == "finished" and last is not None:
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(max(live.poll_seconds, 1))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
