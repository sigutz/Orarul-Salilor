"""Conturi: parole, sesiuni, utilizatorul curent.

Parolele
--------
`hashlib.scrypt`, din biblioteca standard -- fara inca o dependinta care sa aiba nevoie de
compilator. Parametrii se scriu **in hash**, nu doar in cod: cand vom vrea sa-i crestem,
conturile vechi raman verificabile si se pot rescrie la urmatoarea autentificare reusita.

Formatul: `scrypt$n$r$p$sare_hex$hash_hex`.

Ce **nu** face modulul asta
---------------------------
Nu limiteaza incercarile de autentificare. Aplicatia e read-only pentru date publice si
conturile tin doar preferinte (grupa, semigrupa, optionale), deci mizele sunt mici; dar
daca ajunge sa fie expusa public, limitarea trebuie adaugata in fata (nginx, fail2ban).

Mesajul de eroare e acelasi pentru "nu exista contul" si "parola gresita": altfel formularul
ar spune oricui daca o adresa e inregistrata sau nu.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orar.db.models import User
from orar.web.deps import get_db

log = logging.getLogger(__name__)

__all__ = [
    "hash_parola",
    "verifica_parola",
    "autentifica",
    "utilizator_curent",
    "cheie_secreta",
    "token_csrf",
    "verifica_csrf",
    "PAROLA_MINIM",
]

#: Parametrii scrypt de azi. N=2^15 cere ~32 MB si zeci de milisecunde -- destul de scump
#: pentru un atac cu dictionar, destul de ieftin pentru o autentificare.
_N, _R, _P = 2**15, 8, 1


def _memorie(n: int, r: int, p: int) -> int:
    """Plafonul de memorie cerut lui OpenSSL.

    Implicit el permite 32 MB, iar scrypt cu N=2^15 si r=8 are nevoie de 128*N*r = 33.5 MB,
    deci fara plafonul asta functia arunca "memory limit exceeded". Il calculam din parametri
    si ii lasam loc, ca sa mearga si hash-urile vechi cand vom creste N.
    """
    return 128 * n * r * max(1, p) * 2


#: Sub atat nu acceptam parola. Lungimea bate complexitatea; nu cerem simboluri.
PAROLA_MINIM = 10

_CHEIE_SESIUNE = "user_id"
_CHEIE_CSRF = "csrf"


def cheie_secreta() -> str:
    """Cheia cu care se semneaza cookie-ul de sesiune.

    Din `ORAR_SECRET`. Fara ea generam una la pornire -- comod in dezvoltare, dar sesiunile
    se pierd la fiecare repornire si nu merge cu mai multe procese, deci avertizam.
    """
    cheie = os.getenv("ORAR_SECRET", "").strip()
    if cheie:
        return cheie
    log.warning(
        "ORAR_SECRET nu e setat: generez o cheie temporara. Sesiunile se pierd la repornire "
        "si nu sunt valabile intre procese. In productie: ORAR_SECRET=$(openssl rand -hex 32)"
    )
    return secrets.token_hex(32)


# --------------------------------------------------------------------- parole


def hash_parola(parola: str) -> str:
    sare = secrets.token_bytes(16)
    brut = hashlib.scrypt(parola.encode(), salt=sare, n=_N, r=_R, p=_P, maxmem=_memorie(_N, _R, _P))
    return f"scrypt${_N}${_R}${_P}${sare.hex()}${brut.hex()}"


def verifica_parola(parola: str, stocat: str | None) -> bool:
    """Compara in timp constant. `stocat` gol => False, fara sa arunce."""
    if not stocat:
        return False
    try:
        schema, n, r, p, sare_hex, hash_hex = stocat.split("$")
        if schema != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        brut = hashlib.scrypt(
            parola.encode(),
            salt=bytes.fromhex(sare_hex),
            n=n,
            r=r,
            p=p,
            maxmem=_memorie(n, r, p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(brut.hex(), hash_hex)


def normalizeaza_email(email: str) -> str:
    return email.strip().lower()


def autentifica(s: Session, email: str, parola: str) -> User | None:
    """Contul, daca parola se potriveste. Altfel None -- fara sa spunem care parte a picat."""
    user = s.scalar(select(User).where(func.lower(User.email) == normalizeaza_email(email)))
    if user is None:
        # Consumam acelasi timp ca o verificare reala, ca sa nu se poata deduce din durata
        # raspunsului daca adresa exista.
        verifica_parola(parola, hash_parola("consuma-acelasi-timp"))
        return None
    return user if verifica_parola(parola, user.parola_hash) else None


# ------------------------------------------------------------------- sesiunea


def logheaza(request: Request, user: User) -> None:
    """Leaga sesiunea de cont. Regenereaza tokenul CSRF, ca sa nu fie refolosit."""
    request.session.clear()
    request.session[_CHEIE_SESIUNE] = user.id
    request.session[_CHEIE_CSRF] = secrets.token_urlsafe(24)


def deconecteaza(request: Request) -> None:
    request.session.clear()


def utilizator_curent(request: Request, s: Session = Depends(get_db)) -> User | None:
    """Contul din sesiune, sau None. Nu blocheaza: paginile publice raman publice.

    Ruleaza ca dependinta pe toata aplicatia, deci lasa in `request.state.cont` si numele
    de care are nevoie bara de sus -- altfel fiecare sablon ar trebui sa-l care prin context,
    sau procesorul de context ar deschide inca o sesiune, pe langa cea a rutei.
    """
    uid = request.session.get(_CHEIE_SESIUNE) if "session" in request.scope else None
    if uid is None:
        request.state.cont = None
        return None
    user = s.get(User, uid)
    if user is None:
        # Contul a fost sters intre timp; sesiunea nu mai are ce sa insemne.
        request.session.clear()
    request.state.cont = {"nume": user.nume, "id": user.id} if user else None
    return user


# ---------------------------------------------------------------------- CSRF


def token_csrf(request: Request) -> str:
    """Tokenul din sesiune, creat la prima cerere care are nevoie de el."""
    token = request.session.get(_CHEIE_CSRF)
    if not token:
        token = secrets.token_urlsafe(24)
        request.session[_CHEIE_CSRF] = token
    return token


def verifica_csrf(request: Request, trimis: str | None) -> bool:
    """Cookie-ul e `SameSite=Lax`, deci un POST din alt sit nici nu l-ar primi. Tokenul e

    a doua incuietoare, pentru cazurile in care browserul e mai permisiv decat credem."""
    asteptat = request.session.get(_CHEIE_CSRF)
    return bool(asteptat and trimis and hmac.compare_digest(asteptat, trimis))


@dataclass(frozen=True)
class Preferinte:
    """Ce filtreaza contul in interfata."""

    grupa_id: int | None
    semigrupa: str | None
    optionale: frozenset[int]

    @classmethod
    def din_user(cls, user: User | None) -> Preferinte:
        if user is None:
            return cls(None, None, frozenset())
        return cls(
            grupa_id=user.grupa_id,
            semigrupa=user.semigrupa,
            optionale=frozenset(g.id for g in user.optionale),
        )
