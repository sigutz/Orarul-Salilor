"""Ce publica FMI acum, si daca s-a schimbat de la ultimul ingest.

De ce nu merge "primul link de pe pagina"
-----------------------------------------
Prototipul lua primul `bit.ly` gasit in HTML. Pe pagina reala sunt **opt**, iar eticheta
`Orarul grupelor` apare de doua ori -- o data la Semestrul II, o data la Semestrul I -- pe
langa tutoriate, profesori si Centrul ID/IFR. Un `find` naiv prinde deci, dupa cum se
nimereste, orarul altui semestru sau al tutorilor.

Ancorele pe care ne bazam
-------------------------
Nu pozitia in HTML, ci **textul**, care e stabil pentru ca e continut redactional:

    Semestrul II
      ... Saptamana 06.04.2026 - 09.04.2026 este saptamana impara (sapt 7). ...
      Orarul grupelor      -> bit.ly/...   (actualizat 26.04.2026, ora 19:30)
      Orarul profesorilor  -> bit.ly/...   (actualizat 26.04.2026, ora 19:30)

Deci: pentru fiecare link cu eticheta cunoscuta cautam inapoi primul titlu de semestru si
inainte prima paranteza `(actualizat ...)`. Iese o stare **per sursa**, nu un md5 pe toata
pagina: stim exact ce s-a schimbat si ce trebuie reluat.

Data publicata de facultate e un semnal mai bun decat orice amprenta calculata de noi: se
schimba exact cand se schimba orarul, nu cand isi schimba site-ul tema.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from orar.domain.weeks import AncoraSaptamana, parse_ancore

log = logging.getLogger(__name__)

__all__ = [
    "URL_ORAR",
    "SursaOrar",
    "StarePublicata",
    "Schimbare",
    "descarca",
    "parseaza",
    "compara",
]

URL_ORAR = "https://fmi.unibuc.ro/orar/"

#: Etichetele exacte de pe pagina, si numele scurt sub care tinem sursa.
ETICHETE = {
    "orarul grupelor": "grupe",
    "orarul profesorilor": "profesori",
}

_RE_SEMESTRU = re.compile(r"Semestrul\s+(?P<nr>I{1,2}|1|2)\b", re.IGNORECASE)
_RE_ACTUALIZAT = re.compile(
    r"actualizat\s+(?P<zi>\d{1,2})\.(?P<luna>\d{1,2})\.(?P<an>\d{4})"
    r"(?:\s*,\s*ora\s+(?P<ora>\d{1,2}):(?P<min>\d{2}))?",
    re.IGNORECASE,
)
#: Cat de departe in text mai cautam paranteza `(actualizat ...)` dupa un link.
FEREASTRA_TEXT = 6


@dataclass(frozen=True)
class SursaOrar:
    """Un orar publicat: ce semestru, ce fel, unde, si de cand."""

    semestru: int
    fel: str
    url: str
    actualizat: datetime | None = None

    @property
    def cheie(self) -> tuple[int, str]:
        return (self.semestru, self.fel)


@dataclass
class StarePublicata:
    surse: list[SursaOrar] = field(default_factory=list)
    ancore: list[AncoraSaptamana] = field(default_factory=list)
    avertismente: list[str] = field(default_factory=list)

    def sursa(self, semestru: int, fel: str = "grupe") -> SursaOrar | None:
        return next(
            (s for s in self.surse if s.semestru == semestru and s.fel == fel),
            None,
        )

    @property
    def semestru_curent(self) -> int | None:
        """Semestrul cu cea mai recenta actualizare -- cel pe care il tine facultatea la zi."""
        cu_data = [s for s in self.surse if s.actualizat]
        if not cu_data:
            return None
        return max(cu_data, key=lambda s: s.actualizat).semestru


@dataclass(frozen=True)
class Schimbare:
    """Ce s-a schimbat pentru o sursa fata de ce aveam in baza."""

    sursa: SursaOrar
    motiv: str

    def __str__(self) -> str:
        return f"sem {self.sursa.semestru} / {self.sursa.fel}: {self.motiv}"


def descarca(url: str = URL_ORAR, *, timeout: float = 30.0) -> str:
    import httpx

    r = httpx.get(url, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    return r.text


def parseaza(html: str) -> StarePublicata:
    """Citeste din pagina sursele publicate si ancorele de saptamana."""
    from bs4 import BeautifulSoup

    supa = BeautifulSoup(html, "html.parser")
    stare = StarePublicata(ancore=parse_ancore(supa.get_text(" ", strip=True)))

    vazute: set[tuple[int, str]] = set()
    for a in supa.find_all("a", href=True):
        fel = ETICHETE.get(a.get_text(" ", strip=True).strip().lower())
        if fel is None:
            continue
        semestru = _semestrul_dinaintea(a)
        if semestru is None:
            stare.avertismente.append(f"link {a['href']} fara titlu de semestru inaintea lui")
            continue
        if (semestru, fel) in vazute:
            # Doua linkuri cu aceeasi eticheta in aceeasi sectiune: nu putem alege, deci
            # semnalam in loc sa luam la intamplare.
            stare.avertismente.append(
                f"eticheta {fel!r} apare de mai multe ori la semestrul {semestru}"
            )
            continue
        vazute.add((semestru, fel))
        stare.surse.append(
            SursaOrar(
                semestru=semestru,
                fel=fel,
                url=a["href"],
                actualizat=_actualizat_dupa(a),
            )
        )

    if not stare.surse:
        stare.avertismente.append(
            "n-am gasit niciun orar pe pagina -- probabil s-au schimbat etichetele"
        )
    return stare


def _semestrul_dinaintea(nod) -> int | None:  # noqa: ANN001
    """Primul titlu `Semestrul N` de deasupra linkului, in ordinea documentului."""
    for text in nod.find_all_previous(string=True):
        m = _RE_SEMESTRU.search(str(text))
        if m:
            valoare = m.group("nr").upper()
            return {"I": 1, "II": 2}.get(valoare, int(valoare) if valoare.isdigit() else 0) or None
    return None


def _actualizat_dupa(nod) -> datetime | None:  # noqa: ANN001
    """Prima paranteza `(actualizat ...)` de dupa link.

    Ne oprim dupa cateva noduri de text: daca sursa n-are data proprie, e mai bine sa
    intoarcem None decat sa imprumutam data altei surse de mai jos.
    """
    for i, text in enumerate(nod.find_all_next(string=True)):
        if i >= FEREASTRA_TEXT:
            return None
        m = _RE_ACTUALIZAT.search(str(text))
        if m:
            return datetime(
                int(m.group("an")),
                int(m.group("luna")),
                int(m.group("zi")),
                int(m.group("ora") or 0),
                int(m.group("min") or 0),
            )
    return None


def compara(
    stare: StarePublicata, cunoscute: dict[tuple[int, str], datetime | None]
) -> list[Schimbare]:
    """Ce surse trebuie reluate, fata de datele cu care am ingestat ultima oara."""
    schimbari: list[Schimbare] = []
    for sursa in stare.surse:
        if sursa.cheie not in cunoscute:
            schimbari.append(Schimbare(sursa, "sursa noua, neingestata niciodata"))
            continue
        precedenta = cunoscute[sursa.cheie]
        if sursa.actualizat is None:
            # Fara data publicata nu putem decide; nu reluam degeaba un ingest de ~6 minute.
            continue
        if precedenta is None or sursa.actualizat > precedenta:
            schimbari.append(
                Schimbare(
                    sursa, f"actualizat {sursa.actualizat:%d.%m.%Y %H:%M} (aveam {precedenta})"
                )
            )
    return schimbari
