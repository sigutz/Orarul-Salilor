"""Potrivirea numelui prescurtat cu cel intreg.

Toate perechile de mai jos sunt reale: prescurtarea vine dintr-o celula a orarului grupelor,
numele intreg din titlul paginii aceluiasi om din orarul profesorilor. Regulile aSc nu sunt
cele evidente, iar fiecare rand de aici a fost intai o potrivire ratata sau gresita.
"""

from __future__ import annotations

import pytest

from orar.domain.names import potriveste, se_potrivesc

#: (prescurtat, intreg, ce anume ilustreaza cazul)
PERECHI = [
    ("Alexe B", "Alexe Bogdan", "cazul simplu"),
    ("Cheval H", "Cheval Andrei-Horatiu", "initiala e a *ultimului* prenume, nu a primului"),
    ("Gavrila A", "Gavrila Florin-Alexandru", "idem"),
    ("Micluta M", "Micluta-Campeanu Marius", "familia compusa, taiata la primul cuvant"),
    ("BanuDem. I", "Banu Demergian lulia", "familia compusa, lipita si taiata in mijloc"),
    ("Marin Le", "Marin (Velcescu) Letitia", "numele de fata in paranteze; doua litere"),
    ("Grecu AE", "Grecu Alina-Elena", "cate o initiala pentru fiecare prenume"),
    ("Vrinceanu RT", "Vrinceanu Radu-Tudor", "idem"),
    ("Toma AS", "Toma Anda Stefania", "idem, cu prenume separate prin spatiu"),
    ("Stanciu M", "Stanciu Miron-lon", "`lon` citit gresit pentru `Ion`"),
    ("Hirica I", "Hirica lulia", "idem, pe prenume"),
    ("Campian R", "Campian loan Razvan", "idem, cu doua prenume"),
]

NEPERECHI = [
    ("Ion L", "lonescu loan", "familia nu se taie in mijlocul unui cuvant: alt om"),
    ("Ion L", "lonescu Costin-loan", "idem"),
    ("Marin Li", "Marinescu Livia", "idem"),
    ("Cheval H", "Popescu Horatiu", "familie diferita"),
    ("Popescu A", "Popescu Dan", "initiala nu se potriveste"),
    ("Grecu AE", "Grecu Elena-Alina", "initialele conteaza in ordine"),
    ("Toma AS", "Toma Stefania Anda", "idem"),
    ("Marin Le", "Marin Gheorghe", "doua litere care nu prind nimic"),
]


@pytest.mark.parametrize(("scurt", "intreg", "motiv"), PERECHI, ids=[p[2] for p in PERECHI])
def test_se_potrivesc(scurt, intreg, motiv):
    assert se_potrivesc(scurt, intreg), motiv


@pytest.mark.parametrize(("scurt", "intreg", "motiv"), NEPERECHI, ids=[p[2] for p in NEPERECHI])
def test_nu_se_potrivesc(scurt, intreg, motiv):
    assert not se_potrivesc(scurt, intreg), motiv


def test_ambiguitatea_se_vede():
    """`Popescu A` chiar nu-i distinge: prescurtarea din sursa e ambigua, nu codul."""
    candidati = ["Popescu Adrian", "Popescu Ana", "Popescu Dan"]
    assert potriveste("Popescu A", candidati) == ["Popescu Adrian", "Popescu Ana"]


def test_gol_nu_potriveste_nimic():
    assert not se_potrivesc("", "Alexe Bogdan")
    assert not se_potrivesc("Alexe B", "")
    assert potriveste("Alexe B", []) == []


def test_diacriticele_nu_conteaza():
    assert se_potrivesc("Tataram M", "Țățăram Mihai")
