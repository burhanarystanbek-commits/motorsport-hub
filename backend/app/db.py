from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base


def make_engine(url: str | None = None):
    url = url or config.DATABASE_URL
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def init_db(engine) -> None:
    # TODO: replace with Alembic migrations before any schema change ships.
    Base.metadata.create_all(engine)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
