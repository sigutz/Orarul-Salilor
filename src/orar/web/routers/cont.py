"""Inregistrare, autentificare si preferintele contului.

La ce foloseste contul
----------------------
La un singur lucru: sa nu mai cauti de fiecare data. Cine e logat intra pe `/` si vede direct
orarul grupei lui, filtrat pe semigrupa si pe optionalele la care chiar e inscris. Restul
aplicatiei ramane publica -- orarul e informatie publica si nu ceri cont ca sa vezi o sala
libera.

De aceea `utilizator_curent` nu blocheaza nimic: intoarce `None` si paginile merg mai departe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orar.db.models import Grupa, User, UserOptional
from orar.domain.hierarchy import normalizeaza_semigrupa
from orar.web.auth import (
    PAROLA_MINIM,
    autentifica,
    deconecteaza,
    hash_parola,
    logheaza,
    normalizeaza_email,
    token_csrf,
    utilizator_curent,
    verifica_csrf,
)
from orar.web.deps import context_saptamana, get_db, templates

router = APIRouter(tags=["cont"])


def _pagina(
    request: Request,
    sablon: str,
    s: Session,
    user: User | None = None,
    **extra,  # noqa: ANN003
) -> HTMLResponse:
    """Randeaza un sablon de cont. `sablon`, nu `nume`: `nume` e un camp din formular."""
    stare = extra.pop("status_code", 200)
    return templates.TemplateResponse(
        request=request,
        name=sablon,
        context={
            **context_saptamana(s=s),
            "user": user,
            "csrf": token_csrf(request),
            **extra,
        },
        status_code=stare,
    )


# ------------------------------------------------------------------ intrare


@router.get("/intrare", response_class=HTMLResponse)
def formular_intrare(
    request: Request,
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
) -> HTMLResponse:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _pagina(request, "intrare.html", s)


@router.post("/intrare")
def intra(
    request: Request,
    email: str = Form(...),
    parola: str = Form(...),
    csrf: str = Form(""),
    s: Session = Depends(get_db),
):  # noqa: ANN201
    if not verifica_csrf(request, csrf):
        return _pagina(request, "intrare.html", s, eroare="Sesiune expirată. Încearcă din nou.")
    user = autentifica(s, email, parola)
    if user is None:
        # Acelasi mesaj pentru cont inexistent si parola gresita.
        return _pagina(
            request,
            "intrare.html",
            s,
            eroare="Email sau parolă greșită.",
            email=email,
            status_code=401,
        )
    logheaza(request, user)
    return RedirectResponse("/", status_code=303)


@router.post("/iesire")
def iese(request: Request, csrf: str = Form("")):  # noqa: ANN201
    if verifica_csrf(request, csrf):
        deconecteaza(request)
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------- inregistrare


@router.get("/inregistrare", response_class=HTMLResponse)
def formular_inregistrare(
    request: Request,
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
) -> HTMLResponse:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _pagina(request, "inregistrare.html", s, grupe=_grupe_alegibile(s))


@router.post("/inregistrare")
def inregistreaza(
    request: Request,
    nume: str = Form(...),
    email: str = Form(...),
    parola: str = Form(...),
    grupa_id: str = Form(""),
    csrf: str = Form(""),
    s: Session = Depends(get_db),
):  # noqa: ANN201
    def inapoi(eroare: str, stare: int = 400):  # noqa: ANN202
        return _pagina(
            request,
            "inregistrare.html",
            s,
            grupe=_grupe_alegibile(s),
            eroare=eroare,
            nume=nume,
            email=email,
            grupa_id=grupa_id,
            status_code=stare,
        )

    if not verifica_csrf(request, csrf):
        return inapoi("Sesiune expirată. Încearcă din nou.")
    if not nume.strip():
        return inapoi("Numele nu poate fi gol.")
    if "@" not in email:
        return inapoi("Adresa de email nu pare validă.")
    if len(parola) < PAROLA_MINIM:
        return inapoi(f"Parola trebuie să aibă cel puțin {PAROLA_MINIM} caractere.")

    exista = s.scalar(select(User).where(func.lower(User.email) == normalizeaza_email(email)))
    if exista is not None:
        return inapoi("Există deja un cont cu adresa asta.", 409)

    user = User(
        nume=nume.strip(),
        email=normalizeaza_email(email),
        parola_hash=hash_parola(parola),
        grupa_id=int(grupa_id) if grupa_id.isdigit() else None,
    )
    s.add(user)
    s.commit()
    logheaza(request, user)
    return RedirectResponse("/", status_code=303)


# -------------------------------------------------------------- preferinte


@router.get("/preferinte", response_class=HTMLResponse)
def formular_preferinte(
    request: Request,
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
) -> HTMLResponse:
    if user is None:
        return RedirectResponse("/intrare", status_code=303)
    return _pagina(
        request,
        "preferinte.html",
        s,
        user=user,
        grupe=_grupe_alegibile(s),
        pachete=_optionale_pentru(s, user),
        inscris={g.id for g in user.optionale},
    )


@router.post("/preferinte")
def salveaza_preferinte(
    request: Request,
    grupa_id: str = Form(""),
    semigrupa: str = Form(""),
    optional: list[str] = Form(default=[]),
    csrf: str = Form(""),
    s: Session = Depends(get_db),
    user: User | None = Depends(utilizator_curent),
):  # noqa: ANN201
    if user is None:
        return RedirectResponse("/intrare", status_code=303)
    if not verifica_csrf(request, csrf):
        return RedirectResponse("/preferinte", status_code=303)

    user.grupa_id = int(grupa_id) if grupa_id.isdigit() else None
    user.semigrupa = normalizeaza_semigrupa(semigrupa)

    # Inlocuim inscrierile, dar numai cu pachete care exista si sunt intr-adevar optionale;
    # altfel un `<input>` fabricat ar putea lega contul de orice nod din arbore.
    valide = {g.id for g in _optionale_pentru(s, user)}
    cerute = {int(x) for x in optional if x.isdigit()} & valide
    s.query(UserOptional).filter(UserOptional.user_id == user.id).delete()
    for gid in cerute:
        s.add(UserOptional(user_id=user.id, grupa_id=gid))
    s.commit()
    return RedirectResponse("/preferinte?salvat=1", status_code=303)


# ----------------------------------------------------------------- ajutoare


def _grupe_alegibile(s: Session) -> list[Grupa]:
    """Formatiunile la care se poate inscrie cineva: grupe reale, nu serii sau pachete."""
    return list(s.scalars(select(Grupa).where(Grupa.tip == "grupa").order_by(Grupa.nume)))


def _optionale_pentru(s: Session, user: User) -> list[Grupa]:
    """Pachetele de optionale legate de grupa preferata, prin lantul ei ierarhic.

    Fara grupa aleasa n-avem cum sti ce optionale i se potrivesc, deci nu aratam nimic --
    mai bine o lista goala decat toate cele 25 de pachete din facultate.
    """
    if user.grupa_id is None:
        return []
    from orar.db.queries import ids_relevante

    ids = ids_relevante(s, user.grupa_id)
    pachete = s.scalars(select(Grupa).where(Grupa.tip == "optional").order_by(Grupa.nume)).all()
    return [g for g in pachete if _atinge(s, g, ids)]


def _atinge(s: Session, pachet: Grupa, ids: set[int]) -> bool:
    """Pachetul are vreo ora legata de formatiunile din lantul studentului?"""
    from orar.db.models import Ora, OraGrupa

    return bool(
        s.scalar(
            select(Ora.id)
            .join(OraGrupa, OraGrupa.ora_id == Ora.id)
            .where(Ora.grupa_id == pachet.id, OraGrupa.grupa_id.in_(ids))
            .limit(1)
        )
    )
