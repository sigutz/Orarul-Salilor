"""Numarul si paritatea saptamanii academice.

Multe activitati se tin doar in saptamani impare (`SI`) sau doar in cele pare (`SP`),
iar altele doar intr-un interval (`[sapt 1-7]`). Ca sa stim ce se intampla *azi* avem
nevoie de numarul saptamanii curente.

Pagina FMI publica ancorele direct in text:

    Saptamana 06.04.2026 - 09.04.2026 este saptamana impara (sapt 7).
    Saptamana 20.04.2026 - 24.04.2026 este saptamana para (sapt 8).

Atentie: intre cele doua ancore sunt **doua** saptamani calendaristice, dar numai **una**
academica -- saptamana 13-17 aprilie e vacanta de Paste si nu se numara. Numerotarea FMI
sare peste vacante, deci nu se poate calcula prin simpla impartire la 7 de la o singura
ancora. De aceea pastram *toate* ancorele publicate si extrapolam de la cea mai apropiata,
marcand rezultatul ca aproximativ cand nu cade exact pe o ancora.

Paritatea nu se propaga separat: e chiar paritatea numarului academic (saptamana 7 e
impara, 8 e para), verificata pe ambele ancore publicate de FMI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

__all__ = [
    "Paritate",
    "AncoraSaptamana",
    "CalendarAcademic",
    "Saptamana",
    "parse_ancore",
    "parse_interval_saptamani",
    "PATTERN_ANCORA",
]


class Paritate(StrEnum):
    IMPARA = "SI"
    PARA = "SP"

    @property
    def eticheta(self) -> str:
        return "impară" if self is Paritate.IMPARA else "pară"

    @classmethod
    def din_numar(cls, numar: int) -> Paritate:
        """Saptamana 7 e impara, 8 e para -- paritatea numarului academic."""
        return cls.IMPARA if numar % 2 else cls.PARA


def _luni(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass(frozen=True)
class AncoraSaptamana:
    """O corespondenta publicata intre o saptamana calendaristica si numarul ei academic."""

    inceput: date
    numar: int
    paritate: Paritate

    def __post_init__(self) -> None:
        object.__setattr__(self, "inceput", _luni(self.inceput))


@dataclass(frozen=True)
class Saptamana:
    """Rezultatul unei interogari de calendar."""

    numar: int
    paritate: Paritate
    #: False cand numarul a fost extrapolat peste vacante necunoscute.
    exact: bool

    @property
    def eticheta(self) -> str:
        return f"săptămâna {self.numar} ({self.paritate.eticheta})"


@dataclass
class CalendarAcademic:
    """Traduce date calendaristice in saptamani academice, pe baza ancorelor publicate.

    Cu o singura ancora extrapolarea presupune saptamani consecutive, ceea ce e gresit
    peste vacante -- de aceea `Saptamana.exact` devine False. Cu cat watcher-ul reimprospateaza
    mai des ancorele de pe site (Etapa 6), cu atat raspunsul e mai des exact.
    """

    ancore: list[AncoraSaptamana] = field(default_factory=list)
    #: Cate saptamani are semestrul; in afara lor nu mai raspundem.
    lungime_semestru: int = 14

    def __post_init__(self) -> None:
        self.ancore = sorted(self.ancore, key=lambda a: a.inceput)

    def saptamana(self, zi: date) -> Saptamana | None:
        """Saptamana academica a unei zile, sau None daca suntem in afara semestrului."""
        if not self.ancore:
            return None

        luni = _luni(zi)

        for a in self.ancore:
            if a.inceput == luni:
                return Saptamana(a.numar, Paritate.din_numar(a.numar), exact=True)

        # Interpolare intre doua ancore: daca numerotarea e contigua acolo, e sigura.
        for a, b in zip(self.ancore, self.ancore[1:], strict=False):
            if a.inceput < luni < b.inceput:
                delta_cal = (b.inceput - a.inceput).days // 7
                delta_acad = b.numar - a.numar
                if delta_cal == delta_acad:
                    numar = a.numar + (luni - a.inceput).days // 7
                    return self._valideaza(numar, exact=True)
                # Numerotarea sare: e vacanta undeva intre, nu stim exact unde.
                return None

        cea_mai_apropiata = min(self.ancore, key=lambda a: abs((luni - a.inceput).days))
        numar = cea_mai_apropiata.numar + (luni - cea_mai_apropiata.inceput).days // 7
        return self._valideaza(numar, exact=False)

    def _valideaza(self, numar: int, *, exact: bool) -> Saptamana | None:
        if not 1 <= numar <= self.lungime_semestru:
            return None
        return Saptamana(numar, Paritate.din_numar(numar), exact=exact)


# "Saptamana 06.04.2026 - 09.04.2026 este saptamana impara (sapt 7)"
PATTERN_ANCORA = re.compile(
    r"S[ăa]pt[ăa]m[âa]na\s+(?P<zi>\d{1,2})\.(?P<luna>\d{1,2})\.(?P<an>\d{4})"
    r".*?este\s+s[ăa]pt[ăa]m[âa]n[ăa]\s+(?P<par>impar[ăa]|par[ăa])"
    r"(?:\s*\(\s*sapt\.?\s*(?P<nr>\d+)\s*\))?",
    re.IGNORECASE | re.DOTALL,
)


def parse_ancore(text: str) -> list[AncoraSaptamana]:
    """Extrage ancorele de saptamana dintr-un text (pagina FMI).

    Ancorele fara numar explicit `(sapt N)` se ignora: fara numar nu putem fixa
    originea numerotarii, iar o paritate singura nu e suficienta.
    """
    ancore: list[AncoraSaptamana] = []
    for m in PATTERN_ANCORA.finditer(text):
        if not m.group("nr"):
            continue
        este_impara = m.group("par").lower().startswith("i")
        ancore.append(
            AncoraSaptamana(
                inceput=date(int(m.group("an")), int(m.group("luna")), int(m.group("zi"))),
                numar=int(m.group("nr")),
                paritate=Paritate.IMPARA if este_impara else Paritate.PARA,
            )
        )
    return ancore


# `sapt 1-7`, `sapt 2`, `sapt 8-14` -- numere de saptamana ACADEMICA (1..14)
_RE_ACADEMICE = re.compile(r"sapt\.?\s*(?P<corp>[\d\s,+\-]+)", re.IGNORECASE)
# `CU s23,24,25, 26`, `SE s20+21` -- numere de saptamana CALENDARISTICA (ISO), alta scara
_RE_CALENDARISTICE = re.compile(r"\bs\s?\d{1,2}\b", re.IGNORECASE)


def parse_interval_saptamani(text: str) -> set[int] | None:
    """Multimea saptamanilor ACADEMICE in care se tine o activitate.

    Intoarce None cand textul nu se poate raporta la numerotarea academica -- fie e liber
    ("25 mar, 29 apr..."), fie foloseste saptamani calendaristice ISO ("CU s23,24,25, 26",
    "SE s20+21"), care sunt alta scara. In ambele cazuri apelantul afiseaza activitatea
    mereu, ca sa nu o ascunda din greseala.

    >>> sorted(parse_interval_saptamani("sapt 1-7"))
    [1, 2, 3, 4, 5, 6, 7]
    >>> parse_interval_saptamani("CU s23,24,25, 26") is None
    True
    """
    if not text or not text.strip():
        return None

    m = _RE_ACADEMICE.search(text)
    if not m:
        return None

    corp = m.group("corp")
    numere: set[int] = set()
    for interval in re.finditer(r"(\d{1,2})\s*-\s*(\d{1,2})", corp):
        a, b = int(interval.group(1)), int(interval.group(2))
        if 1 <= a <= b <= 20:
            numere.update(range(a, b + 1))
    for singur in re.finditer(r"\d{1,2}", re.sub(r"\d{1,2}\s*-\s*\d{1,2}", " ", corp)):
        n = int(singur.group())
        if 1 <= n <= 20:
            numere.add(n)

    return numere or None
