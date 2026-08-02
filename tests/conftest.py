"""Fixturi comune.

Baza de test se construieste o singura data pe sesiune, dintr-un SQLite in memorie
incarcat din setul golden. E suficient de rapid (~1 s) si testeaza exact drumul real:
JSON -> loader -> consolidare -> interogari.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from orar.db.models import Base
from orar.ingest.consolidate import consolideaza
from orar.ingest.load import incarca_pagini

RADACINA = Path(__file__).resolve().parent
GOLDEN = RADACINA / "golden" / "date.json"
FIXTURI = RADACINA / "fixtures"


@pytest.fixture(scope="session")
def pagini_golden() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _engine_memorie():
    """SQLite in memorie, vizibil din toate firele de executie.

    Implicit, fiecare *conexiune* la `sqlite://` primeste propria baza goala, iar
    TestClient ruleaza aplicatia pe alt fir -- deci ar vedea o baza fara tabele.
    StaticPool tine o singura conexiune partajata.
    """
    return create_engine(
        "sqlite://",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture(scope="session")
def _engine():
    engine = _engine_memorie()

    @event.listens_for(engine, "connect")
    def _fk(conn, _rec):  # noqa: ANN001
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="session")
def _sesiune_incarcata(_engine, pagini_golden) -> Session:
    """Baza cu golden-ul incarcat SI consolidat -- starea reala a aplicatiei.

    Ingestul ruleaza in sesiunea lui, apoi testele primesc una noua. Asa e si in
    productie (worker-ul scrie, web-ul citeste), si asa nu putem trece din greseala
    teste care de fapt citesc obiecte ramase in identity map-ul ingestului.
    """
    Sesiune = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    with Sesiune() as ingest:
        incarca_pagini(ingest, pagini_golden)
        consolideaza(ingest, an_universitar="2025-2026")
        ingest.commit()
    return Sesiune()


@pytest.fixture
def db(_sesiune_incarcata) -> Session:
    return _sesiune_incarcata


@pytest.fixture(scope="session")
def sesiune_neconsolidata(_engine, pagini_golden) -> Session:
    """Sesiune separata, fara consolidare -- pentru testele care o masoara."""
    engine = _engine_memorie()
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    incarca_pagini(s, pagini_golden)
    s.commit()
    return s
