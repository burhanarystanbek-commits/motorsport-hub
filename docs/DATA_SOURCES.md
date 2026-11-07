# Data sources and actual coverage

Status legend: **Implemented+unit-tested** = adapter exists and passes tests against recorded-shape fixtures.
**Not live-tested** = never run against the real service. **Not investigated** = no research done yet; nothing below is guessed.

| Series | Source | Status | Provides | Known limits |
|---|---|---|---|---|
| F1 | Jolpica-F1 (Ergast-compatible), `https://api.jolpi.ca/ergast/f1` | Implemented+unit-tested; **not live-tested** | Calendar + session times, driver/constructor standings, race, sprint and qualifying results | Rate limit documented by a client library as 500 req/h; no news, no live timing |
| F1 live timing | OpenF1, `https://api.openf1.org/v1` | Implemented+unit-tested against fixtures built from the documented field layout; **not live-tested** (host unreachable from the dev sandbox) | Laps, sectors, speed traps, intervals/gaps, positions, stints/tyres, pit stops, race control, weather; any past session replayable by `session_key` | Historical data is free; data **during a live session needs an OpenF1 account** (`OPENF1_USERNAME`/`OPENF1_PASSWORD`), otherwise the API returns `available: false` with the reason. Delay of a few seconds vs. TV |
| F2, F3 | fiaformula2.com / fiaformula3.com | **Not investigated** | - | - |
| WEC / Le Mans | fiawec.com | **Not investigated** | - | - |
| IMSA | imsa.com | **Not investigated** | - | - |
| GT World Challenge | gt-world-challenge-*.com | **Not investigated** (SRO is seen to publish timing bulletins as PDF) | - | PDF parsing would be fragile |
| DTM | dtm.com | **Not investigated** | - | - |
| News (all) | - | **No adapter**; `news_article` table is schema only | - | - |

## Phase 1 checklist per remaining source
1. Read robots.txt and terms of service; record what is allowed.
2. Look for an official API, RSS feed, CSV/PDF downloads or a structured endpoint the site itself documents.
3. Record update frequency and coverage; write a fixture from a real response.
4. Implement an adapter against `app/adapters/base.py`, add tests, mark status here only after a real fetch succeeds.

If no permitted source exists: the API returns `available: false` and the UI links to the official site. Alternatives: a paid sports-data API, or manual CSV import.
