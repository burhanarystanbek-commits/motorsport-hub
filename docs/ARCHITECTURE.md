# Architecture (backend foundation)

- **Adapters** (`app/adapters/`): one per source, return validated pydantic DTOs (`Bundle`). No DB or UI knowledge, so one broken source cannot break the rest.
- **Refresh** (`app/refresh.py`): global lock (one refresh at a time), per-source isolation, staleness check (default 24h), validate -> persist in one transaction -> replace standings only after success. On failure the transaction is rolled back, the last valid data stays, `data_source.last_error` is set and the API reports `possibly_outdated`.
- **Database**: SQLAlchemy 2. SQLite by default, PostgreSQL via `DATABASE_URL`. Tables are created with `create_all`; **Alembic migrations are not set up yet**.
- **API** (FastAPI, CORS via `CORS_ORIGINS`):
  - `/api/health`, `/api/status`, `POST /api/refresh` (409 if one is running)
  - `/api/championships`, `/api/events?championship=&year=`, `/api/events/{series}/{year}/{round}` (all sessions + results: race, sprint, qualifying)
  - `/api/standings/{series}/{year}?kind=driver|constructor`, `/api/results/{series}/{year}?kind=race|sprint|qualifying` (winners per round), `/api/drivers/{series}/{year}`
  - Live timing (F1 only): `/api/live/f1?session_key=latest`, `/api/live/f1/stream` (SSE), `/api/live/f1/laps/{driver_number}`, `/api/live/f1/sessions?year=`
- **Scheduling**: refresh-if-stale on server start, plus `python -m app.cli refresh` for a daily cron/systemd timer.
- **Model**: championships have a `rules` JSON, standings have `kind` and `class_name`, `Entry`/`EntryDriver` allow several drivers per car. Those endurance/GT parts are schema only until a WEC/IMSA/GT adapter uses them.
- **Live timing** (`app/live/`): `OpenF1Client` -> `SessionFeed` (per session, fetches only rows newer than the last `date`, so polling stays cheap) -> pure `build_snapshot` (timing tower: position, gap to leader, interval, last/best lap, sectors with overall-best flags, speed trap, tyre compound + age, pit stops, track flag, race control, weather, fastest lap). `LiveTimingService` shares one upstream poll per `LIVE_POLL_SECONDS` across all clients, keeps the last good snapshot on error (`possibly_outdated`), stops polling finished sessions and keeps at most 4 sessions in memory. Live data is not stored in the DB.
- **Not built**: frontend, news, favourites, search, notifications, PWA/offline, live timing for series other than F1.
