"""Ruta /sala/{id} -- gradul de ocupare al unei sali."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from orar.db.models import Ora, Sala
from orar.db.queries import gaseste_sala, ore_pentru_sala
from orar.domain.grid import ORA_MAX, ORA_MIN, ZILE, construieste_grila
from orar.domain.weeks import parse_interval_saptamani
from orar.web.deps import context_saptamana, get_db, saptamana_activa, templates

router = APIRouter(prefix="/sala", tags=["sala"])

#: Sloturi disponibile intr-o saptamana: 5 zile x 12 ore.
SLOTURI_TOTAL = len(ZILE) * (ORA_MAX - ORA_MIN)


@dataclass
class Conflict:
    """Doua activitati care ocupa aceeasi sala in acelasi timp, in aceeasi saptamana."""

    zi: str
    ora: str
    activitati: list[Ora]
    motiv: str


def _saptamani(o: Ora) -> set[int] | None:
    return parse_interval_saptamani(o.saptamani) if o.saptamani else None


def _chiar_se_suprapun(a: Ora, b: Ora) -> bool:
    """Se calca efectiv, sau doar par?

    Doua activitati in aceeasi sala si acelasi interval NU sunt in conflict daca una e in
    saptamani impare si cealalta in pare, sau daca intervalele lor de saptamani sunt
    disjuncte. Fara verificarea asta pagina ar semnala zeci de conflicte inexistente.
    """
    if a.frecventa and b.frecventa and a.frecventa != b.frecventa:
        return False
    sa, sb = _saptamani(a), _saptamani(b)
    return not (sa is not None and sb is not None and not (sa & sb))


def _detecteaza_conflicte(ore: list[Ora]) -> list[Conflict]:
    """Suprapuneri reale in aceeasi sala."""
    conflicte: list[Conflict] = []
    pe_zi: dict[str, list[Ora]] = {}
    for o in ore:
        pe_zi.setdefault(o.zi_saptamana, []).append(o)

    for zi, lot in pe_zi.items():
        for i, a in enumerate(lot):
            for b in lot[i + 1 :]:
                if a.ora_inceput >= b.ora_sfarsit or b.ora_inceput >= a.ora_sfarsit:
                    continue
                if not _chiar_se_suprapun(a, b):
                    continue
                motiv = (
                    "aceeași disciplină listată de două ori cu durate diferite"
                    if a.materie_id == b.materie_id
                    else "două activități diferite în același interval"
                )
                conflicte.append(
                    Conflict(
                        zi=zi,
                        ora=f"{max(a.ora_inceput, b.ora_inceput):%H:%M}",
                        activitati=[a, b],
                        motiv=motiv,
                    )
                )
    return conflicte


def _ocupare(ore: list[Ora]) -> tuple[dict[str, int], int]:
    """Cate sloturi de o ora sunt ocupate, per zi si in total."""
    pe_zi = dict.fromkeys(ZILE, 0)
    ocupate: set[tuple[str, int]] = set()
    for o in ore:
        for h in range(
            max(ORA_MIN, o.ora_inceput.hour), min(ORA_MAX, o.ora_sfarsit.hour or ORA_MAX)
        ):
            ocupate.add((o.zi_saptamana, h))
    for zi, _h in ocupate:
        if zi in pe_zi:
            pe_zi[zi] += 1
    return pe_zi, len(ocupate)


@router.get("", response_class=HTMLResponse)
def listeaza_sali(request: Request, s: Session = Depends(get_db)) -> HTMLResponse:
    sali = list(s.execute(select(Sala).order_by(Sala.tip, Sala.nume)).scalars())
    ocupari = {}
    for sala in sali:
        _, total = _ocupare(ore_pentru_sala(s, sala.id))
        ocupari[sala.id] = total
    return templates.TemplateResponse(
        request=request,
        name="sali.html",
        context={
            **context_saptamana(s=s),
            "sali": sali,
            "ocupari": ocupari,
            "sloturi_total": SLOTURI_TOTAL,
        },
    )


@router.get("/{identificator}", response_class=HTMLResponse)
def afiseaza_sala(
    request: Request,
    identificator: str,
    doar_saptamana: bool = Query(
        False, alias="saptamana", description="doar activitatile din saptamana curenta"
    ),
    zi: date | None = Query(None),
    s: Session = Depends(get_db),
) -> HTMLResponse:
    sala = gaseste_sala(s, identificator)
    if sala is None:
        raise HTTPException(status_code=404, detail=f"Nu există sala {identificator!r}")

    ore = ore_pentru_sala(s, sala.id)
    ctx_sapt = context_saptamana(zi, s)
    sapt = saptamana_activa(ctx_sapt)
    grila = construieste_grila(
        ore,
        saptamana=sapt,
        doar_saptamana_curenta=doar_saptamana and sapt is not None,
    )
    pe_zi, total_ocupate = _ocupare(ore)

    return templates.TemplateResponse(
        request=request,
        name="sala.html",
        context={
            **ctx_sapt,
            "sala": sala,
            "grila": grila,
            "total": len(ore),
            "ocupare_pe_zi": pe_zi,
            "ocupate": total_ocupate,
            "sloturi_total": SLOTURI_TOTAL,
            "procent": round(100 * total_ocupate / SLOTURI_TOTAL),
            "conflicte": _detecteaza_conflicte(ore),
            "filtru_saptamana": doar_saptamana,
            "ore_pe_zi": ORA_MAX - ORA_MIN,
        },
    )
