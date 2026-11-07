import httpx
import pytest

from app.db import init_db, make_engine, make_session_factory

SCHEDULE = {"MRData": {"RaceTable": {"Races": [
    {"season": "2026", "round": "1", "raceName": "Australian Grand Prix", "date": "2026-03-15", "time": "04:00:00Z",
     "Circuit": {"circuitId": "albert_park", "circuitName": "Albert Park Grand Prix Circuit",
                 "Location": {"locality": "Melbourne", "country": "Australia"}},
     "FirstPractice": {"date": "2026-03-13", "time": "01:30:00Z"},
     "Qualifying": {"date": "2026-03-14", "time": "05:00:00Z"}},
    {"season": "2026", "round": "2", "raceName": "Chinese Grand Prix", "date": "2026-03-22",
     "Circuit": {"circuitId": "shanghai", "circuitName": "Shanghai International Circuit",
                 "Location": {"locality": "Shanghai", "country": "China"}},
     "Sprint": {"date": "2026-03-21"}}]}}}

DRIVERS = {"MRData": {"StandingsTable": {"StandingsLists": [{"round": "1", "DriverStandings": [
    {"position": "1", "points": "25", "wins": "1",
     "Driver": {"driverId": "alpha", "givenName": "Ann", "familyName": "Alpha", "code": "ALP", "nationality": "British"},
     "Constructors": [{"constructorId": "t1", "name": "Team One", "nationality": "British"}]},
    {"position": "2", "points": "18", "wins": "0",
     "Driver": {"driverId": "beta", "givenName": "Bo", "familyName": "Beta", "code": "BET", "nationality": "Dutch"},
     "Constructors": [{"constructorId": "t2", "name": "Team Two", "nationality": "Italian"}]}]}]}}}

CONSTRUCTORS = {"MRData": {"StandingsTable": {"StandingsLists": [{"round": "1", "ConstructorStandings": [
    {"position": "1", "points": "25", "wins": "1",
     "Constructor": {"constructorId": "t1", "name": "Team One", "nationality": "British"}}]}]}}}

RESULTS = {"MRData": {"total": "2", "RaceTable": {"Races": [
    {"season": "2026", "round": "1", "Results": [
        {"number": "1", "position": "1", "positionText": "1", "points": "25", "grid": "1", "laps": "58",
         "status": "Finished", "Time": {"time": "1:20:00.000"},
         "Driver": DRIVERS["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"][0]["Driver"],
         "Constructor": {"constructorId": "t1", "name": "Team One", "nationality": "British"}},
        {"number": "2", "position": "2", "positionText": "R", "points": "0", "grid": "2", "laps": "10",
         "status": "Engine",
         "Driver": DRIVERS["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"][1]["Driver"],
         "Constructor": {"constructorId": "t2", "name": "Team Two", "nationality": "Italian"}}]}]}}}


_D = DRIVERS["MRData"]["StandingsTable"]["StandingsLists"][0]["DriverStandings"]
SPRINT = {"MRData": {"total": "1", "RaceTable": {"Races": [
    {"season": "2026", "round": "2", "SprintResults": [
        {"number": "1", "position": "1", "positionText": "1", "points": "8", "grid": "1", "laps": "19",
         "status": "Finished", "Time": {"time": "30:00.000"}, "Driver": _D[0]["Driver"],
         "Constructor": {"constructorId": "t1", "name": "Team One", "nationality": "British"}}]}]}}}

QUALIFYING = {"MRData": {"total": "2", "RaceTable": {"Races": [
    {"season": "2026", "round": "1", "QualifyingResults": [
        {"number": "1", "position": "1", "Q1": "1:20.1", "Q2": "1:19.9", "Q3": "1:19.5", "Driver": _D[0]["Driver"],
         "Constructor": {"constructorId": "t1", "name": "Team One", "nationality": "British"}},
        {"number": "2", "position": "2", "Q1": "1:21.0", "Driver": _D[1]["Driver"],
         "Constructor": {"constructorId": "t2", "name": "Team Two", "nationality": "Italian"}}]}]}}}


def make_transport(fail: bool = False, empty_schedule: bool = False):
    def handler(req: httpx.Request):
        if fail:
            return httpx.Response(503)
        p = req.url.path
        if p.endswith("/driverstandings.json"):
            return httpx.Response(200, json=DRIVERS)
        if p.endswith("/constructorstandings.json"):
            return httpx.Response(200, json=CONSTRUCTORS)
        if p.endswith("/results.json"):
            return httpx.Response(200, json=RESULTS)
        if p.endswith("/sprint.json"):
            return httpx.Response(200, json=SPRINT)
        if p.endswith("/qualifying.json"):
            return httpx.Response(200, json=QUALIFYING)
        if empty_schedule:
            return httpx.Response(200, json={"MRData": {"RaceTable": {"Races": []}}})
        return httpx.Response(200, json=SCHEDULE)
    return httpx.MockTransport(handler)


@pytest.fixture
def factory():
    eng = make_engine("sqlite://")
    init_db(eng)
    return make_session_factory(eng)
