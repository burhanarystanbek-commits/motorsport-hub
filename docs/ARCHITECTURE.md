# Architecture (backend foundation)

- **Adapters** (`app/adapters/`): one per source, return validated pydantic DTOs (`Bundle`). No DB or UI knowledge, so one broken source cannot break the rest.
- **Refresh** (`app/refresh.py`): global lock (one refresh at a time), per-source isolation, staleness check (default 24h), validate -> persist in one transaction -> replace standings only after success. On failure the transaction is rolled back, the last valid data stays, `data_source.last_error` is set and the API reports `possibly_outdated`.
- **Database**: SQLAlchemy 2. SQLite by default, PostgreSQL via `DATABASE_URL`. Tables are created with `create_all`; **Alembic migrations are not set up yet**.
- **API** (FastAPI): `/api/status`, `POST /api/refresh` (409 if one is running), `/api/championships`, `/api/events`, `/api/standings/{series}/{year}`.
- **Scheduling**: refresh-if-stale on server start, plus `python -m app.cli refresh` for a daily cron/systemd timer.
- **Model**: championships have a `rules` JSON, standings have `kind` and `class_name`, `Entry`/`EntryDriver` allow several drivers per car. Those endurance/GT parts are schema only until a WEC/IMSA/GT adapter uses them.
- **Not built**: frontend, news, favourites, search, notifications, PWA/offline, live timing.
