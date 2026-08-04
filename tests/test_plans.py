"""Planurile de invatamant: parsarea tabelului si legarea de abrevierile din orar.

Fragmentul de mai jos e o copie fidela a ce scoate `pdftotext -layout` dintr-un plan real,
cu alinierea coloanelor pastrata -- ea **e** informatia: fara ea nu s-ar sti care numar e C,
care S si care credite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from orar.db.models import Materie
from orar.domain.abbrev import bucati, cuvinte_semnificative, potriveste, scor
from orar.ingest.plans import DisciplinaPlan, are_strat_de_text, incarca_planuri, parseaza

PLAN = """
UNIVERSITATEA DIN BUCUREŞTI
Programul de studii universitare de licență Informatică

ANUL I 2025-2026 - PLAN DE ÎNVĂȚĂMÂNT
                                                              Semestrul I                    Semestrul II
 Nr.                                        Tipul
                Discipline obligatorii              Tip oră        Forma de   Nr. de
 Crt.                                    disciplinei
                                                   C   S   L   P   evaluare   credite   C   S   L   P
 1.     Structuri algebrice în informatică    DF    2   2   -   -      E         4      -   -   -   -    -    -
 2.     Baze de date                          DF    -   -   -   -      -         -      2   -   2   -    E    5
 3.     Programare orientată pe obiecte       DS    -   -   -   -      -         -      3   1   2   -    E    6
                     Total                          12  8   6   1    5E+3V    32 ECTS

                Discipline facultative               Tip oră       Forma de   Nr. de
  4     Etica si integritate academica        DC    2   2   -   -      V         2      -   -   -   -    -    -

ANUL II 2025-2026 - PLAN DE ÎNVĂȚĂMÂNT
                Discipline obligatorii               Tip oră       Forma de   Nr. de
 1.     Ob.11 Algoritmi avansați              DS    2   1   1   -      E         5      -   -   -   -    -    -
"""


@pytest.fixture(scope="module")
def discipline() -> list[DisciplinaPlan]:
    return parseaza(PLAN, sursa="test")


# --------------------------------------------------------------------- parsare


def test_gaseste_toate_randurile(discipline):
    assert [d.nume for d in discipline] == [
        "Structuri algebrice în informatică",
        "Baze de date",
        "Programare orientată pe obiecte",
        "Etica si integritate academica",
        "Algoritmi avansați",
    ]


def test_randul_de_total_nu_e_disciplina(discipline):
    assert not any("Total" in d.nume for d in discipline)


def test_coloanele_numerice(discipline):
    d = discipline[0]
    assert (d.nr_ore_c, d.nr_ore_s, d.nr_ore_l, d.nr_ore_p) == (2, 2, None, None)
    assert (d.credite, d.forma_evaluare, d.tip_disciplina) == (4, "E", "DF")


def test_semestrul_e_cel_in_care_are_credite(discipline):
    """Un rand acopera amandoua semestrele; disciplina e in cel cu valori, nu cu liniute."""
    assert discipline[0].semestru == 1
    assert discipline[1].semestru == 2
    assert (discipline[1].nr_ore_c, discipline[1].nr_ore_l) == (2, 2)
    assert discipline[1].credite == 5


def test_anul_si_sectiunea_tin_pana_la_urmatorul_titlu(discipline):
    dupa_nume = {d.nume: d for d in discipline}
    assert dupa_nume["Structuri algebrice în informatică"].an == 1
    assert dupa_nume["Structuri algebrice în informatică"].tip_materie == "obligatorie"
    assert dupa_nume["Etica si integritate academica"].tip_materie == "facultativa"
    assert dupa_nume["Algoritmi avansați"].an == 2
    assert dupa_nume["Algoritmi avansați"].tip_materie == "obligatorie"


def test_codul_de_master_nu_intra_in_denumire(discipline):
    """`Ob.11 Algoritmi avansați` -- codul e al planului, nu parte din nume."""
    assert "Ob.11" not in " ".join(d.nume for d in discipline)


def test_programul_se_retine(discipline):
    assert discipline[0].program == "Informatică"


def test_titlul_sectiunii_poate_fi_precedat_de_altceva():
    """La CTI antetul e `Nr. Crt.  Discipline obligatorii  ...`, nu la inceput de rand."""
    text = """ANUL I 2025-2026 - PLAN DE ÎNVĂȚĂMÂNT
 Nr. Crt.        Discipline obligatorii             Tip oră
 1.     Analiză matematică                   DF    2   2   -   -      E        5
"""
    assert parseaza(text)[0].tip_materie == "obligatorie"


def test_fisierul_cu_font_propriu_e_recunoscut():
    """Textul iese ca `'LVFLSOLQH`; niciun cuvant real nu apare."""
    assert are_strat_de_text(PLAN)
    assert not are_strat_de_text("$OJHEU OLQLDU ') ( \n 'LVFLSOLQH REOLJDWRULL")


# ------------------------------------------------------------------ abrevieri


@pytest.mark.parametrize(
    ("abreviere", "denumire"),
    [
        ("StructDate", "Structuri de date"),
        ("BD", "Baze de date"),
        ("POO", "Programare orientată pe obiecte"),
        ("ArhSistCalcul", "Arhitectura sistemelor de calcul"),
        ("Geom&AlgLin", "Geometrie și algebră liniară"),
        ("LogMat&Comp", "Logică matematică și computațională"),
        ("LbForm&Autom", "Limbaje formale și automate"),
        ("MatematiciSpeciale", "Matematici speciale"),
        ("ComputerVision", "Vedere artificială / Computer Vision"),
        ("InvatAutom", "Învățare automată / Advanced Machine Learning"),
    ],
)
def test_abrevierea_se_explica(abreviere, denumire):
    assert scor(abreviere, denumire) >= 0.75, (bucati(abreviere), cuvinte_semnificative(denumire))


@pytest.mark.parametrize(
    ("abreviere", "denumire"),
    [
        ("StructDate", "Baze de date"),
        ("BD", "Programare orientată pe obiecte"),
        ("Geom&AlgLin", "Geometrie descriptivă"),
        ("ArhSistCalcul", "Arhitectura sistemelor software"),
    ],
)
def test_abrevierea_nu_se_explica(abreviere, denumire):
    assert scor(abreviere, denumire) < 0.75


def test_cuvintele_de_legatura_nu_conteaza():
    """`de`, `si`, `pe` nu apar niciodata in abreviere."""
    assert cuvinte_semnificative("Metode de dezvoltare software") == cuvinte_semnificative(
        "Metode dezvoltare software"
    )


def test_ambiguitatea_reala_se_vede():
    """`BD` chiar nu distinge intre cele doua; abrevierea din sursa e ambigua, nu codul."""
    gasite = potriveste("BD", ["Baze de date", "Big Data", "Structuri de date"])
    assert [d for d, _ in gasite] == ["Big Data", "Baze de date"]
    assert gasite[0][1] == gasite[1][1]


# -------------------------------------------------------------------- incarcare


def test_incarcarea_completeaza_materia(db, discipline):
    materie = db.scalar(select(Materie).where(Materie.nume == "BD"))
    assert materie is not None
    try:
        rap = incarca_planuri(db, [d for d in discipline if d.nume == "Baze de date"])
        assert rap.materii_completate == 1
        assert (materie.credite, materie.forma_evaluare) == (5, "E")
        assert materie.denumire == "Baze de date"
        assert (materie.nr_ore_c, materie.nr_ore_l) == (2, 2)
    finally:
        db.rollback()


def test_materia_fara_corespondent_ramane_goala(db, discipline):
    try:
        rap = incarca_planuri(db, [d for d in discipline if d.nume == "Baze de date"])
        assert rap.fara_corespondent, "restul materiilor n-au corespondent in fragmentul asta"
        alta = db.scalar(select(Materie).where(Materie.nume == "POO"))
        assert alta is None or alta.credite is None
    finally:
        db.rollback()


def test_aceeasi_disciplina_scrisa_in_doua_feluri_nu_e_ambigua(db):
    """`Tehnici Web` si `Tehnici web` sunt aceeasi disciplina, nu doua intre care sa alegem."""
    from orar.ingest.plans import _chiar_ambiguu

    assert not _chiar_ambiguu([("Tehnici Web", 1.0), ("Tehnici web", 1.0)])
    assert not _chiar_ambiguu([("Big Data", 1.0), ("Big Data / Big Data", 1.0)])
    assert _chiar_ambiguu([("Big Data", 1.0), ("Baze de date", 1.0)])
