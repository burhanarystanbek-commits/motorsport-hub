"""Live timing: fixtures follow the OpenF1 v1 documented field layout (not recorded live)."""
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx
import pytest

from app.adapters.base import SourceError
from app.live.openf1 import OpenF1Client, SessionFeed, build_snapshot, session_status
from app.live.service import LiveTimingService

SESSION = {"session_key": 9999, "meeting_key": 1200, "session_name": "Race", "session_type": "Race",
           "circuit_short_name": "Monza", "country_name": "Italy", "location": "Monza",
           "date_start": "2026-09-06T13:00:00+00:00", "date_end": "2026-09-06T15:00:00+00:00"}
DRIVERS = [
    {"driver_number": 1, "name_acronym": "ALP", "full_name": "Ann ALPHA", "team_name": "Team One",
     "team_colour": "3671C6", "session_key": 9999},
    {"driver_number": 16, "name_acronym": "BET", "full_name": "Bo BETA", "team_name": "Team Two",
     "team_colour": "E8002D", "session_key": 9999},
]


def lap(n, num, dur, s, date, pit=False):
    return {"driver_number": n, "lap_number": num, "lap_duration": dur, "duration_sector_1": s[0],
            "duration_sector_2": s[1], "duration_sector_3": s[2], "st_speed": 340, "i1_speed": 300,
            "i2_speed": 310, "is_pit_out_lap": pit, "date_start": date}


ROWS = {
    "drivers": DRIVERS,
    "position": [{"driver_number": 1, "position": 2, "date": "2026-09-06T13:01:00"},
                 {"driver_number": 16, "position": 1, "date": "2026-09-06T13:01:00"},
                 {"driver_number": 1, "position": 1, "date": "2026-09-06T13:05:00"},
                 {"driver_number": 16, "position": 2, "date": "2026-09-06T13:05:00"}],
    "intervals": [{"driver_number": 1, "gap_to_leader": 0, "interval": None, "date": "2026-09-06T13:05:00"},
                  {"driver_number": 16, "gap_to_leader": 1.2345, "interval": 1.2345, "date": "2026-09-06T13:05:00"},
                  {"driver_number": 16, "gap_to_leader": "+1 LAP", "interval": "+1 LAP",
                   "date": "2026-09-06T13:04:00"}],  # older row must not win
    "laps": [lap(1, 1, None, (None, 30.0, 29.0), "2026-09-06T13:00:00"),
             lap(1, 2, 81.5, (27.0, 27.5, 27.0), "2026-09-06T13:02:00"),
             lap(1, 3, 82.0, (26.8, 28.0, 27.2), "2026-09-06T13:03:30"),
             lap(16, 2, 81.9, (27.1, 27.4, 27.4), "2026-09-06T13:02:00"),
             lap(16, 3, 81.7, (27.2, 27.3, 27.2), "2026-09-06T13:03:30", pit=True)],
    "stints": [{"driver_number": 1, "stint_number": 1, "compound": "MEDIUM", "lap_start": 1, "lap_end": None,
                "tyre_age_at_start": 2},
               {"driver_number": 16, "stint_number": 1, "compound": "SOFT", "lap_start": 1, "lap_end": 2,
                "tyre_age_at_start": 0},
               {"driver_number": 16, "stint_number": 2, "compound": "HARD", "lap_start": 3, "lap_end": None,
                "tyre_age_at_start": 0}],
    "pit": [{"driver_number": 16, "lap_number": 2, "pit_duration": 22.1, "date": "2026-09-06T13:03:20"}],
    "race_control": [{"date": "2026-09-06T13:00:00", "category": "Flag", "flag": "GREEN", "scope": "Track",
                      "message": "GREEN LIGHT"},
                     {"date": "2026-09-06T13:04:00", "category": "Flag", "flag": "YELLOW", "scope": "Sector",
                      "message": "YELLOW IN SECTOR 2"}],
    "weather": [{"date": "2026-09-06T13:00:00", "air_temperature": 25, "track_temperature": 40, "rainfall": 0},
                {"date": "2026-09-06T13:05:00", "air_temperature": 26, "track_temperature": 41, "rainfall": 0}],
}
NOW = datetime(2026, 9, 6, 13, 6, tzinfo=timezone.utc)


def test_snapshot_tower():
    s = build_snapshot(SESSION, ROWS, NOW)
    assert s["session"]["status"] == "live" and s["leader_lap"] == 3
    a, b = s["timing"]
    assert (a["code"], a["position"], b["code"], b["position"]) == ("ALP", 1, "BET", 2)
    assert b["gap_to_leader"] == 1.234 and b["interval"] == 1.234  # latest row, rounded
    assert a["team_colour"] == "#3671C6"
    assert a["laps_completed"] == 2 and a["current_lap"] == 3
    assert a["last_lap"]["time"] == 82.0 and not a["last_lap"]["personal_best"]
    assert a["best_lap"] == {"lap": 2, "time": 81.5}
    assert a["last_lap"]["sector_overall_best"] == [True, False, False]
    assert a["tyre"] == {"compound": "MEDIUM", "age_laps": 4, "stint": 1}
    assert b["tyre"]["compound"] == "HARD" and b["pit_stops"] == 1 and b["last_lap"]["pit_out_lap"]
    assert s["fastest_lap"]["code"] == "ALP" and s["fastest_lap"]["time"] == 81.5
    assert s["track_flag"] == "GREEN"  # sector yellow is not a track flag
    assert s["weather"]["air_temperature"] == 26
    assert s["race_control"][0]["message"] == "YELLOW IN SECTOR 2"


def test_snapshot_handles_empty_feed():
    s = build_snapshot(SESSION, {}, NOW)
    assert s["timing"] == [] and s["fastest_lap"] is None and s["weather"] is None


def test_session_status():
    assert session_status(SESSION, datetime(2026, 9, 6, 12, tzinfo=timezone.utc)) == "upcoming"
    assert session_status(SESSION, datetime(2026, 9, 6, 16, tzinfo=timezone.utc)) == "finished"


class FakeOpenF1:
    """Serves ROWS and honours OpenF1's `field>value` filter so incremental polling is tested."""

    def __init__(self, status=200):
        self.calls, self.status = [], status

    def __call__(self, req: httpx.Request):
        ep = req.url.path.rsplit("/", 1)[-1]
        query = unquote(str(req.url.query, "ascii") if isinstance(req.url.query, bytes) else str(req.url.query))
        self.calls.append((ep, query))
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "nope"})
        if ep == "sessions":
            return httpx.Response(200, json=[SESSION])
        rows = ROWS.get(ep, [])
        for part in query.split("&"):
            if ">=" in part:
                field, val = part.split(">=", 1)
                rows = [r for r in rows if (r.get(field) or "") >= val]
            elif ">" in part:
                field, val = part.split(">", 1)
                rows = [r for r in rows if (r.get(field) or "") > val]
        if not rows:
            return httpx.Response(404, json={"detail": "No results found."})
        return httpx.Response(200, json=rows)


def client(fake):
    return OpenF1Client(transport=httpx.MockTransport(fake), base="https://x/v1", username="", password="")


def test_feed_fetches_only_new_rows():
    fake = FakeOpenF1()
    feed = SessionFeed(client(fake), SESSION)
    feed.poll()
    assert len(feed.rows["laps"]) == 5 and len(feed.rows["position"]) == 4
    feed.poll()  # nothing new upstream -> no duplicates
    assert len(feed.rows["laps"]) == 5 and len(feed.rows["intervals"]) == 3
    laps_q = [q for ep, q in fake.calls if ep == "laps"]
    assert "date_start>2026-09-06T13:03:30" in laps_q[-1]


def test_service_caches_and_throttles():
    fake = FakeOpenF1()
    svc = LiveTimingService(client(fake), poll_seconds=60)
    s1 = svc.snapshot("latest")
    n = len(fake.calls)
    s2 = svc.snapshot("latest")
    assert s1["available"] and s2["timing"] == s1["timing"]
    assert len(fake.calls) == n  # second call served from cache
    laps = svc.laps("latest", 16)
    assert [x["lap"] for x in laps] == [2, 3] and laps[1]["pit_out_lap"]


def test_service_reports_auth_error():
    svc = LiveTimingService(client(FakeOpenF1(status=401)), poll_seconds=0)
    s = svc.snapshot("latest")
    assert s["available"] is False and "OpenF1" in s["message"]


def test_client_raises_on_server_error():
    with pytest.raises(SourceError):
        client(FakeOpenF1(status=500)).get("laps", {"session_key": 1})


def test_api_live_endpoints(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main
    monkeypatch.setattr(main, "live", LiveTimingService(client(FakeOpenF1()), poll_seconds=60))
    tc = TestClient(main.app)  # no `with`: startup refresh (network) is not triggered
    r = tc.get("/api/live/f1").json()
    assert r["available"] and r["timing"][0]["code"] == "ALP"
    assert tc.get("/api/live/f1/laps/1").json()[0]["lap"] == 1
    assert tc.get("/api/live/f1/sessions?year=2026").json()[0]["session_key"] == 9999
    assert tc.get("/api/live/wec").status_code == 404
