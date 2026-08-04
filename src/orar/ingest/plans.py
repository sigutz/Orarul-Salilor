r"""Planurile de invatamant: creditele, forma de evaluare si numarul de ore.

Ce aduc in plus fata de orar
----------------------------
Orarul spune *cand si unde* se tine o activitate, dar nu spune nimic despre disciplina ca
atare. `MATERIE.CREDITE`, `FORMA_EVALUARE`, `TIP_DISCIPLINA` si `NR_ORE_C/S/L/P` nu apar
nicaieri in el -- vin din alt loc: folderul "Planurile de invatamant" de pe Drive.

Sursa e mult mai prietenoasa decat orarul
-----------------------------------------
PDF-urile de aici **se descarca** (spre deosebire de orar, blocat) si patru din noua au
**strat de text intact**, deci se citesc exact, fara OCR:

    1.  Structuri algebrice în informatică      DF   2  2  -  -   E  4    -  -  -  -   -  -
        ^nr ^denumire                          ^tip  ^C ^S ^L ^P  ^ev ^cr  \___ semestrul II ___/

Un rand acopera **amandoua semestrele**; disciplina apartine celui in care are credite.

Cele cinci care nu se pot citi
------------------------------
Restul folosesc un font cu codificare proprie, fara tabela ToUnicode. Literele se pot
recupera (sunt deplasate cu +29), dar **cifrele lipsesc cu totul** din extragere:

    "$OJHEU  OLQLDU   ')   ("   =   "Algebră liniară  DF  ...  E"

adica exact creditele si orele pentru care venisem. Nici randarea + OCR nu ajuta usor:
detectorul rateaza cifrele izolate dintr-un tabel rarefiat. Deci le raportam ca necitibile,
nu le ghicim. Vezi `docs/planuri-de-invatamant.md`.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = [
    "DisciplinaPlan",
    "RaportPlanuri",
    "URL_PLANURI",
    "EroarePlan",
    "extrage_text",
    "parseaza",
    "parseaza_fisier",
    "parseaza_director",
    "descarca_planuri",
    "incarca_planuri",
    "RaportIncarcare",
]

URL_PLANURI = "https://drive.google.com/drive/folders/1cg-GOlmDhAYBiqHJAd_iEes8QKm2GE1U"

_ROMANE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}
_RE_AN = re.compile(r"^\s*ANUL\s+(?P<an>[IVX]+)\b", re.IGNORECASE)
_RE_PROGRAM = re.compile(
    r"Programul de studii universitare de (?:master|licen[țt][ăa]?)\s+(?P<nume>.+?)\s*$",
    re.IGNORECASE,
)
#: Titlul sectiunii nu e mereu la inceput de rand: la CTI e precedat de `Nr. Crt.`. Cautam
#: deci fraza oriunde, dar cu lista inchisa de feluri, ca sa nu prindem o denumire oarecare.
_RE_SECTIUNE = re.compile(
    r"\bDiscipline\s+(?P<fel>obligatorii|op[\u021bt]ionale|facultative|la alegere)\b",
    re.IGNORECASE,
)
#: Randul unei discipline: numar, denumire, tipul disciplinei, apoi coloanele numerice.
_RE_RAND = re.compile(
    r"^\s*(?P<nr>\d{1,2})\s*\.?\s+"
    r"(?P<nume>\S.*?)\s{2,}"
    r"(?P<tip>D[FSCO])\s+"
    r"(?P<coloane>[-\d\sEVAv+/]*)$"
)
#: Codul din fata denumirii, la master: `Ob.11 Sisteme de baze de date`.
_RE_COD = re.compile(r"^(?P<cod>(?:Ob|Op)\.\s?\d+)\s+(?P<nume>.+)$")
#: Randurile de total nu sunt discipline.
_RE_TOTAL = re.compile(r"^\s*Total\b", re.IGNORECASE)

_FELURI = {
    "obligatorii": "obligatorie",
    "la alegere": "optionala",
    "optionale": "optionala",
    "opționale": "optionala",
    "facultative": "facultativa",
    "alegere": "optionala",
}


class EroarePlan(RuntimeError):
    pass


@dataclass(frozen=True)
class DisciplinaPlan:
    """O linie din planul de invatamant."""

    nume: str
    #: DF (fundamentala) | DS (de specialitate) | DC (complementara) | DO (optionala)
    tip_disciplina: str
    an: int | None
    semestru: int | None
    #: E (examen) | V (verificare)
    forma_evaluare: str | None
    credite: int | None
    nr_ore_c: int | None = None
    nr_ore_s: int | None = None
    nr_ore_l: int | None = None
    nr_ore_p: int | None = None
    #: obligatorie | optionala | facultativa
    tip_materie: str | None = None
    #: Programul de studii, cand fisierul acopera mai multe (masteratele).
    program: str | None = None
    sursa: str = ""


@dataclass
class RaportPlanuri:
    fisiere_citite: int = 0
    fisiere_necitibile: list[str] = field(default_factory=list)
    discipline: list[DisciplinaPlan] = field(default_factory=list)
    avertismente: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        linii = [
            f"fisiere citite     : {self.fisiere_citite}",
            f"discipline gasite  : {len(self.discipline)}",
        ]
        if self.fisiere_necitibile:
            linii.append(f"fara strat de text : {len(self.fisiere_necitibile)}")
            linii += [f"    {x}" for x in self.fisiere_necitibile]
        return "\n".join(linii)


# ---------------------------------------------------------------------------
# Textul
# ---------------------------------------------------------------------------


def extrage_text(pdf: Path) -> str:
    """Textul PDF-ului, cu coloanele pastrate.

    `pdftotext -layout` (poppler). Alinierea coloanelor **e** informatia utila aici: fara ea
    n-am putea sti care numar e C, care S si care credite. Alternativele din pip pe care
    le-am incercat rup cuvintele in bucati (`St ruct uri a lg ebrice`), fiindca PDF-ul isi
    pozitioneaza fiecare glifa separat.
    """
    if shutil.which("pdftotext") is None:
        raise EroarePlan(
            "pdftotext nu e instalat (poppler-utils). Pe Fedora: sudo dnf install poppler-utils"
        )
    rezultat = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        timeout=120,
    )
    if rezultat.returncode != 0:
        raise EroarePlan(f"pdftotext a esuat pe {pdf.name}: {rezultat.stderr.decode()[:200]}")
    return rezultat.stdout.decode("utf-8", "replace")


def are_strat_de_text(text: str) -> bool:
    """Textul e lizibil, sau e codificarea proprie a fontului?

    Verificam pe cuvinte pe care orice plan le contine. La fisierele cu font propriu ele ies
    ca `'LVFLSOLQH` si niciun cuvant real nu apare.
    """
    return bool(re.search(r"Discipline|PLAN DE ÎNV|Nr\. de credite|Tipul", text))


# ---------------------------------------------------------------------------
# Parsarea
# ---------------------------------------------------------------------------


def _numar(token: str) -> int | None:
    return int(token) if token.isdigit() else None


def _coloane(text: str) -> list[str]:
    return text.split()


def parseaza(text: str, *, sursa: str = "") -> list[DisciplinaPlan]:
    """Disciplinele dintr-un plan, cu anul si sectiunea din care fac parte.

    Contextul (anul, programul, felul disciplinelor) vine din titlurile de sectiune si tine
    pana la urmatorul titlu -- randurile in sine nu il repeta.
    """
    discipline: list[DisciplinaPlan] = []
    an: int | None = None
    program: str | None = None
    fel: str | None = None

    for linie in text.split("\n"):
        if m := _RE_AN.match(linie):
            an = _ROMANE.get(m.group("an").upper())
            continue
        if m := _RE_PROGRAM.search(linie):
            program = m.group("nume").strip()
            continue
        if m := _RE_SECTIUNE.search(linie):
            fel = _FELURI.get(m.group("fel").lower())
            continue
        if _RE_TOTAL.match(linie):
            continue
        m = _RE_RAND.match(linie)
        if not m:
            continue
        d = _din_rand(m, an=an, program=program, fel=fel, sursa=sursa)
        if d is not None:
            discipline.append(d)
    return discipline


def _din_rand(m: re.Match[str], *, an, program, fel, sursa) -> DisciplinaPlan | None:  # noqa: ANN001
    nume = re.sub(r"\s+", " ", m.group("nume")).strip(" .*")
    if cod := _RE_COD.match(nume):
        nume = cod.group("nume").strip()
    if not nume:
        return None

    col = _coloane(m.group("coloane"))
    # Fiecare semestru are sase coloane: C, S, L, P, forma de evaluare, credite.
    sem1, sem2 = col[:6], col[6:12]
    semestru, valori = (1, sem1) if _are_continut(sem1) else (2, sem2)
    if not _are_continut(valori):
        return None
    valori = valori + ["-"] * (6 - len(valori))

    forma = valori[4] if valori[4] in ("E", "V") else None
    return DisciplinaPlan(
        nume=nume,
        tip_disciplina=m.group("tip"),
        an=an,
        semestru=semestru,
        forma_evaluare=forma,
        credite=_numar(valori[5]),
        nr_ore_c=_numar(valori[0]),
        nr_ore_s=_numar(valori[1]),
        nr_ore_l=_numar(valori[2]),
        nr_ore_p=_numar(valori[3]),
        tip_materie=fel,
        program=program,
        sursa=sursa,
    )


def _are_continut(coloane: list[str]) -> bool:
    """Semestrul in care se tine disciplina e cel care are credite sau ore, nu liniute."""
    return any(t.isdigit() for t in coloane)


def parseaza_fisier(pdf: Path) -> list[DisciplinaPlan]:
    text = extrage_text(pdf)
    if not are_strat_de_text(text):
        raise EroarePlan(
            f"{pdf.name}: fontul are codificare proprie, iar cifrele lipsesc din extragere"
        )
    return parseaza(text, sursa=pdf.name)


def parseaza_director(director: Path) -> RaportPlanuri:
    """Toate planurile dintr-un director, cu cele necitibile raportate separat."""
    rap = RaportPlanuri()
    for pdf in sorted(director.rglob("*.pdf")):
        try:
            discipline = parseaza_fisier(pdf)
        except EroarePlan as e:
            rap.fisiere_necitibile.append(str(e))
            continue
        rap.fisiere_citite += 1
        rap.discipline += discipline
        if not discipline:
            rap.avertismente.append(f"{pdf.name}: strat de text bun, dar niciun rand recunoscut")
    return rap


# ---------------------------------------------------------------------------
# Descarcarea
# ---------------------------------------------------------------------------


def descarca_planuri(director: Path, *, url: str = URL_PLANURI) -> list[Path]:
    """Descarca PDF-urile din folderul public de planuri.

    Spre deosebire de orar, fisierele astea **nu** au descarcarea blocata, deci nu e nevoie
    de capturi: le luam intregi. Playwright serveste doar la listarea folderului, care se
    incarca din JavaScript.
    """
    import httpx

    director.mkdir(parents=True, exist_ok=True)
    descarcate: list[Path] = []
    for fid, nume in _listeaza(url):
        if not nume.lower().endswith(".pdf"):
            continue
        cale = director / re.sub(r"[^\w.-]+", "_", nume)
        r = httpx.get(
            f"https://drive.google.com/uc?export=download&id={fid}",
            follow_redirects=True,
            timeout=120,
        )
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            log.warning("%s nu s-a descarcat ca PDF (probabil cere confirmare)", nume)
            continue
        cale.write_bytes(r.content)
        descarcate.append(cale)
    return descarcate


def _listeaza(url: str) -> list[tuple[str, str]]:
    """(id, nume) pentru tot ce e in folder, coborand si in subfoldere."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise EroarePlan("playwright nu e instalat: pip install -e '.[ingest]'") from e

    gasite: list[tuple[str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pagina = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
        de_vizitat = [url]
        vizitate: set[str] = set()
        while de_vizitat:
            curent = de_vizitat.pop()
            if curent in vizitate:
                continue
            vizitate.add(curent)
            for fid, nume in _continut(pagina, curent):
                if nume.lower().endswith(".pdf"):
                    gasite.append((fid, nume))
                elif "." not in nume:  # subfolder
                    de_vizitat.append(f"https://drive.google.com/drive/folders/{fid}")
        browser.close()
    return gasite


def _continut(pagina, url: str) -> list[tuple[str, str]]:  # noqa: ANN001
    import time

    pagina.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(7)
    elemente = pagina.evaluate(
        """() => Array.from(document.querySelectorAll('[data-id]')).map(e => ({
             id: e.getAttribute('data-id'),
             nume: (e.getAttribute('aria-label') || e.innerText || '').trim().split('\\n')[0],
           }))"""
    )
    propriu = url.rsplit("/", 1)[-1]
    vazute, out = set(), []
    for e in elemente:
        cheie = (e["id"], e["nume"])
        if e["id"] and e["nume"] and e["id"] != propriu and cheie not in vazute:
            vazute.add(cheie)
            out.append((e["id"], e["nume"]))
    return out


# ---------------------------------------------------------------------------
# Incarcarea in baza
# ---------------------------------------------------------------------------


@dataclass
class RaportIncarcare:
    materii_completate: int = 0
    #: Materii pentru care nicio denumire din planuri nu explica abrevierea.
    fara_corespondent: list[str] = field(default_factory=list)
    #: Abrevieri care se potrivesc la fel de bine cu mai multe denumiri.
    ambigue: list[str] = field(default_factory=list)
    #: Discipline din plan pe care orarul nu le contine (nu se tin in semestrul asta).
    neutilizate: int = 0

    def __str__(self) -> str:
        return "\n".join(
            [
                f"materii completate : {self.materii_completate}",
                f"fara corespondent  : {len(self.fara_corespondent)}",
                f"ambigue            : {len(self.ambigue)}",
                f"discipline nefolosite in orar: {self.neutilizate}",
            ]
        )


def incarca_planuri(sesiune, discipline: list[DisciplinaPlan]) -> RaportIncarcare:  # noqa: ANN001
    """Leaga disciplinele de materiile din orar si le completeaza coloanele.

    Legatura se face pe **regula de abreviere** (vezi `domain/abbrev.py`), nu pe potrivire
    fuzzy de siruri: `BD` si `Big Data` s-ar confunda oricum altfel.

    Cand aceeasi denumire apare in mai multe planuri (an/semestru diferit), o luam pe cea cu
    scorul cel mai bun; daca sunt egale, o raportam ca ambigua si nu alegem noi.
    """
    from sqlalchemy import select

    from orar.db.models import Materie
    from orar.domain.abbrev import potriveste

    dupa_nume: dict[str, list[DisciplinaPlan]] = {}
    for d in discipline:
        dupa_nume.setdefault(d.nume, []).append(d)

    rap = RaportIncarcare()
    folosite: set[str] = set()
    for materie in sesiune.scalars(select(Materie)):
        gasite = potriveste(materie.nume, list(dupa_nume))
        if not gasite:
            rap.fara_corespondent.append(materie.nume)
            continue
        if _chiar_ambiguu(gasite):
            rap.ambigue.append(f"{materie.nume!r} -> {[d for d, _ in gasite[:3]]}")
            continue
        denumire = gasite[0][0]
        folosite.add(denumire)
        _aplica(materie, dupa_nume[denumire][0], denumire)
        rap.materii_completate += 1

    sesiune.flush()
    rap.neutilizate = len(dupa_nume) - len(folosite)
    return rap


def _chiar_ambiguu(gasite: list[tuple[str, float]]) -> bool:
    """Doua denumiri la egalitate inseamna ambiguitate doar daca sunt discipline diferite.

    Planurile scriu aceeasi disciplina si `Tehnici Web`, si `Tehnici web`, si
    `Metode dezvoltare software` alaturi de `Metode de dezvoltare software`. Diferenta e de
    scriere, nu de continut, deci nu avem intre ce alege -- le comparam pe cuvintele care
    conteaza.
    """
    from orar.domain.abbrev import cuvinte_semnificative, variante

    if len(gasite) < 2 or gasite[0][1] != gasite[1][1]:
        return False
    la_egalitate = [d for d, s in gasite if s == gasite[0][1]]
    # Comparam pe *variante*: `Big Data` si `Big Data / Big Data` au una comuna, deci sunt
    # aceeasi disciplina scrisa o data monolingv si o data bilingv.
    forme = [{tuple(cuvinte_semnificative(v)) for v in variante(d)} for d in la_egalitate]
    comune = set.intersection(*forme)
    return not comune


def _aplica(materie, d: DisciplinaPlan, denumire_intreaga: str) -> None:  # noqa: ANN001
    """Scrie coloanele de plan pe materie, pastrand denumirea scurta din orar.

    `NUME` ramane abrevierea: ea e cheia sub care apare peste tot in interfata si in orar.
    Denumirea intreaga se pastreaza separat, ca sa se poata afisa acolo unde e loc.
    """
    materie.denumire = denumire_intreaga
    materie.credite = d.credite
    materie.tip_materie = d.tip_materie
    materie.forma_evaluare = d.forma_evaluare
    materie.tip_disciplina = d.tip_disciplina
    materie.an = d.an
    materie.semestru = d.semestru
    materie.nr_ore_c = d.nr_ore_c
    materie.nr_ore_s = d.nr_ore_s
    materie.nr_ore_l = d.nr_ore_l
    materie.nr_ore_p = d.nr_ore_p
