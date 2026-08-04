"""Pagina principala: cautare si navigare in arborele de formatiuni."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orar.db.models import Grupa, Ora, Sala, User
from orar.domain.hierarchy import DENUMIRI_SPECIALIZARE
from orar.web.auth import utilizator_curent
from orar.web.deps import context_saptamana, get_db, templates

router = APIRouter(tags=["index"])


@router.get("/", response_class=HTMLResponse)
def acasa(
    request: Request,
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
) -> HTMLResponse:
    # Cine si-a ales o grupa nu are de ce sa treaca prin cautare: il ducem direct la orarul
    # lui. `/acasa` ramane pentru cand chiar vrea lista intreaga.
    if user is not None and user.grupa is not None:
        return RedirectResponse(f"/grupa/{user.grupa.slug}", status_code=303)
    return _pagina_acasa(request, s, user)


@router.get("/acasa", response_class=HTMLResponse)
def toate(
    request: Request,
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
) -> HTMLResponse:
    """Lista completa, chiar daca ai o grupa preferata."""
    return _pagina_acasa(request, s, user)


def _pagina_acasa(request: Request, s: Session, user: User | None) -> HTMLResponse:
    specializari = list(
        s.execute(
            select(Grupa)
            .where(Grupa.tip == "specializare")
            .order_by(Grupa.specializare, Grupa.an_studiu)
        ).scalars()
    )
    # Grupele reale, gata de afisat sub fiecare specializare.
    grupe = list(
        s.execute(select(Grupa).where(Grupa.tip == "grupa").order_by(Grupa.nume)).scalars()
    )
    pachete = list(
        s.execute(select(Grupa).where(Grupa.tip == "optional").order_by(Grupa.nume)).scalars()
    )
    sali = list(s.execute(select(Sala).where(Sala.tip == "fizica").order_by(Sala.nume)).scalars())

    pe_specializare: dict[int, list[Grupa]] = {}
    for g in grupe:
        # urcam la nodul de specializare (grupa -> serie -> specializare)
        nod = g
        while nod.parinte is not None and nod.tip != "specializare":
            nod = nod.parinte
        if nod.tip == "specializare":
            pe_specializare.setdefault(nod.id, []).append(g)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **context_saptamana(s=s),
            "user": user,
            "specializari": specializari,
            "pe_specializare": pe_specializare,
            "pachete": pachete,
            "sali": sali,
            "total_ore": s.scalar(select(func.count()).select_from(Ora)),
            "denumiri": DENUMIRI_SPECIALIZARE,
        },
    )


@router.get("/cauta", response_class=HTMLResponse)
def cauta(
    request: Request,
    q: str = Query("", min_length=0),
    s: Session = Depends(get_db),
) -> HTMLResponse:
    """Cautare incrementala (HTMX) in grupe si sali."""
    termen = q.strip()
    grupe: list[Grupa] = []
    sali: list[Sala] = []
    if termen:
        tipar = f"%{termen}%"
        grupe = list(
            s.execute(
                select(Grupa)
                .where(Grupa.nume.ilike(tipar), Grupa.tip.in_(("grupa", "optional", "serie")))
                .order_by(Grupa.tip.desc(), Grupa.nume)
                .limit(12)
            ).scalars()
        )
        sali = list(
            s.execute(
                select(Sala).where(Sala.nume.ilike(tipar)).order_by(Sala.nume).limit(8)
            ).scalars()
        )

    return templates.TemplateResponse(
        request=request,
        name="_rezultate.html",
        context={"grupe": grupe, "sali": sali, "termen": termen},
    )
