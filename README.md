# Motorsport Hub (backend foundation)

Early foundation for a multi-series motorsport hub. **Only F1 has an adapter, and it has not yet been run against the live service.** See `docs/DATA_SOURCES.md` for honest coverage.

## Run
```
cd backend
pip install -r requirements.txt
cp ../.env.example .env   # export the variables (the app reads the environment)
python -m pytest -q                 # tests (no network needed)
python -m app.cli refresh --force   # first real fetch from Jolpica
uvicorn app.main:app --reload       # API on :8000
```
Daily refresh: run `python -m app.cli refresh` from cron / a systemd timer.

## Environment variables
`DATABASE_URL`, `STALE_AFTER_HOURS`, `SEASON`, `USER_AGENT` (see `.env.example`). No API secrets are required.
