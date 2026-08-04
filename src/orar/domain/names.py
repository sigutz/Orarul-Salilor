"""Potrivirea numelui prescurtat din celula cu numele intreg din titlul paginii.

Cele doua orare scriu acelasi om altfel. In celula, unde nu incape mult, aSc prescurteaza;
pe pagina lui de profesor scrie numele intreg. Perechile de mai jos sunt reale, luate din
sursa, si arata ca prescurtarea **nu** e "primul cuvant + prima litera a celui de-al doilea":

    Cheval H      <-  Cheval Andrei-Horatiu     initiala e a *ultimului* prenume
    Micluta M     <-  Micluta-Campeanu Marius   numele de familie e taiat la prima parte
    BanuDem. I    <-  Banu Demergian Iulia      numele de familie e lipit si taiat
    Marin Le      <-  Marin (Velcescu) Letitia  doua litere, plus numele de fata in paranteze
    Grecu AE      <-  Grecu Alina-Elena         cate o initiala pentru fiecare prenume
    Vrinceanu RT  <-  Vrinceanu Radu-Tudor      la fel

Regula care le acopera pe toate:

    prescurtarea = <prefix al numelui de familie lipit> <initiale, in ordine>

Initialele se potrivesc ca **subsecventa**: fiecare litera prinde cate un prenume, in ordine,
dar pot ramane prenume nefolosite -- `Cheval H` sare peste Andrei si prinde Horatiu.

Numele intreg si cel prescurtat se citesc cu functii **diferite**, nu cu o euristica pe
lungime: apelantul stie mereu care e care, iar "Ion" are exact atatea litere cat au si
initialele duble, deci o singura functie ar trebui sa ghiceasca -- si ar gresi.

Ambiguitatea ramane posibila: `Popescu A` se potriveste si cu Adrian, si cu Ana. Aceea e in
sursa, nu in cod; apelantul decide ce face cand raman mai multi candidati.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["tokenuri", "se_potrivesc", "potriveste"]

#: Confuziile pe care recunoasterea le face la fontul asta si care apar in nume:
#: `Iulia` citit `lulia`, `Ion` citit `lon`. Le colapsam doar pentru comparatie.
_CONFUZII = str.maketrans({"l": "i", "1": "i", "|": "i", "0": "o", "5": "s"})
#: Numele de fata, scris in paranteze, nu apare in prescurtare.
_RE_PARANTEZE = re.compile(r"\([^)]*\)")
_RE_NELITERE = re.compile(r"[^a-z]+")


def _fara_diacritice(text: str) -> str:
    descompus = unicodedata.normalize("NFD", text)
    return "".join(c for c in descompus if unicodedata.category(c) != "Mn")


def tokenuri(nume: str) -> list[str]:
    """Cuvintele numelui, normalizate pentru comparatie."""
    curat = _RE_PARANTEZE.sub(" ", _fara_diacritice(nume).lower())
    curat = curat.replace("-", " ").replace(".", " ")
    bucati = (_RE_NELITERE.sub("", p) for p in curat.split())
    return [t.translate(_CONFUZII) for t in bucati if t]


def _prescurtat(nume: str) -> tuple[str, str]:
    """(familie_lipita, initiale) dintr-un nume prescurtat, ex. `BanuDem. I` -> `banudem`, `i`."""
    t = tokenuri(nume)
    if not t:
        return "", ""
    if len(t) == 1:
        return t[0], ""
    return "".join(t[:-1]), t[-1]


def _intreg(nume: str) -> tuple[str, tuple[str, ...]]:
    """(familie, prenume) dintr-un nume intreg. Primul token e familia, restul prenume."""
    t = tokenuri(nume)
    if not t:
        return "", ()
    return t[0], tuple(t[1:])


def _initialele_se_potrivesc(initiale: str, prenume: tuple[str, ...]) -> bool:
    """Doua citiri posibile pentru un grup de litere, si amandoua apar in sursa.

    `Grecu AE` <- `Grecu Alina-Elena`: cate o initiala pentru fiecare prenume, in ordine.
    `Marin Le` <- `Marin Letitia`:     primele doua litere ale *unui singur* prenume.

    Din text nu se poate sti care din doua a fost, deci acceptam oricare. Nu slabeste mult
    filtrul: `Toma AS` tot nu se potriveste cu `Toma Stefania Anda`, fiindca nici ordinea
    initialelor, nici vreun prefix nu ies.
    """
    if any(p.startswith(initiale) for p in prenume):
        return True
    ramase = list(prenume)
    for litera in initiale:
        while ramase and not ramase[0].startswith(litera):
            ramase.pop(0)
        if not ramase:
            return False
        ramase.pop(0)
    return True


def se_potrivesc(prescurtat: str, intreg: str) -> bool:
    """`Cheval H` si `Cheval Andrei-Horatiu` sunt acelasi om?"""
    fam_scurt, initiale = _prescurtat(prescurtat)
    fam_lung, prenume = _intreg(intreg)
    if not fam_scurt or not fam_lung:
        return False

    # Numele de familie se compara pe **granita de cuvant**, nu pe orice prefix: `Micluta`
    # tine loc lui `Micluta-Campeanu` fiindca taie exact intre cuvinte, dar `Ion` nu are voie
    # sa prinda `Ionescu` -- ar fi alt om. Singura taiere in mijlocul unui cuvant o acceptam
    # cand prescurtarea e mai *lunga* decat primul cuvant si continua in al doilea:
    # `BanuDem` <- `Banu` + `Demergian`.
    for k in range(len(prenume) + 1):
        familie = fam_lung + "".join(prenume[:k])
        urmator = familie + (prenume[k] if k < len(prenume) else "")
        exact = familie == fam_scurt
        trunchiat = len(fam_scurt) > len(familie) and urmator.startswith(fam_scurt)
        if not (exact or trunchiat):
            continue
        # Cand prescurtarea a inghitit si cuvantul urmator, el nu mai e prenume.
        ramase = prenume[k + 1 :] if trunchiat else prenume[k:]
        if not initiale or _initialele_se_potrivesc(initiale, ramase):
            return True
    return False


def potriveste(prescurtat: str, intregi) -> list[str]:  # noqa: ANN001
    """Toate numele intregi care se potrivesc cu prescurtarea. Mai multe = ambiguu in sursa."""
    return [x for x in intregi if se_potrivesc(prescurtat, x)]
