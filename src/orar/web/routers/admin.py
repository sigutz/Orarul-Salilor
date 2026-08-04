"""Coada de verificare: activitatile pe care extragerea nu le-a putut confirma.

De ce e o pagina, nu un raport in log
-------------------------------------
Lexiconul spune *ca* nu recunoaste un camp, dar nu si care e raspunsul corect. Singurul
lucru care lamureste asta e imaginea. Deci pagina pune decupajul celulei -- taiat exact din
captura din care a fost citita, prin `SURSA_PAGINA` + `SURSA_BBOX` -- langa valorile propuse.
Fara decupaj, ecranul ar cere sa ai incredere fix acolo unde am spus ca nu avem.

Ordinea cozii
-------------
Intai activitatile cu campuri pe care vocabularul le-a respins, apoi cele cu increderea cea
mai mica. Scorul brut al recunoasterii nu e un criteriu bun singur: sta pe la 0.7-0.9 chiar
si pe citiri perfecte, deci ar ineca lista in celule bune.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orar.db.models import Ora
from orar.web.deps import context_saptamana, get_db, templates

router = APIRouter(prefix="/admin", tags=["admin"])

#: Unde stau capturile din care s-a citit. Configurabil pentru cand baza si imaginile
#: ajung pe masini diferite.
DIRECTOR_CAPTURI = Path("data/screenshots")


@router.get("/review", response_class=HTMLResponse)
def review(
    request: Request,
    prag: float = Query(0.75, ge=0.0, le=1.0),
    limita: int = Query(100, ge=1, le=500),
    s: Session = Depends(get_db),
) -> HTMLResponse:
    """Activitatile de verificat, cele mai indoielnice intai."""
    candidate = list(
        s.scalars(
            select(Ora)
            .where(Ora.sursa_bbox.is_not(None))
            .where((Ora.campuri_nesigure.is_not(None)) | (Ora.confidence < prag))
            .order_by(Ora.campuri_nesigure.is_(None), Ora.confidence)
            .limit(limita)
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            **context_saptamana(s=s),
            "ore": candidate,
            "prag": prag,
            "total_nesigure": s.scalar(
                select(func.count()).select_from(Ora).where(Ora.campuri_nesigure.is_not(None))
            ),
            "total_cu_provenienta": s.scalar(
                select(func.count()).select_from(Ora).where(Ora.sursa_bbox.is_not(None))
            ),
            "director_lipsa": not DIRECTOR_CAPTURI.is_dir(),
        },
    )


def _gaseste_captura(sursa: str) -> Path | None:
    """Imaginea din care s-a citit activitatea.

    `SURSA_PAGINA` tine calea relativa la radacina capturilor (`sem2-grupe/pag_016.png`),
    dar randurile scrise inainte de asta au doar numele fisierului -- pentru ele mai cautam
    o data in subdirectoare, ca sa nu ramana fara decupaj dupa o actualizare.
    """
    cale = DIRECTOR_CAPTURI / sursa
    if cale.is_file():
        return cale
    nume = Path(sursa).name
    return next((p for p in DIRECTOR_CAPTURI.rglob(nume) if p.is_file()), None)


@router.get("/decupaj/{ora_id}")
def decupaj(ora_id: int, s: Session = Depends(get_db)) -> Response:
    """Decupajul celulei din care a fost citita activitatea."""
    ora = s.get(Ora, ora_id)
    if ora is None or not ora.sursa_bbox or not ora.sursa_pagina:
        raise HTTPException(404, "activitatea nu are provenienta pastrata")

    cale = _gaseste_captura(ora.sursa_pagina)
    if cale is None:
        raise HTTPException(
            404,
            f"captura {ora.sursa_pagina} nu mai e pe disc; ruleaza din nou `orar sincronizeaza`",
        )
    try:
        cutie = tuple(int(v) for v in ora.sursa_bbox.split(","))
    except ValueError as e:
        raise HTTPException(500, f"bbox stricat: {ora.sursa_bbox!r}") from e
    if len(cutie) != 4:
        raise HTTPException(500, f"bbox stricat: {ora.sursa_bbox!r}")

    from PIL import Image

    tampon = io.BytesIO()
    with Image.open(cale) as im:
        im.crop(cutie).save(tampon, format="PNG")
    return Response(tampon.getvalue(), media_type="image/png")
