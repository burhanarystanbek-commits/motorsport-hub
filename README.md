# Motorsport Hub (backend foundation)

Backend for a multi-series motorsport hub. **Only F1 has adapters (Jolpica for calendar/results/standings, OpenF1 for live timing); neither has been run against the live service yet.** See `docs/DATA_SOURCES.md` for honest coverage.

## Run
```
cd backend
pip install -r requirements.txt
cp ../.env.example .env   # export the variables (the app reads the environment)
python -m pytest -q                 # tests (no network needed)
python -m app.cli refresh --force   # first real fetch from Jolpica
uvicorn app.main:app --reload       # app + API on http://localhost:8000
```
Daily refresh: run `python -m app.cli refresh` from cron / a systemd timer.

## Environment variables
`DATABASE_URL`, `STALE_AFTER_HOURS`, `SEASON`, `USER_AGENT`, `OPENF1_USERNAME`/`OPENF1_PASSWORD` (only for live data during a session), `LIVE_POLL_SECONDS`, `CORS_ORIGINS` (see `.env.example`).

## Live timing (F1)
```
curl localhost:8000/api/live/f1                       # current / latest session
curl localhost:8000/api/live/f1?session_key=9158      # replay a past session
curl -N localhost:8000/api/live/f1/stream             # Server-Sent Events, pushed on change
curl localhost:8000/api/live/f1/laps/1                # every lap of car #1
```
Endpoint list: `docs/ARCHITECTURE.md`. Interactive docs: `http://localhost:8000/docs`.

## Frontend
`frontend/` is a no-build single-page app (plain HTML/CSS/JS) served by the backend at `/`:
home (next-race countdown, standings, last winner), calendar, standings, round results (race / sprint / qualifying)
and live timing (timing tower over SSE, click a driver for every lap + lap-time chart, race control, weather, replay of past sessions).
To host it separately, serve the folder anywhere and set `window.MH_API = "https://your-api"` before `app.js`.
