"""Ridica activitatile comune la nodul de serie/an caruia ii apartin de fapt.

Problema
--------
Fiecare pagina din PDF e *autonoma*: pagina grupei 244 arata si cursurile care se tin cu
toata seria 24. Acelasi curs apare deci pe paginile 241, 242, 243 si 244, iar loader-ul
naiv creeaza patru randuri ORA identice:

    Amf.501  marti 14:00-17:00  POO (curs)  Paun A  -> grupa 141
    Amf.501  marti 14:00-17:00  POO (curs)  Paun A  -> grupa 142
    Amf.501  marti 14:00-17:00  POO (curs)  Paun A  -> grupa 143
    Amf.501  marti 14:00-17:00  POO (curs)  Paun A  -> grupa 144

Consecinte, ambele grave:
  - `/sala/Amf.501` arata patru activitati suprapuse in acelasi slot, deci pare
    supra-rezervata, iar detectia de conflicte da fals pozitiv;
  - ierarhia Serie -> Grupa ramane goala: niciun curs nu apartine seriei, desi exact
    asta e cerinta -- o ora de serie sa fie vizibila tuturor grupelor copil.

Solutie
-------
Grupam activitatile identice si le mutam la **cel mai apropiat stramos comun** (LCA):

  - daca proprietarii sunt *exact* toate grupele-copil ale LCA-ului, ora e a intregii
    serii/an => o mutam acolo si stergem duplicatele. Vizibilitatea vine din ierarhie.
  - daca sunt doar o parte, mutarea ar face-o vizibila si celor care nu o au => pastram
    un singur rand si legam explicit proprietarii reali prin ORA_GRUPA.

In ambele cazuri raman `1` rand per activitate reala, deci ocuparea salilor devine corecta.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orar.db.models import Grupa, Ora, OraGrupa

log = logging.getLogger(__name__)

__all__ = ["RaportConsolidare", "consolideaza"]


@dataclass
class RaportConsolidare:
    grupuri_identice: int = 0
    ore_sterse: int = 0
    ridicate_la_serie: int = 0
    ridicate_partial: int = 0
    legaturi_adaugate: int = 0
    exemple: list[str] = field(default_factory=list)
    #: Perechi identice in tot afara de ora de sfarsit -- erori de extragere in sursa.
    suspecte: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        linii = [
            f"grupuri de activitati identice : {self.grupuri_identice}",
            f"randuri ORA eliminate          : {self.ore_sterse}",
            f"ridicate la serie/an (complet) : {self.ridicate_la_serie}",
            f"pastrate cu legaturi explicite : {self.ridicate_partial}",
            f"legaturi ORA_GRUPA adaugate    : {self.legaturi_adaugate}",
        ]
        if self.suspecte:
            linii.append(f"durate contradictorii in sursa : {len(self.suspecte)} (vezi -v)")
        return "\n".join(linii)


def _cheie(o: Ora) -> tuple:
    """Identitatea unei activitati, independent de grupa care o gazduieste."""
    return (
        o.perioada_id,
        o.materie_id,
        o.profesor_id,
        o.sala_id,
        o.zi_saptamana,
        o.ora_inceput,
        o.ora_sfarsit,
        o.tip_ora_materie,
        o.frecventa,
        o.saptamani,
        o.semigrupa,
    )


def _cale_la_radacina(g: Grupa, parinti: dict[int, int | None]) -> list[int]:
    """[nod, parinte, ..., radacina]"""
    cale = [g.id]
    vazute = {g.id}
    cur = parinti.get(g.id)
    while cur is not None and cur not in vazute:
        cale.append(cur)
        vazute.add(cur)
        cur = parinti.get(cur)
    return cale


def _lca(ids: list[int], parinti: dict[int, int | None], noduri: dict[int, Grupa]) -> int | None:
    """Cel mai apropiat stramos comun al unui set de noduri."""
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]

    cai = [list(reversed(_cale_la_radacina(noduri[i], parinti))) for i in ids]  # radacina -> nod
    comun: int | None = None
    for nivel in zip(*cai, strict=False):
        if len(set(nivel)) == 1:
            comun = nivel[0]
        else:
            break
    return comun


def consolideaza(s: Session, *, an_universitar: str | None = None) -> RaportConsolidare:
    """Deduplica activitatile repetate pe paginile grupelor din aceeasi serie."""
    rap = RaportConsolidare()

    stmt = select(Grupa)
    if an_universitar:
        stmt = stmt.where(Grupa.an_universitar == an_universitar)
    noduri = {g.id: g for g in s.execute(stmt).scalars()}
    parinti = {g.id: g.parinte_id for g in noduri.values()}

    #: copiii directi de tip 'grupa' ai fiecarui nod -- referinta pentru "complet"
    copii_grupa: dict[int, set[int]] = defaultdict(set)
    for g in noduri.values():
        if g.parinte_id is not None and g.tip == "grupa":
            copii_grupa[g.parinte_id].add(g.id)

    ore_stmt = select(Ora)
    if an_universitar:
        ore_stmt = ore_stmt.join(Ora.grupa).where(Grupa.an_universitar == an_universitar)

    pe_cheie: dict[tuple, list[Ora]] = defaultdict(list)
    for o in s.execute(ore_stmt).scalars():
        pe_cheie[_cheie(o)].append(o)

    for lot in pe_cheie.values():
        if len(lot) < 2:
            continue
        proprietari = {o.grupa_id for o in lot}
        if len(proprietari) < 2:
            # Duplicate exacte in aceeasi grupa: pastram unul singur.
            rap.grupuri_identice += 1
            for o in lot[1:]:
                s.delete(o)
                rap.ore_sterse += 1
            continue

        rap.grupuri_identice += 1
        tinta = _lca(sorted(proprietari), parinti, noduri)
        pastrat, restul = lot[0], lot[1:]

        if tinta is not None and tinta not in proprietari and copii_grupa.get(tinta) == proprietari:
            # Toate grupele-copil ale LCA-ului o au => e o ora de serie/an.
            # Mutam prin *relatie*, nu prin FK: altfel `ora.grupa` ramane obiectul vechi in
            # identity map si orice cod care citeste in aceeasi sesiune vede grupa gresita.
            pastrat.grupa = noduri[tinta]
            rap.ridicate_la_serie += 1
            if len(rap.exemple) < 8:
                rap.exemple.append(
                    f"{noduri[tinta].nume}: {pastrat.zi_saptamana} "
                    f"{pastrat.ora_inceput:%H:%M} {pastrat.materie.nume if pastrat.materie else '?'} "
                    f"({len(proprietari)} grupe)"
                )
        else:
            # Set partial: pastram proprietarul original si legam restul explicit.
            rap.ridicate_partial += 1
            existente = {
                r[0]
                for r in s.execute(select(OraGrupa.grupa_id).where(OraGrupa.ora_id == pastrat.id))
            }
            for gid in proprietari - {pastrat.grupa_id} - existente:
                s.add(OraGrupa(ora_id=pastrat.id, grupa_id=gid))
                rap.legaturi_adaugate += 1

        for o in restul:
            s.execute(delete(OraGrupa).where(OraGrupa.ora_id == o.id))
            s.delete(o)
            rap.ore_sterse += 1

    _detecteaza_durate_contradictorii(pe_cheie, rap)
    s.flush()
    return rap


def _detecteaza_durate_contradictorii(
    pe_cheie: dict[tuple, list[Ora]], rap: RaportConsolidare
) -> None:
    """Semnaleaza activitati identice care difera DOAR prin ora de sfarsit.

    Aceeasi ora aparuta pe doua pagini nu poate dura si 2 si 3 ore -- una dintre pagini a
    fost extrasa gresit (numarul de coloane acoperite de celula a fost citit gresit).
    Nu ghicim care e corecta: consolidarea le lasa ca randuri separate si le raporteaza,
    ca sa nu inventam date. Segmentarea geometrica din Etapa 4 rezolva clasa asta de erori
    la sursa, pentru ca latimea celulei e pura aritmetica pe caroiaj.
    """
    fara_sfarsit: dict[tuple, list[Ora]] = defaultdict(list)
    for cheie, lot in pe_cheie.items():
        # cheia e (perioada, materie, prof, sala, zi, inceput, sfarsit, tip, frec, sapt, semi)
        redusa = cheie[:6] + cheie[7:]
        for o in lot:
            fara_sfarsit[redusa].append(o)

    for lot in fara_sfarsit.values():
        durate = {o.ora_sfarsit for o in lot}
        if len(durate) < 2:
            continue
        exemplu = lot[0]
        variante = ", ".join(
            f"{o.ora_inceput:%H:%M}-{o.ora_sfarsit:%H:%M} ({o.sursa_pagina})" for o in lot
        )
        rap.suspecte.append(
            f"{exemplu.materie.nume if exemplu.materie else '?'} "
            f"{exemplu.zi_saptamana} in {exemplu.sala.nume if exemplu.sala else '?'}: {variante}"
        )
