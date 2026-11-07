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

## App (phone + PC)
`frontend/` is an installable app (PWA): it fetches data **directly from Jolpica-F1 and OpenF1 on the device**,
no own server needed, keeps the last data for offline use and installs like a native app:
- **Android / Chrome / Edge (Windows, macOS, Linux):** open the site -> "Установить" button (or browser menu -> Install app).
- **iPhone / iPad:** Safari -> Share -> "На экран «Домой»".

Hosting: GitHub Pages, deployed by `.github/workflows/pages.yml` on every push to `main`
(one-time: repo Settings -> Pages -> Source: GitHub Actions). URL: `https://<user>.github.io/motorsport-hub/`.
Local try-out: `python -m http.server -d frontend 8080` -> http://localhost:8080.

Live timing during a session needs an OpenF1 access token (paste it on the Live page; stored only on the device).
Past sessions are free.

The Python backend is now optional (own database, scheduled refresh, shared cache for many users).
To point the app at it, set `window.MH_API = "https://your-api"` before `app.js`; the backend also serves the app at `/`.
