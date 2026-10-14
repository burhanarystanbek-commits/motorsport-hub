import os
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./motorsport.db")
STALE_AFTER_HOURS = float(os.getenv("STALE_AFTER_HOURS", "24"))
USER_AGENT = os.getenv("USER_AGENT", "motorsport-hub/0.1")


def season() -> int:
    v = os.getenv("SEASON", "").strip()
    return int(v) if v else datetime.now(timezone.utc).year
