"""Formula 1 via Jolpica-F1 (Ergast-compatible, public, rate-limited).
Parsing follows the documented Ergast JSON layout; it has NOT yet been run
against the live service from this development sandbox (see docs/DATA_SOURCES.md)."""
import time
from datetime import date, datetime, timezone

import httpx

from .. import config
from .base import (Bundle, DriverRef, EventDTO, ResultDTO, SessionDTO,
                   SourceError, StandingDTO, TeamRef)

BASE = "https://api.jolpi.ca/ergast/f1"
SESSION_KEYS = {
    "FirstPractice": "fp1", "SecondPractice": "fp2", "ThirdPractice": "fp3",
    "SprintQualifying": "sprint_qualifying", "SprintShootout": "sprint_qualifying",
    "Sprint": "sprint", "Qualifying": "qualifying",
}


def _dt(d: str | None, t: str | None) -> datetime | None:
    if not d or not t:
        return None
    return datetime.fromisoformat(f"{d}T{t.replace('Z', '')}").replace(tzinfo=timezone.utc)


def _driver(d: dict) -> DriverRef:
    return DriverRef(key=d["driverId"], name=f"{d['givenName']} {d['familyName']}",
                     code=d.get("code"), nationality=d.get("nationality"))


def _team(c: dict) -> TeamRef:
    return TeamRef(key=c["constructorId"], name=c["name"], nationality=c.get("nationality"))


class JolpicaF1:
    slug = "jolpica-f1"
    championship_slug = "f1"
    championship_name = "Formula 1"
    category = "open-wheel"
    official_url = "https://www.formula1.com/"

    def __init__(self, transport: httpx.BaseTransport | None = None, base: str = BASE, pause: float = 0.3):
        self.client = httpx.Client(transport=transport, timeout=20,
                                   headers={"User-Agent": config.USER_AGENT})
        self.base, self.pause = base, pause

    def _get(self, path: str, **params) -> dict:
        url = f"{self.base}/{path}"
        for attempt in range(2):
            try:
                r = self.client.get(url, params=params)
            except httpx.HTTPError as e:
                raise SourceError(f"network error: {e}") from e
            if r.status_code == 429 and attempt == 0:
                time.sleep(min(float(r.headers.get("Retry-After", 5)), 30))
                continue
            if r.status_code != 200:
                raise SourceError(f"HTTP {r.status_code} for {path}")
            try:
                return r.json()["MRData"]
            except (ValueError, KeyError) as e:
                raise SourceError(f"malformed response for {path}") from e
        raise SourceError(f"rate limited: {path}")

    # --- parsers (pure, unit-tested) ---
    @staticmethod
    def parse_schedule(mr: dict) -> list[EventDTO]:
        events = []
        for r in mr["RaceTable"]["Races"]:
            c = r["Circuit"]
            sessions = [SessionDTO(kind=SESSION_KEYS[k], starts_at=_dt(v.get("date"), v.get("time")))
                        for k, v in r.items() if k in SESSION_KEYS]
            sessions.append(SessionDTO(kind="race", starts_at=_dt(r["date"], r.get("time"))))
            dates = [date.fromisoformat(r["date"])] + [date.fromisoformat(r[k]["date"]) for k in r if k in SESSION_KEYS]
            events.append(EventDTO(
                key=f"{r['season']}-{r['round']}", round=int(r["round"]), name=r["raceName"],
                circuit_key=c["circuitId"], circuit_name=c["circuitName"],
                locality=c["Location"].get("locality"), country=c["Location"].get("country"),
                start_date=min(dates), end_date=max(dates), sessions=sessions))
        return events

    @staticmethod
    def parse_standings(mr: dict, kind: str) -> tuple[list[StandingDTO], int | None]:
        lists = mr["StandingsTable"]["StandingsLists"]
        if not lists:
            return [], None  # season not started: not an error
        sl = lists[0]
        rows = []
        for row in sl["DriverStandings" if kind == "driver" else "ConstructorStandings"]:
            base = dict(kind=kind, position=int(row["position"]), points=float(row["points"]),
                        wins=int(row["wins"]))
            if kind == "driver":
                base["driver"] = _driver(row["Driver"])
                if row.get("Constructors"):
                    base["team"] = _team(row["Constructors"][-1])
            else:
                base["team"] = _team(row["Constructor"])
            rows.append(StandingDTO(**base))
        return rows, int(sl["round"])

    @staticmethod
    def parse_results(mr: dict) -> list[ResultDTO]:
        out = []
        for r in mr["RaceTable"]["Races"]:
            for x in r.get("Results", []):
                pos = int(x["position"]) if x.get("positionText", "").isdigit() else None
                out.append(ResultDTO(
                    event_key=f"{r['season']}-{r['round']}", session_kind="race", position=pos,
                    status=x["status"], car_number=x.get("number"), grid=int(x["grid"]) if x.get("grid") else None,
                    laps=int(x["laps"]) if x.get("laps") else None,
                    time_text=(x.get("Time") or {}).get("time"), points=float(x["points"]),
                    driver=_driver(x["Driver"]), team=_team(x["Constructor"])))
        return out

    # --- orchestration ---
    def fetch(self, year: int) -> Bundle:
        events = self.parse_schedule(self._get(f"{year}.json", limit=100))
        drivers, after = self.parse_standings(self._get(f"{year}/driverstandings.json"), "driver")
        constructors, _ = self.parse_standings(self._get(f"{year}/constructorstandings.json"), "constructor")
        results, offset = [], 0
        for _ in range(20):  # hard page cap
            time.sleep(self.pause)
            mr = self._get(f"{year}/results.json", limit=100, offset=offset)
            results += self.parse_results(mr)
            offset += 100
            if offset >= int(mr["total"]):
                break
        return Bundle(year=year, events=events, standings=drivers + constructors,
                      standings_after_round=after, results=results)
