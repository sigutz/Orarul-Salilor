"""Legarea abrevierii din orar de denumirea intreaga din planul de invatamant.

Orarul scrie `StructDate`, planul scrie `Structuri de date`. Nu e o potrivire fuzzy de siruri
-- ar da rezultate aiurea pe abrevieri de doua litere -- ci una **structurala**, fiindca aSc
construieste abrevierea dupa o regula:

    Structuri de date                    -> StructDate      prefixe de cuvant, fara "de"
    Baze de date                         -> BD              doar initialele
    Programare orientata pe obiecte      -> POO             idem
    Arhitectura sistemelor de calcul     -> ArhSistCalcul   prefixe
    Geometrie si algebra liniara         -> Geom&AlgLin     "si" devine "&"
    Limbaje formale si automate          -> LbForm&Autom    `Lb` nu e prefix, e schelet

Regula unificata: **taiem abrevierea la majuscule** si cerem ca fiecare bucata sa fie o
*subsecventa* a cuvantului corespunzator din denumire, incepand cu aceeasi litera. Prefixul
(`Struct` in `structuri`) si scheletul de consoane (`Lb` in `limbaje`) sunt amandoua
subsecvente, deci o singura conditie le acopera pe amandoua.

Cuvintele de legatura (`de`, `si`, `pe`, `in`, `pentru`) nu apar niciodata in abreviere, deci
se scot inainte de comparatie.

Ce **nu** face: nu alege intre doua denumiri care se potrivesc la fel de bine. `potriveste`
le intoarce pe toate; cine cheama decide, iar ambiguitatea se raporteaza.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["bucati", "cuvinte_semnificative", "variante", "scor", "potriveste", "PRAG"]

#: Cuvinte care leaga, dar nu poarta inteles; aSc le sare cand construieste abrevierea.
STOPWORDS = frozenset(
    [
        "de",
        "a",
        "al",
        "ale",
        "ai",
        "la",
        "si",
        "in",
        "pe",
        "cu",
        "pentru",
        "din",
        "spre",
        "sub",
        "pre",
        "pri",
        "o",
        "un",
        "pt",
        "pentru",
        "pt.",
    ]
)

#: Sub atata potrivire nu legam disciplina de materie.
PRAG = 0.75

_RE_BUCATA = re.compile(r"[A-Z][a-z]*|[a-z]+|\d+")


def _fara_diacritice(text: str) -> str:
    descompus = unicodedata.normalize("NFD", text)
    return "".join(c for c in descompus if unicodedata.category(c) != "Mn").lower()


def bucati(abreviere: str) -> list[str]:
    """Taie abrevierea la majuscule si la separatoare.

    `LbForm&Autom` -> `lb form autom`; `POO` -> `p o o`; `AnalizaMate II` -> `analiza mate ii`.
    """
    return [_fara_diacritice(b) for b in _RE_BUCATA.findall(abreviere)]


def cuvinte_semnificative(denumire: str) -> list[str]:
    """Cuvintele denumirii, fara cele de legatura."""
    curat = _fara_diacritice(denumire)
    curat = re.sub(r"[^\w\s]+", " ", curat)
    return [c for c in curat.split() if c and c not in STOPWORDS]


def _e_subsecventa(bucata: str, cuvant: str) -> bool:
    """`lb` e schelet pentru `limbaje`; `struct` e prefix pentru `structuri`. Ambele trec."""
    if not bucata or not cuvant or bucata[0] != cuvant[0]:
        return False
    it = iter(cuvant)
    return all(litera in it for litera in bucata)


def variante(denumire: str) -> list[str]:
    """Denumirile de master sunt bilingve: `Vedere artificiala / Computer Vision`.

    Abrevierea din orar urmeaza una dintre ele -- `ComputerVision` pe cea engleza, dar
    `InvatAutom` pe cea romaneasca -- deci le incercam pe amandoua.
    """
    parti = [p.strip() for p in denumire.split("/") if p.strip()]
    return parti if len(parti) > 1 else [denumire]


def scor(abreviere: str, denumire: str) -> float:
    """Cat de bine explica denumirea abrevierea, intre 0 si 1.

    Toate bucatile abrevierii trebuie sa se regaseasca, in ordine. Scorul e cat din denumire
    a fost folosita: `BD` <- `Baze de date` foloseste tot (1.0), pe cand `IA` <- `Inteligenta
    artificiala in medicina` ar lasa un cuvant nefolosit si iese mai jos.
    """
    return max(_scor_simplu(abreviere, v) for v in variante(denumire))


def _scor_simplu(abreviere: str, denumire: str) -> float:
    b = bucati(abreviere)
    cuvinte = cuvinte_semnificative(denumire)
    if not b or not cuvinte:
        return 0.0

    ramase = list(cuvinte)
    folosite = 0
    for bucata in b:
        while ramase and not _e_subsecventa(bucata, ramase[0]):
            ramase.pop(0)
        if not ramase:
            return 0.0  # o bucata nu se explica: nu e aceeasi disciplina
        ramase.pop(0)
        folosite += 1
    return folosite / len(cuvinte)


def potriveste(abreviere: str, denumiri, prag: float = PRAG):  # noqa: ANN001, ANN201
    """Denumirile care explica abrevierea, cele mai bune intai.

    Intoarce perechi `(denumire, scor)`. Mai multe cu acelasi scor = ambiguu in sursa.
    """
    gasite = [(d, scor(abreviere, d)) for d in denumiri]
    gasite = [(d, s) for d, s in gasite if s >= prag]
    return sorted(gasite, key=lambda x: (-x[1], len(x[0])))
