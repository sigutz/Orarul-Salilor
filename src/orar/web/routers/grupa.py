"""Ruta /grupa/{id} -- orarul unei formatiuni, cu mostenire ierarhica."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from orar.db.models import Grupa, Ora
from orar.db.queries import gaseste_grupa, ids_descendenti, ids_stramosi, ore_pentru_grupa
from orar.domain.grid import Provenienta, construieste_grila
from orar.web.deps import context_saptamana, get_db, saptamana_activa, templates

router = APIRouter(prefix="/grupa", tags=["grupa"])


def _clasifica(
    ore: list[Ora], grupa: Grupa, stramosi: set[int], descendenti: set[int]
) -> tuple[dict[int, Provenienta], dict[int, str]]:
    """De unde vine fiecare ora, raportat la grupa ceruta.

    Pentru orele partajate NU numim grupa-proprietar: un student din 244 nu are de ce sa
    vada "de la 241" pentru un curs pe care il au amandoua. Le aratam drept comune.
    """
    provenienta: dict[int, Provenienta] = {}
    surse: dict[int, str] = {}

    for o in ore:
        if o.grupa_id == grupa.id:
            provenienta[o.id] = Provenienta.PROPRIE
        elif o.grupa_id in stramosi:
            provenienta[o.id] = Provenienta.MOSTENITA
            surse[o.id] = o.grupa.nume
        elif o.grupa_id in descendenti:
            provenienta[o.id] = Provenienta.SEMIGRUPA
            surse[o.id] = o.semigrupa.replace("_", " ") if o.semigrupa else o.grupa.nume
        else:
            provenienta[o.id] = Provenienta.PARTAJATA
            surse[o.id] = o.grupa.nume if o.grupa.tip == "optional" else "activitate comună"

    return provenienta, surse


@router.get("/{identificator}", response_class=HTMLResponse)
def afiseaza_grupa(
    request: Request,
    identificator: str,
    doar_saptamana: bool = Query(False, alias="saptamana", description="doar activitatile din saptamana curenta"),
    zi: date | None = Query(None, description="data de referinta (implicit azi)"),
    semigrupa: str | None = Query(None, description="filtreaza pe semigrupa, ex. Gr_1"),
    s: Session = Depends(get_db),
) -> HTMLResponse:
    grupa = gaseste_grupa(s, identificator)
    if grupa is None:
        raise HTTPException(status_code=404, detail=f"Nu există formațiunea {identificator!r}")

    stramosi = ids_stramosi(s, grupa.id) - {grupa.id}
    descendenti = ids_descendenti(s, grupa.id) - {grupa.id}
    ore = ore_pentru_grupa(s, grupa.id)

    if semigrupa:
        ore = [o for o in ore if o.semigrupa in (None, semigrupa)]

    provenienta, surse = _clasifica(ore, grupa, stramosi, descendenti)
    ctx_sapt = context_saptamana(zi)
    sapt = saptamana_activa(ctx_sapt)
    grila = construieste_grila(
        ore,
        provenienta=provenienta,
        surse=surse,
        saptamana=sapt,
        doar_saptamana_curenta=doar_saptamana and sapt is not None,
    )

    lant = []
    cur: Grupa | None = grupa.parinte
    while cur is not None:
        lant.append(cur)
        cur = cur.parinte
    lant.reverse()

    semigrupe = sorted(
        {o.semigrupa for o in ore if o.semigrupa},
    )

    return templates.TemplateResponse(
        request=request,
        name="grupa.html",
        context={
            **ctx_sapt,
            "grupa": grupa,
            "lant": lant,
            "copii": sorted(
                (s.get(Grupa, i) for i in descendenti), key=lambda g: g.nume if g else ""
            ),
            "grila": grila,
            "total": len(ore),
            "filtru_saptamana": doar_saptamana,
            "semigrupa_activa": semigrupa,
            "semigrupe": semigrupe,
            "Provenienta": Provenienta,
        },
    )
