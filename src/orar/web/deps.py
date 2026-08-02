"""Dependinte partajate de rute: sesiune, sabloane, contextul saptamanii.

Traiesc separat de `app.py` ca routerele sa le poata importa fara import circular.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from orar.db.session import get_sessionmaker
from orar.domain.weeks import AncoraSaptamana, CalendarAcademic, Paritate

AICI = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(AICI / "templates"))

#: Ancorele publicate de FMI pentru semestrul II 2025-2026. Sunt doua, la distanta de
#: doua saptamani calendaristice dar una academica -- vacanta de Paste dintre ele.
#: In Etapa 6 watcher-ul le citeste direct de pe site si le pastreaza in baza.
CALENDAR = CalendarAcademic(
    ancore=[
        AncoraSaptamana(inceput=date(2026, 4, 6), numar=7, paritate=Paritate.IMPARA),
        AncoraSaptamana(inceput=date(2026, 4, 20), numar=8, paritate=Paritate.PARA),
    ]
)


def get_db() -> Iterator[Session]:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


def context_saptamana(zi: date | None = None) -> dict[str, object]:
    """Numarul si paritatea saptamanii pentru o data (implicit azi)."""
    zi = zi or date.today()
    sapt = CALENDAR.saptamana(zi)
    return {
        "azi": zi,
        "saptamana": sapt,
        "numar_saptamana": sapt.numar if sapt else None,
        "paritate": sapt.paritate if sapt else None,
        "in_semestru": sapt is not None,
    }


def saptamana_activa(ctx: dict[str, object]):
    """Saptamana de folosit la filtrarea grilei, sau None cand nu se poate filtra.

    In vacanta nu exista numar academic, deci orice filtrare ar stinge activitati la
    intamplare. Atunci nu filtram deloc si aratam orarul complet.
    """
    return ctx.get("saptamana")
