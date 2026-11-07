from datetime import datetime, timezone

from app.adapters.jolpica_f1 import JolpicaF1
from tests.conftest import make_transport


def test_fetch_parses_schedule_standings_results():
    b = JolpicaF1(transport=make_transport(), pause=0).fetch(2026)
    assert [e.round for e in b.events] == [1, 2]
    e1 = b.events[0]
    assert str(e1.start_date) == "2026-03-13" and str(e1.end_date) == "2026-03-15"
    kinds = {s.kind: s.starts_at for s in e1.sessions}
    assert kinds["race"] == datetime(2026, 3, 15, 4, 0, tzinfo=timezone.utc)
    assert set(kinds) == {"fp1", "qualifying", "race"}
    # missing time stays None: never invented
    assert {s.kind: s.starts_at for s in b.events[1].sessions}["race"] is None
    assert b.standings_after_round == 1
    assert [(s.kind, s.position) for s in b.standings] == [("driver", 1), ("driver", 2), ("constructor", 1)]
    assert b.standings[0].team.name == "Team One"
    assert b.results[0].position == 1 and b.results[1].position is None  # retired = not classified


def test_empty_standings_is_not_an_error():
    rows, rnd = JolpicaF1.parse_standings({"StandingsTable": {"StandingsLists": []}}, "driver")
    assert rows == [] and rnd is None


def test_sprint_and_qualifying_parsed():
    from app.adapters.jolpica_f1 import JolpicaF1
    from tests.conftest import QUALIFYING, SPRINT
    sp = JolpicaF1.parse_results(SPRINT["MRData"], "sprint")
    assert sp[0].session_kind == "sprint" and sp[0].points == 8
    q = JolpicaF1.parse_results(QUALIFYING["MRData"], "qualifying")
    assert [(x.position, x.status, x.time_text) for x in q] == [(1, "Q3", "1:19.5"), (2, "Q1", "1:21.0")]
