"""python -m app.cli refresh [--force]   (run daily from cron / systemd timer / a scheduled job)"""
import sys

from . import config
from .db import init_db, make_engine, make_session_factory
from .refresh import refresh_all
from .registry import get_adapters

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "refresh":
        sys.exit("usage: python -m app.cli refresh [--force]")
    eng = make_engine()
    init_db(eng)
    for r in refresh_all(make_session_factory(eng), get_adapters(), config.season(), force="--force" in sys.argv):
        print(r.source, r.status, r.message or r.counts)
