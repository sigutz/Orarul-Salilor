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


def _context_cont(request) -> dict[str, object]:  # noqa: ANN001
    """Ce are nevoie bara de sus pe *fiecare* pagina: cine e logat si tokenul CSRF.

    Cheia e `cont`, nu `user`: procesoarele de context ale lui Starlette se aplica **peste**
    contextul rutei, deci un `user` de aici l-ar inlocui pe cel viu al rutei cu unul detasat
    de sesiune, iar sabloanele care umbla la relatii (`user.grupa`) ar crapa. Asa fiecare
    isi pastreaza rolul: `cont` pentru bara, `user` pentru pagina.

    Nu deschide el sesiune la baza: valoarea o pune `auth.utilizator_curent`, care ruleaza
    ca dependinta pe toata aplicatia si foloseste `get_db` -- deci si testele care inlocuiesc
    baza vad acelasi lucru ca rutele.
    """
    if "session" not in request.scope:
        return {"cont": None, "csrf": ""}
    from orar.web.auth import token_csrf

    return {"cont": getattr(request.state, "cont", None), "csrf": token_csrf(request)}


templates = Jinja2Templates(directory=str(AICI / "templates"), context_processors=[_context_cont])

#: Ancorele publicate de FMI pentru semestrul II 2025-2026, ca rezerva. Sunt doua, la
#: distanta de doua saptamani calendaristice dar una academica -- vacanta de Paste dintre
#: ele. Cele reale vin din baza, unde le scrie `orar sincronizeaza`; astea raman pentru o
#: instalare in care watcher-ul n-a rulat inca, ca interfata sa nu porneasca fara calendar.
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


def calendar(s: Session | None = None) -> CalendarAcademic:
    """Calendarul academic: din baza daca watcher-ul a rulat, altfel cel de rezerva."""
    if s is None:
        return CALENDAR
    from orar.worker.sync import calendar_din_baza

    return calendar_din_baza(s) or CALENDAR


def context_saptamana(zi: date | None = None, s: Session | None = None) -> dict[str, object]:
    """Numarul si paritatea saptamanii pentru o data (implicit azi)."""
    zi = zi or date.today()
    sapt = calendar(s).saptamana(zi)
    return {
        "azi": zi,
        "saptamana": sapt,
        "numar_saptamana": sapt.numar if sapt else None,
        "paritate": sapt.paritate if sapt else None,
        "in_semestru": sapt is not None,
        "sursa_orar": sursa_curenta(s),
    }


def sursa_curenta(s: Session | None):  # noqa: ANN201
    """Orarul de grupe pe care il urmarim, ca sa aratam cat de proaspete sunt datele."""
    if s is None:
        return None
    from sqlalchemy import select

    from orar.db.models import SursaOrar

    return s.scalar(
        select(SursaOrar)
        .where(SursaOrar.fel == "grupe")
        .order_by(SursaOrar.actualizat.desc().nullslast())
        .limit(1)
    )


def saptamana_activa(ctx: dict[str, object]):
    """Saptamana de folosit la filtrarea grilei, sau None cand nu se poate filtra.

    In vacanta nu exista numar academic, deci orice filtrare ar stinge activitati la
    intamplare. Atunci nu filtram deloc si aratam orarul complet.
    """
    return ctx.get("saptamana")
