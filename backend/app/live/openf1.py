"""F1 live timing via OpenF1 (https://openf1.org).

Field names follow the OpenF1 v1 documentation; this module has NOT yet been run
against the live service from the development sandbox (see docs/DATA_SOURCES.md).

Design:
- `OpenF1Client` does HTTP + optional OAuth token (needed for data during a live session).
- `SessionFeed` keeps everything received for ONE session and fetches only new rows
  (`date>` filter), so a 2-hour race is not re-downloaded every few seconds.
- `build_snapshot` is a pure function: feed rows -> timing-tower JSON. Unit-tested.
"""
import threading
import time
from datetime import datetime, timezone

import httpx
from urllib.parse import quote

from .. import config
from ..adapters.base import SourceError

# endpoint -> date field used for incremental fetching (None = small, refetch fully)
INCREMENTAL = {"intervals": "date", "position": "date", "laps": "date_start",
               "pit": "date", "race_control": "date", "weather": "date"}
FULL = ("drivers", "stints")


def _parse_dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class OpenF1Client:
    def __init__(self, transport: httpx.BaseTransport | None = None, base: str | None = None,
                 username: str | None = None, password: str | None = None):
        self.base = (base or config.OPENF1_BASE).rstrip("/")
        self.username = config.OPENF1_USERNAME if username is None else username
        self.password = config.OPENF1_PASSWORD if password is None else password
        self.client = httpx.Client(transport=transport, timeout=15, headers={"User-Agent": config.USER_AGENT})
        self._token, self._token_exp = None, 0.0
        self._tlock = threading.Lock()

    @property
    def authenticated(self) -> bool:
        return bool(self.username and self.password)

    def _auth_header(self) -> dict:
        if not self.authenticated:
            return {}
        with self._tlock:
            if not self._token or time.time() > self._token_exp - 60:
                root = self.base.rsplit("/v1", 1)[0]
                try:
                    r = self.client.post(f"{root}/token", data={"username": self.username,
                                                                "password": self.password})
                except httpx.HTTPError as e:
                    raise SourceError(f"OpenF1 token request failed: {e}") from e
                if r.status_code != 200:
                    raise SourceError(f"OpenF1 token request: HTTP {r.status_code}")
                body = r.json()
                self._token = body["access_token"]
                self._token_exp = time.time() + float(body.get("expires_in", 3600))
            return {"Authorization": f"Bearer {self._token}"}

    def get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        # OpenF1 filters like `date>X` are encoded in the key, so build the query manually.
        # keys ending in an operator ("date>") are written as `date>VALUE`, not `date>=VALUE`
        # values are percent-encoded: "+00:00" in a timestamp must not turn into a space
        query = "&".join(f"{k}{quote(str(v), safe='')}" if k[-1] in "<>" else f"{k}={quote(str(v), safe='')}"
                         for k, v in (params or {}).items())
        url = f"{self.base}/{endpoint}" + (f"?{query}" if query else "")
        for attempt in range(2):
            try:
                r = self.client.get(url, headers=self._auth_header())
            except httpx.HTTPError as e:
                raise SourceError(f"network error: {e}") from e
            if r.status_code == 429 and attempt == 0:
                time.sleep(min(float(r.headers.get("Retry-After", 2)), 10))
                continue
            if r.status_code == 404:
                return []  # OpenF1 answers 404 when a filter matches nothing
            if r.status_code in (401, 403):
                raise SourceError("OpenF1 refused access: live data during a session needs an "
                                  "OpenF1 account (set OPENF1_USERNAME / OPENF1_PASSWORD)")
            if r.status_code != 200:
                raise SourceError(f"OpenF1 HTTP {r.status_code} for {endpoint}")
            try:
                data = r.json()
            except ValueError as e:
                raise SourceError(f"malformed OpenF1 response for {endpoint}") from e
            if isinstance(data, dict):  # error object instead of a list
                raise SourceError(f"OpenF1 error for {endpoint}: {data.get('detail') or data}")
            return data
        raise SourceError(f"OpenF1 rate limited: {endpoint}")


class SessionFeed:
    """All rows received so far for one session_key; `poll()` appends only new ones."""

    def __init__(self, client: OpenF1Client, session: dict):
        self.client, self.session = client, session
        self.key = session["session_key"]
        self.rows: dict[str, list[dict]] = {e: [] for e in (*INCREMENTAL, *FULL)}
        self._cursor: dict[str, str] = {}
        self.polled_at: datetime | None = None

    def poll(self):
        for ep, field in INCREMENTAL.items():
            params = {"session_key": self.key}
            if ep in self._cursor:
                params[f"{field}>"] = self._cursor[ep]
            new = [r for r in self.client.get(ep, params) if r.get(field)]
            if new:
                self.rows[ep].extend(new)
                self._cursor[ep] = max(r[field] for r in new)
        for ep in FULL:
            self.rows[ep] = self.client.get(ep, {"session_key": self.key})
        self.polled_at = datetime.now(timezone.utc)


def _latest_by_driver(rows: list[dict], field: str = "date") -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in rows:
        n = r.get("driver_number")
        if n is None:
            continue
        if n not in out or (r.get(field) or "") >= (out[n].get(field) or ""):
            out[n] = r
    return out


def _gap(v):
    """OpenF1 gaps are seconds (float), '+1 LAP' style strings, or null."""
    if v is None or isinstance(v, str):
        return v
    return round(float(v), 3)


def session_status(session: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    start, end = _parse_dt(session.get("date_start")), _parse_dt(session.get("date_end"))
    if start and now < start:
        return "upcoming"
    if end and now > end:
        return "finished"
    return "live"


def build_snapshot(session: dict, rows: dict[str, list[dict]], now: datetime | None = None) -> dict:
    drivers = {d["driver_number"]: d for d in rows.get("drivers", [])}
    pos = _latest_by_driver(rows.get("position", []))
    ints = _latest_by_driver(rows.get("intervals", []))

    laps_by: dict[int, list[dict]] = {}
    for lap in rows.get("laps", []):
        laps_by.setdefault(lap["driver_number"], []).append(lap)
    stints_by: dict[int, list[dict]] = {}
    for s in rows.get("stints", []):
        stints_by.setdefault(s["driver_number"], []).append(s)
    pits_by: dict[int, int] = {}
    for p in rows.get("pit", []):
        pits_by[p["driver_number"]] = pits_by.get(p["driver_number"], 0) + 1

    def timed(lap):
        return lap.get("lap_duration") is not None

    all_timed = [lap for laps in laps_by.values() for lap in laps if timed(lap)]
    overall_best = min(all_timed, key=lambda x: x["lap_duration"]) if all_timed else None
    best_sectors = {i: min((lap[f"duration_sector_{i}"] for lap in all_timed if lap.get(f"duration_sector_{i}")),
                           default=None) for i in (1, 2, 3)}

    numbers = set(drivers) | set(pos) | set(laps_by)
    tower = []
    for n in numbers:
        d = drivers.get(n, {})
        laps = sorted(laps_by.get(n, []), key=lambda x: x["lap_number"])
        done = [lap for lap in laps if timed(lap)]
        last = done[-1] if done else None
        best = min(done, key=lambda x: x["lap_duration"]) if done else None
        stint = max(stints_by.get(n, []), key=lambda s: s.get("stint_number") or 0, default=None)
        cur_lap = laps[-1]["lap_number"] if laps else None
        tyre = None
        if stint:
            age = stint.get("tyre_age_at_start") or 0
            if cur_lap and stint.get("lap_start"):
                age += max(cur_lap - stint["lap_start"], 0)
            tyre = {"compound": stint.get("compound"), "age_laps": age, "stint": stint.get("stint_number")}
        last_lap = None
        if last:
            last_lap = {"lap": last["lap_number"], "time": last["lap_duration"],
                        "sectors": [last.get(f"duration_sector_{i}") for i in (1, 2, 3)],
                        "personal_best": best is last,
                        "overall_best": overall_best is last,
                        "sector_overall_best": [last.get(f"duration_sector_{i}") is not None and
                                                last.get(f"duration_sector_{i}") == best_sectors[i]
                                                for i in (1, 2, 3)],
                        "speed_trap_kph": last.get("st_speed"),
                        "pit_out_lap": bool(last.get("is_pit_out_lap"))}
        iv = ints.get(n, {})
        tower.append({
            "position": pos.get(n, {}).get("position"),
            "driver_number": n,
            "code": d.get("name_acronym"),
            "name": d.get("full_name") or d.get("broadcast_name"),
            "team": d.get("team_name"),
            "team_colour": f"#{d['team_colour']}" if d.get("team_colour") else None,
            "headshot_url": d.get("headshot_url"),
            "gap_to_leader": _gap(iv.get("gap_to_leader")),
            "interval": _gap(iv.get("interval")),
            "current_lap": cur_lap,
            "laps_completed": len(done),
            "last_lap": last_lap,
            "best_lap": {"lap": best["lap_number"], "time": best["lap_duration"]} if best else None,
            "tyre": tyre,
            "pit_stops": pits_by.get(n, 0),
        })
    tower.sort(key=lambda r: (r["position"] is None, r["position"] or 0, r["driver_number"]))

    weather = max(rows.get("weather", []), key=lambda w: w.get("date") or "", default=None)
    rc = sorted(rows.get("race_control", []), key=lambda x: x.get("date") or "", reverse=True)[:30]
    flag = next((m.get("flag") for m in rc if m.get("flag") and m.get("scope", "Track") == "Track"), None)
    leader_lap = max((r["current_lap"] or 0 for r in tower), default=0) or None
    return {
        "available": True,
        "session": {"session_key": session.get("session_key"), "meeting_key": session.get("meeting_key"),
                    "name": session.get("session_name"), "type": session.get("session_type"),
                    "circuit": session.get("circuit_short_name"), "country": session.get("country_name"),
                    "location": session.get("location"), "date_start": session.get("date_start"),
                    "date_end": session.get("date_end"), "status": session_status(session, now)},
        "leader_lap": leader_lap,
        "track_flag": flag,
        "fastest_lap": ({"driver_number": overall_best["driver_number"],
                         "code": drivers.get(overall_best["driver_number"], {}).get("name_acronym"),
                         "lap": overall_best["lap_number"], "time": overall_best["lap_duration"]}
                        if overall_best else None),
        "weather": ({k: weather.get(k) for k in ("air_temperature", "track_temperature", "humidity",
                                                  "rainfall", "wind_speed", "wind_direction", "pressure")}
                    if weather else None),
        "race_control": [{"date": m.get("date"), "lap": m.get("lap_number"), "category": m.get("category"),
                          "flag": m.get("flag"), "driver_number": m.get("driver_number"),
                          "message": m.get("message")} for m in rc],
        "timing": tower,
    }
