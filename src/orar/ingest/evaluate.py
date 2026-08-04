"""Acuratetea citirii, masurata camp cu camp fata de setul de referinta.

Setul de referinta (`tests/golden/date.json`) e iesirea prototipului cu Gemini: 98 de pagini,
1143 de activitati. **Nu e adevar absolut** -- am verificat vizual cateva locuri in care
greseste (ex. pagina 14, miercuri, ii lipsesc doua celule; pagina 5, `11-14` citit `11-13`).
Il folosim ca reper de regresie, nu ca oracol: o diferenta merita privita, nu neaparat
reparata in parserul nostru.

Paginile se leaga dupa **titlu**, nu dupa numar: ordinea din JSON nu e ordinea din PDF.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from orar.ingest.lexicon import Lexicon
from orar.ingest.ocr import MotorRecunoastere, PaginaCitita, citeste_fisier
from orar.ingest.segment import ZILE, EroareSegmentare

log = logging.getLogger(__name__)

__all__ = ["Raport", "evalueaza", "CAMPURI"]

CAMPURI = ("ore", "profesor", "materie", "tip", "frecventa", "saptamani", "semigrupa", "sala")


@dataclass
class Raport:
    pagini_citite: int = 0
    pagini_nepotrivite: list[str] = field(default_factory=list)
    #: camp -> (potrivite, total)
    potriviri: dict[str, list[int]] = field(default_factory=dict)
    celule_in_plus: int = 0
    celule_lipsa: int = 0
    #: (camp, asteptat, citit) -> de cate ori
    diferente: Counter = field(default_factory=Counter)
    #: Cum arata dezacordurile pe `ore`: intervalul nostru il contine pe cel din referinta,
    #: e continut de el, sau nu se cuprind deloc.
    forme_ore: Counter = field(default_factory=Counter)

    def acuratete(self, camp: str) -> float:
        bine, tot = self.potriviri.get(camp, [0, 0])
        return bine / tot if tot else 0.0

    def __str__(self) -> str:
        linii = [
            f"pagini citite      : {self.pagini_citite}",
            f"pagini nepotrivite : {len(self.pagini_nepotrivite)}",
            f"celule in plus     : {self.celule_in_plus}",
            f"celule lipsa       : {self.celule_lipsa}",
            "",
        ]
        for camp in CAMPURI:
            bine, tot = self.potriviri.get(camp, [0, 0])
            linii.append(f"  {camp:11} {self.acuratete(camp) * 100:6.2f}%   ({bine}/{tot})")
        if self.forme_ore:
            total = sum(self.forme_ore.values())
            contine = self.forme_ore["contine"]
            linii += [
                "",
                f"dezacorduri pe `ore`: {total}, din care {contine} in care intervalul",
                "nostru il *contine* strict pe cel din referinta. Asa arata benzile pe care",
                "referinta le-a citit ca celule alaturate de cate o ora in loc de celule",
                "suprapuse pe tot intervalul (verificat pe pixeli: pag_012, luni 18-20).",
                f"  {dict(self.forme_ore)}",
            ]
        return "\n".join(linii)


def _cheie(activitate: dict) -> tuple[str, str]:
    """Identificam o activitate prin zi + interval: geometria e exacta, textul nu."""
    return (activitate["_zi"], activitate["ore"])


def _interval(text: str) -> tuple[int, int] | None:
    parti = text.split("-")
    if len(parti) != 2:
        return None
    try:
        return int(parti[0]), int(parti[1])
    except ValueError:
        return None


def _se_suprapun(a: dict, b: dict) -> bool:
    ia, ib = _interval(a["ore"]), _interval(b["ore"])
    if ia is None or ib is None:
        return a["ore"] == b["ore"]
    return ia[0] < ib[1] and ib[0] < ia[1]


def _aplatizeaza(pagina: dict) -> list[dict]:
    out = []
    for zi in ZILE:
        for a in pagina.get(zi, []):
            out.append({**a, "_zi": zi, "ore": _ore(a["ore"])})
    return out


def _ore(text: str) -> str:
    """`08-10` si `8-10` sunt acelasi interval."""
    parti = text.split("-")
    if len(parti) != 2:
        return text
    try:
        return f"{int(parti[0])}-{int(parti[1])}"
    except ValueError:
        return text


def evalueaza(
    imagini: list[Path],
    referinta: Path,
    motor: MotorRecunoastere,
    lexicon: Lexicon,
    la_pagina=None,  # noqa: ANN001
) -> Raport:
    """Citeste fiecare imagine si o compara cu pagina corespunzatoare din referinta.

    Legarea se face pe **numarul paginii**, nu pe titlu. Titlurile se aseamana intre ele mai
    mult decat pare: `Facultative an II (...)` si `Facultative an III (...)` difera printr-o
    litera din ~55, deci o potrivire fuzzy le poate confunda -- si atunci toate cele 13
    activitati ale unei pagini ies "gresite" fara ca extragerea sa aiba vreo vina.
    Referinta pastreaza in `_source` pagina din care vine, iar capturile poarta acelasi
    numar; asta e o cheie exacta.
    """
    date = json.loads(referinta.read_text(encoding="utf-8"))
    dupa_numar = {_numar_pagina(p.get("_source", "")): p for p in date}
    dupa_numar.pop(None, None)
    dupa_titlu = {p["grupa"]: p for p in date}
    raport = Raport(potriviri={c: [0, 0] for c in CAMPURI})

    for cale in imagini:
        try:
            citita = citeste_fisier(cale, motor, lexicon)
        except EroareSegmentare as e:
            log.debug("%s: %s", cale.name, e)
            continue
        raport.pagini_citite += 1
        if la_pagina is not None:
            la_pagina(cale, citita)

        asteptata = dupa_numar.get(_numar_pagina(cale.name))
        if asteptata is None:
            # Fara numar de pagina in referinta ramane titlul, cu prag mare.
            asteptata = dupa_titlu.get(citita.titlu) or _dupa_asemanare(citita.titlu, dupa_titlu)
        if asteptata is None:
            raport.pagini_nepotrivite.append(f"{cale.name}: {citita.titlu!r}")
            continue
        _compara(raport, citita, asteptata)

    return raport


_RE_NUMAR_PAGINA = re.compile(r"pag[_-]?(\d+)", re.IGNORECASE)


def _numar_pagina(nume: str) -> int | None:
    """`pag_46.png` si `pag_046.png` sunt aceeasi pagina."""
    m = _RE_NUMAR_PAGINA.search(nume or "")
    return int(m.group(1)) if m else None


def _dupa_asemanare(titlu: str, dupa_titlu: dict[str, dict]) -> dict | None:
    from rapidfuzz import fuzz, process

    if not titlu or not dupa_titlu:
        return None
    gasit = process.extractOne(titlu, list(dupa_titlu), scorer=fuzz.ratio)
    if gasit and gasit[1] >= 85:
        return dupa_titlu[gasit[0]]
    return None


def _compara(raport: Raport, citita: PaginaCitita, asteptata: dict) -> None:
    """Imperecheaza activitatile si numara potrivirile pe campuri.

    Aceeasi zi si acelasi interval pot avea mai multe activitati (benzi suprapuse: semigrupe
    sau saptamani alternante). Referinta nu spune in ce banda sta fiecare, deci nu le putem
    lega dupa pozitie -- le legam dupa **cat de bine seamana**, lacom, perechea cea mai buna
    intai. Altfel doua benzi ale aceluiasi interval s-ar imperechea invers si ar iesi opt
    campuri gresite dintr-o citire perfecta.

    Legarea cere doar ca intervalele sa se **suprapuna**, nu sa fie identice, fiindca tocmai
    `ore` e campul in care referinta greseste sistematic: unde pagina are trei celule
    suprapuse de 18-20, Gemini a citit sase celule alaturate de cate o ora (verificat pe
    pixeli: `pag_012`, luni). Daca am cere egalitate, greseala referintei ar ascunde din
    masuratoare toate celelalte campuri ale acelor celule.
    """
    ref = _aplatizeaza(asteptata)
    nostru = [{**a.ca_json(), "_zi": a.zi, "ore": _ore(a.ore)} for a in citita.activitati]

    perechi = sorted(
        (
            (_asemanare(n, r), i, j)
            for i, r in enumerate(ref)
            for j, n in enumerate(nostru)
            if r["_zi"] == n["_zi"] and _se_suprapun(r, n)
        ),
        reverse=True,
    )
    legat_ref: set[int] = set()
    legat_noi: set[int] = set()
    for _, i, j in perechi:
        if i in legat_ref or j in legat_noi:
            continue
        legat_ref.add(i)
        legat_noi.add(j)
        _numara(raport, nostru[j], ref[i])

    raport.celule_lipsa += len(ref) - len(legat_ref)
    raport.celule_in_plus += len(nostru) - len(legat_noi)


def _asemanare(a: dict, b: dict) -> int:
    return sum(1 for camp in CAMPURI if (a.get(camp) or "") == (b.get(camp) or ""))


def _numara(raport: Raport, citit: dict, asteptat: dict) -> None:
    for camp in CAMPURI:
        raport.potriviri[camp][1] += 1
        if (citit.get(camp) or "") == (asteptat.get(camp) or ""):
            raport.potriviri[camp][0] += 1
        else:
            raport.diferente[(camp, asteptat.get(camp, ""), citit.get(camp, ""))] += 1
            if camp == "ore":
                raport.forme_ore[_forma_ore(citit["ore"], asteptat["ore"])] += 1


def _forma_ore(nostru: str, referinta: str) -> str:
    a, b = _interval(nostru), _interval(referinta)
    if a is None or b is None:
        return "necitibil"
    if a[0] <= b[0] and b[1] <= a[1]:
        return "contine"
    if b[0] <= a[0] and a[1] <= b[1]:
        return "continut"
    return "decalat"
