"""Sincronizarea completa: pagina FMI -> captura -> segmentare -> OCR -> baza.

Ordinea si de ce
----------------
1. **Citim pagina** si aflam ce a publicat facultatea (`ingest/watcher.py`).
2. **Salvam ancorele** de saptamana. Sunt ieftine si independente de orar: chiar daca
   ingestul nu se mai face, paritatea afisata in interfata ramane corecta.
3. **Comparam** data publicata cu cea de la ultimul ingest reusit. Daca nu s-a schimbat
   nimic, ne oprim aici -- captura celor 100 de pagini dureaza ~6 minute si nu are rost.
4. Doar daca s-a schimbat: capturam, citim si incarcam.

`INGESTAT_LA` se scrie **dupa** ce ingestul a reusit, nu inainte. Daca pica la jumatate,
urmatoarea rulare reia sursa in loc sa o creada facuta.

Ingestul nu incarca peste datele vechi: sterge intai orele semestrului respectiv. Altfel
o activitate mutata ar ramane si pe locul vechi, iar `/sala` ar arata conflicte inventate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orar.db.models import AncoraSaptamana as AncoraDB
from orar.db.models import Ora, Perioada
from orar.db.models import SursaOrar as SursaDB
from orar.ingest import watcher

log = logging.getLogger(__name__)

__all__ = [
    "RaportSincronizare",
    "sincronizeaza",
    "salveaza_ancore",
    "calendar_din_baza",
    "curata_orfanii",
]


@dataclass
class RaportSincronizare:
    verificat: bool = False
    schimbari: list[str] = field(default_factory=list)
    ingestate: list[str] = field(default_factory=list)
    ancore: int = 0
    #: Ce a spus verificarea cu orarul profesorilor.
    crosscheck: list[str] = field(default_factory=list)
    avertismente: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        linii = [
            f"pagina citita     : {'da' if self.verificat else 'nu'}",
            f"ancore salvate    : {self.ancore}",
            f"surse de reluat   : {len(self.schimbari)}",
        ]
        linii += [f"    {s}" for s in self.schimbari]
        if self.ingestate:
            linii.append(f"surse ingestate   : {len(self.ingestate)}")
            linii += [f"    {s}" for s in self.ingestate]
        if self.crosscheck:
            linii.append("verificare incrucisata:")
            linii += [f"    {s}" for s in self.crosscheck]
        linii += [f"  ! {a}" for a in self.avertismente]
        return "\n".join(linii)


def sincronizeaza(
    s: Session,
    *,
    an_universitar: str = "2025-2026",
    semestru: int | None = None,
    director: Path = Path("data/screenshots"),
    forteaza: bool = False,
    doar_verifica: bool = False,
    fara_crosscheck: bool = False,
    html: str | None = None,
) -> RaportSincronizare:
    """Verifica pagina FMI si, daca e cazul, reia ingestul.

    `semestru=None` inseamna semestrul pe care facultatea il tine la zi (cel cu cea mai
    recenta actualizare), ca sa nu reingestam din greseala orarul vechi.
    """
    rap = RaportSincronizare()
    stare = watcher.parseaza(html if html is not None else watcher.descarca())
    rap.verificat = True
    rap.avertismente += stare.avertismente

    rap.ancore = salveaza_ancore(s, stare.ancore, an_universitar=an_universitar)

    tinta = semestru if semestru is not None else stare.semestru_curent
    if tinta is None:
        rap.avertismente.append("nu am putut deduce semestrul curent din pagina")
        return rap

    surse = [x for x in stare.surse if x.semestru == tinta and x.fel == "grupe"]
    if not surse:
        rap.avertismente.append(f"pagina nu are 'Orarul grupelor' pentru semestrul {tinta}")
        return rap

    cunoscute = _ingestate_pana_acum(s, an_universitar)
    for sursa in surse:
        rand = _upsert_sursa(s, sursa, an_universitar)
        rand.verificat_la = datetime.now()
    s.flush()

    schimbari = watcher.compara(stare, cunoscute)
    schimbari = [c for c in schimbari if c.sursa.semestru == tinta and c.sursa.fel == "grupe"]
    if forteaza and not schimbari:
        schimbari = [watcher.Schimbare(surse[0], "reluare fortata")]
    rap.schimbari = [str(c) for c in schimbari]

    if doar_verifica or not schimbari:
        return rap

    for c in schimbari:
        _ingesteaza(s, c.sursa, an_universitar=an_universitar, director=director, rap=rap)

    if rap.ingestate and not fara_crosscheck:
        _crosscheck(s, stare, tinta, an_universitar=an_universitar, director=director, rap=rap)
    return rap


def _crosscheck(
    s: Session,
    stare: watcher.StarePublicata,
    semestru: int,
    *,
    an_universitar: str,
    director: Path,
    rap: RaportSincronizare,
) -> None:
    """A doua sursa: orarul profesorilor, pentru confirmare si nume intregi.

    Ruleaza dupa ingest, nu inaintea lui: are nevoie de baza deja incarcata ca sa aiba ce
    confirma. Daca pica -- alt layout, captura intrerupta -- ingestul principal ramane bun,
    deci nu lasam o eroare de aici sa strice tot.
    """
    from orar.ingest.capture import EroareCaptura, OptiuniCaptura, captureaza_orar
    from orar.ingest.crosscheck import (
        citeste_orarul_profesorilor,
        completeaza_profesorii,
        extinde_numele,
        verifica,
    )
    from orar.ingest.lexicon import Lexicon
    from orar.ingest.ocr import RapidOCR

    sursa = stare.sursa(semestru, "profesori")
    if sursa is None:
        rap.avertismente.append("pagina nu are 'Orarul profesorilor'; sar peste verificare")
        return

    tinta = director / f"sem{semestru}-profesori"
    try:
        rez = captureaza_orar(sursa.url, OptiuniCaptura(director=tinta))
    except EroareCaptura as e:
        rap.avertismente.append(f"captura orarului profesorilor: {e}")
        return
    rap.avertismente += rez.avertismente

    index = citeste_orarul_profesorilor(tinta, RapidOCR(), Lexicon.din_baza(s))
    raport = verifica(s, index)
    completate = completeaza_profesorii(s, index)
    extinse, ambigue = extinde_numele(s, index)

    rand = _upsert_sursa(s, sursa, an_universitar)
    rand.ingestat_la = sursa.actualizat
    s.flush()

    rap.crosscheck = [
        f"{raport.confirmate} activitati confirmate de a doua sursa "
        f"({raport.acoperire * 100:.0f}%), {len(raport.divergente)} divergente",
        f"{len(completate)} campuri nesigure completate, {len(extinse)} nume intregite",
    ]
    if ambigue:
        rap.crosscheck.append(f"{len(ambigue)} prescurtari ambigue, lasate cum sunt")


def salveaza_ancore(s: Session, ancore, *, an_universitar: str, semestru: int = 2) -> int:  # noqa: ANN001
    """Scrie ancorele publicate, inlocuindu-le pe cele cu aceeasi saptamana."""
    n = 0
    for a in ancore:
        rand = s.scalar(
            select(AncoraDB).where(
                AncoraDB.an_univ == an_universitar,
                AncoraDB.semestru == semestru,
                AncoraDB.inceput == a.inceput,
            )
        )
        if rand is None:
            rand = AncoraDB(an_univ=an_universitar, semestru=semestru, inceput=a.inceput)
            s.add(rand)
        rand.numar = a.numar
        rand.paritate = str(a.paritate)
        n += 1
    s.flush()
    return n


def calendar_din_baza(s: Session, *, an_universitar: str | None = None):  # noqa: ANN001
    """`CalendarAcademic` construit din ancorele salvate; None daca nu exista niciuna."""
    from orar.domain.weeks import AncoraSaptamana, CalendarAcademic, Paritate

    q = select(AncoraDB).order_by(AncoraDB.inceput)
    if an_universitar:
        q = q.where(AncoraDB.an_univ == an_universitar)
    randuri = list(s.scalars(q))
    if not randuri:
        return None
    return CalendarAcademic(
        ancore=[
            AncoraSaptamana(inceput=r.inceput, numar=r.numar, paritate=Paritate(r.paritate))
            for r in randuri
        ]
    )


def _ingestate_pana_acum(s: Session, an_universitar: str) -> dict[tuple[int, str], datetime | None]:
    return {
        (r.semestru, r.fel): r.ingestat_la
        for r in s.scalars(select(SursaDB).where(SursaDB.an_univ == an_universitar))
    }


def _upsert_sursa(s: Session, sursa: watcher.SursaOrar, an_universitar: str) -> SursaDB:
    rand = s.scalar(
        select(SursaDB).where(
            SursaDB.an_univ == an_universitar,
            SursaDB.semestru == sursa.semestru,
            SursaDB.fel == sursa.fel,
        )
    )
    if rand is None:
        rand = SursaDB(an_univ=an_universitar, semestru=sursa.semestru, fel=sursa.fel)
        s.add(rand)
    rand.url = sursa.url
    rand.actualizat = sursa.actualizat
    return rand


def _ingesteaza(
    s: Session,
    sursa: watcher.SursaOrar,
    *,
    an_universitar: str,
    director: Path,
    rap: RaportSincronizare,
) -> None:
    from orar.ingest.capture import EroareCaptura, OptiuniCaptura, captureaza_orar
    from orar.ingest.consolidate import consolideaza
    from orar.ingest.lexicon import Lexicon
    from orar.ingest.load import incarca_pagini
    from orar.ingest.ocr import RapidOCR, citeste_fisier
    from orar.ingest.segment import EroareSegmentare

    tinta = director / f"sem{sursa.semestru}-{sursa.fel}"
    try:
        rez = captureaza_orar(sursa.url, OptiuniCaptura(director=tinta))
    except EroareCaptura as e:
        rap.avertismente.append(f"captura pentru {sursa.fel} sem {sursa.semestru}: {e}")
        return
    rap.avertismente += rez.avertismente

    # Vocabularul de pornire e cel din baza; la prima rulare e gol si totul ajunge in
    # coada de verificare, ceea ce e onest -- nu avem inca de unde sti termenii corecti.
    lexicon = Lexicon.din_baza(s)
    motor = RapidOCR()
    pagini = []
    for pagina in rez.pagini:
        try:
            citita = citeste_fisier(pagina.cale, motor, lexicon)
        except EroareSegmentare:
            continue  # coperta / cuprins
        # Calea **relativa la radacina capturilor**, nu doar numele: capturam in
        # `screenshots/sem2-grupe/`, si numai numele fisierului n-ar mai duce inapoi la
        # imagine, deci coada de verificare ar ramane fara decupaje.
        pagini.append(
            {
                **citita.ca_json(cu_provenienta=True),
                "_source": str(pagina.cale.relative_to(director)),
            }
        )

    if not pagini:
        rap.avertismente.append(f"nicio pagina citibila in {tinta}")
        return

    _sterge_semestrul(s, an_universitar=an_universitar, semestru=sursa.semestru)
    raport = incarca_pagini(s, pagini, an_universitar=an_universitar, semestru=sursa.semestru)
    consolidare = consolideaza(s, an_universitar=an_universitar)
    orfani = curata_orfanii(s)
    if orfani:
        rap.avertismente.append(f"entitati ramase fara ore, sterse: {orfani}")

    rand = _upsert_sursa(s, sursa, an_universitar)
    rand.ingestat_la = sursa.actualizat
    s.flush()
    rap.ingestate.append(
        f"sem {sursa.semestru} / {sursa.fel}: {raport.pagini} pagini, "
        f"{raport.ore} ore -> {raport.ore - consolidare.ore_sterse} dupa consolidare"
    )


def _sterge_semestrul(s: Session, *, an_universitar: str, semestru: int) -> None:
    """Sterge orele semestrului, ca reingestul sa nu lase in urma activitati mutate."""
    perioade = list(
        s.scalars(
            select(Perioada.id).where(
                Perioada.an_univ == an_universitar, Perioada.semestru == semestru
            )
        )
    )
    if perioade:
        s.execute(delete(Ora).where(Ora.perioada_id.in_(perioade)))
        s.flush()


def curata_orfanii(s: Session) -> dict[str, int]:
    """Sterge profesorii, materiile si salile la care nu mai trimite nicio ora.

    Ingestul insereaza si valorile pe care nu le-a putut confirma -- altfel ora ar ramane
    fara profesor, iar coada de verificare n-ar avea ce arata. Dupa o reluare, cele care nu
    s-au mai citit la fel raman agatate de nimic. Lasate acolo, tabela creste la fiecare
    rulare si duce si numerele din interfata in eroare ("205 profesori" pentru o facultate
    care are ~197).
    """
    from orar.db.models import Materie, Profesor, Sala

    sterse: dict[str, int] = {}
    for model, camp in (
        (Profesor, Ora.profesor_id),
        (Materie, Ora.materie_id),
        (Sala, Ora.sala_id),
    ):
        folosite = select(camp).where(camp.is_not(None))
        rezultat = s.execute(delete(model).where(model.id.not_in(folosite)))
        if rezultat.rowcount:
            sterse[model.__tablename__] = rezultat.rowcount
    s.flush()
    return sterse
