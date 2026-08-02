"""Engine si sesiuni SQLAlchemy."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

__all__ = ["get_engine", "get_sessionmaker", "sesiune", "cale_db"]

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def cale_db() -> Path:
    """Calea fisierului SQLite. Suprascriptibila prin ORAR_DB."""
    if env := os.environ.get("ORAR_DB"):
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "orar.db"


def get_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    global _engine
    if url is None and _engine is not None:
        return _engine

    if url is None:
        cale = cale_db()
        cale.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{cale}"

    engine = create_engine(url, echo=echo, future=True)

    # SQLite nu impune cheile straine implicit, iar WAL face cititul (web) sa nu se
    # blocheze in timp ce scrie ingestul.
    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _record) -> None:  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    if url is None or _engine is None:
        _engine = engine
    return engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _Session


@contextmanager
def sesiune() -> Iterator[Session]:
    """Sesiune tranzactionala: commit la iesire normala, rollback la exceptie."""
    s = get_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
