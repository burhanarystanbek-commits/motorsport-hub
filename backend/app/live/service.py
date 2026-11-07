"""Shared live-timing cache: however many clients poll, upstream is hit at most
once per LIVE_POLL_SECONDS per session. A failed poll keeps the last good snapshot."""
import threading
import time
from .. import config
from ..adapters.base import SourceError
from .openf1 import OpenF1Client, SessionFeed, _parse_dt, build_snapshot, session_status

LATEST_RESOLVE_SECONDS = 60
MAX_FEEDS = 4  # historical replays share memory with the live one


class LiveTimingService:
    def __init__(self, client: OpenF1Client | None = None, poll_seconds: float | None = None):
        self.client = client or OpenF1Client()
        self.poll_seconds = config.LIVE_POLL_SECONDS if poll_seconds is None else poll_seconds
        self._lock = threading.Lock()
        self._feeds: dict[int, SessionFeed] = {}
        self._last_poll: dict[int, float] = {}
        self._errors: dict[int, str | None] = {}
        self._latest: tuple[float, dict] | None = None

    def _resolve(self, session_key: str | int) -> dict:
        if str(session_key) == "latest":
            if self._latest and time.monotonic() - self._latest[0] < LATEST_RESOLVE_SECONDS:
                return self._latest[1]
            found = self.client.get("sessions", {"session_key": "latest"})
            if not found:
                raise SourceError("OpenF1 returned no current session")
            self._latest = (time.monotonic(), found[0])
            return found[0]
        key = int(session_key)
        if key in self._feeds:
            return self._feeds[key].session
        found = self.client.get("sessions", {"session_key": key})
        if not found:
            raise LookupError(f"unknown session_key {key}")
        return found[0]

    def snapshot(self, session_key: str | int = "latest") -> dict:
        with self._lock:
            try:
                session = self._resolve(session_key)
            except SourceError as e:
                return {"available": False, "message": str(e), "timing": []}
            key = session["session_key"]
            feed = self._feeds.get(key)
            if feed is None:
                if len(self._feeds) >= MAX_FEEDS:  # drop the least recently polled feed
                    oldest = min(self._last_poll, key=self._last_poll.get)
                    for d in (self._feeds, self._last_poll, self._errors):
                        d.pop(oldest, None)
                feed = self._feeds[key] = SessionFeed(self.client, session)
            # A finished session that was fetched after it ended never changes: stop polling it.
            end = _parse_dt(session.get("date_end"))
            frozen = feed.polled_at is not None and session_status(session) == "finished" and \
                end is not None and feed.polled_at > end
            due = time.monotonic() - self._last_poll.get(key, 0) >= self.poll_seconds
            if due and not frozen:
                try:
                    feed.poll()
                    self._errors[key] = None
                except SourceError as e:
                    self._errors[key] = str(e)
                self._last_poll[key] = time.monotonic()
            if feed.polled_at is None:
                return {"available": False, "message": self._errors.get(key), "timing": []}
            snap = build_snapshot(session, feed.rows)
            snap["retrieved_at"] = feed.polled_at.isoformat()
            snap["possibly_outdated"] = self._errors.get(key) is not None
            snap["last_error"] = self._errors.get(key)
            return snap

    def laps(self, session_key: str | int, driver_number: int) -> list[dict]:
        self.snapshot(session_key)  # make sure the feed exists and is fresh
        with self._lock:
            key = self._resolve(session_key)["session_key"]
            feed = self._feeds.get(key)
            rows = [] if feed is None else feed.rows["laps"]
            return sorted(({"lap": r["lap_number"], "time": r.get("lap_duration"),
                            "sectors": [r.get(f"duration_sector_{i}") for i in (1, 2, 3)],
                            "speeds_kph": {"i1": r.get("i1_speed"), "i2": r.get("i2_speed"),
                                           "trap": r.get("st_speed")},
                            "pit_out_lap": bool(r.get("is_pit_out_lap")), "started_at": r.get("date_start")}
                           for r in rows if r["driver_number"] == driver_number), key=lambda x: x["lap"])

    def sessions(self, year: int | None = None, meeting_key: int | None = None) -> list[dict]:
        params = {k: v for k, v in (("year", year), ("meeting_key", meeting_key)) if v is not None}
        return [{"session_key": s["session_key"], "meeting_key": s.get("meeting_key"),
                 "name": s.get("session_name"), "type": s.get("session_type"),
                 "circuit": s.get("circuit_short_name"), "country": s.get("country_name"),
                 "date_start": s.get("date_start"), "date_end": s.get("date_end")}
                for s in self.client.get("sessions", params)]
