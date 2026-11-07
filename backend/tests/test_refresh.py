import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.adapters.base import Bundle, StandingDTO, TeamRef
from app.adapters.jolpica_f1 import JolpicaF1
from app.models import DataSource, Event, StandingEntry, SyncLog
from app.refresh import RefreshInProgress, _lock, is_stale, refresh_all
from tests.conftest import make_transport

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)


def ad(**kw):
    return JolpicaF1(transport=make_transport(**kw), pause=0)


def test_success_then_skipped_when_fresh(factory):
    assert refresh_all(factory, [ad()], 2026, now=NOW)[0].status == "ok"
    assert refresh_all(factory, [ad()], 2026, now=NOW + timedelta(hours=1))[0].status == "skipped"
    assert refresh_all(factory, [ad()], 2026, now=NOW + timedelta(hours=25))[0].status == "ok"
    with factory() as db:
        assert len(db.scalars(select(Event)).all()) == 2  # upsert, no duplicates
        assert len(db.scalars(select(StandingEntry)).all()) == 3


def test_failure_keeps_last_valid_data_and_records_error(factory):
    refresh_all(factory, [ad()], 2026, now=NOW)
    r = refresh_all(factory, [ad(fail=True)], 2026, force=True, now=NOW + timedelta(days=2))[0]
    assert r.status == "error" and "503" in r.message
    with factory() as db:
        assert len(db.scalars(select(StandingEntry)).all()) == 3  # untouched
        ds = db.scalar(select(DataSource))
        assert ds.last_error and ds.last_success_at is not None
        assert is_stale(ds, NOW + timedelta(days=2))
        assert db.scalars(select(SyncLog).where(SyncLog.status == "error")).first()


def test_empty_source_does_not_wipe_existing_events(factory):
    refresh_all(factory, [ad()], 2026, now=NOW)
    r = refresh_all(factory, [ad(empty_schedule=True)], 2026, force=True, now=NOW + timedelta(days=2))[0]
    with factory() as db:
        assert len(db.scalars(select(Event)).all()) == 2
    assert r.status == "error"


def test_one_failing_source_does_not_block_another(factory):
    good = ad()
    bad = ad(fail=True)
    bad.slug, bad.championship_slug = "broken", "x"
    reports = refresh_all(factory, [bad, good], 2026, now=NOW)
    assert [r.status for r in reports] == ["error", "ok"]


def test_concurrent_refresh_rejected(factory):
    assert _lock.acquire(blocking=False)
    try:
        with pytest.raises(RefreshInProgress):
            refresh_all(factory, [ad()], 2026)
    finally:
        _lock.release()


def test_bundle_rejects_duplicate_positions():
    row = StandingDTO(kind="driver", position=1, points=1, team=TeamRef(key="a", name="A"))
    with pytest.raises(ValueError):
        Bundle(year=2026, standings=[row, row])


def test_event_detail_and_results_api(factory, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main
    from app.adapters.jolpica_f1 import JolpicaF1
    from app.refresh import refresh_all
    from tests.conftest import make_transport
    refresh_all(factory, [JolpicaF1(transport=make_transport(), pause=0)], 2026, force=True)
    monkeypatch.setattr(main, "SessionLocal", factory)
    tc = TestClient(main.app)
    ev = tc.get("/api/events/f1/2026/1").json()
    by_kind = {s["kind"]: s["results"] for s in ev["sessions"]}
    assert by_kind["race"][0]["driver"] == "Ann Alpha" and by_kind["race"][1]["position"] is None
    assert by_kind["qualifying"][0]["time"] == "1:19.5" and ev["live_timing_available"]
    sprint = {s["kind"]: s["results"] for s in tc.get("/api/events/f1/2026/2").json()["sessions"]}["sprint"]
    assert sprint[0]["points"] == 8
    assert tc.get("/api/results/f1/2026").json()[0]["driver"] == "Ann Alpha"
    assert tc.get("/api/drivers/f1/2026").json()[0]["team"] == "Team One"
    assert tc.get("/api/events/f1/2026/99").status_code == 404
