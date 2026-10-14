"""Source-adapter contract. Adapters turn one source into validated DTOs.
Nothing here touches the database or the UI, so a broken source can only
fail its own adapter."""
from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel, Field, model_validator


class DriverRef(BaseModel):
    key: str
    name: str
    code: str | None = None
    nationality: str | None = None


class TeamRef(BaseModel):
    key: str
    name: str
    nationality: str | None = None
    kind: str = "constructor"


class SessionDTO(BaseModel):
    kind: str
    starts_at: datetime | None = None  # timezone-aware UTC; None = time unpublished


class EventDTO(BaseModel):
    key: str
    round: int = Field(ge=1)
    name: str
    circuit_key: str
    circuit_name: str
    locality: str | None = None
    country: str | None = None
    start_date: date
    end_date: date
    sessions: list[SessionDTO] = []


class StandingDTO(BaseModel):
    kind: str  # driver | constructor | team | manufacturer
    class_name: str | None = None
    position: int = Field(ge=1)
    points: float = Field(ge=0)
    wins: int | None = Field(default=None, ge=0)
    driver: DriverRef | None = None
    team: TeamRef | None = None

    @model_validator(mode="after")
    def _has_subject(self):
        if self.driver is None and self.team is None:
            raise ValueError("standing row needs a driver or a team")
        return self


class ResultDTO(BaseModel):
    event_key: str
    session_kind: str
    position: int | None = Field(default=None, ge=1)
    status: str
    car_number: str | None = None
    class_name: str | None = None
    grid: int | None = None
    laps: int | None = None
    time_text: str | None = None
    points: float = 0
    driver: DriverRef | None = None
    team: TeamRef | None = None


class Bundle(BaseModel):
    year: int
    events: list[EventDTO] = []
    standings: list[StandingDTO] = []
    standings_after_round: int | None = None
    results: list[ResultDTO] = []
    source_updated_at: datetime | None = None  # publisher timestamp, if the source gives one

    @model_validator(mode="after")
    def _unique_positions(self):
        seen = set()
        for s in self.standings:
            k = (s.kind, s.class_name, s.position)
            if k in seen:
                raise ValueError(f"duplicate standings position {k}")
            seen.add(k)
        return self


class SourceAdapter(Protocol):
    slug: str  # data source id, e.g. "jolpica-f1"
    championship_slug: str  # e.g. "f1"
    championship_name: str
    category: str
    official_url: str

    def fetch(self, year: int) -> Bundle: ...


class SourceError(Exception):
    """Source unreachable, rate-limited or returned unusable data."""
