import os
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./motorsport.db")
STALE_AFTER_HOURS = float(os.getenv("STALE_AFTER_HOURS", "24"))
USER_AGENT = os.getenv("USER_AGENT", "motorsport-hub/0.1")


def season() -> int:
    v = os.getenv("SEASON", "").strip()
    return int(v) if v else datetime.now(timezone.utc).year

# Live timing (OpenF1). Historical sessions are free; live data during a session
# needs an OpenF1 account (https://openf1.org) -> set username/password.
OPENF1_BASE = os.getenv("OPENF1_BASE", "https://api.openf1.org/v1")
OPENF1_USERNAME = os.getenv("OPENF1_USERNAME", "")
OPENF1_PASSWORD = os.getenv("OPENF1_PASSWORD", "")
LIVE_POLL_SECONDS = float(os.getenv("LIVE_POLL_SECONDS", "4"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
