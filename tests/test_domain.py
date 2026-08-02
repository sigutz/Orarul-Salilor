"""Normalizarea salilor si aritmetica saptamanilor."""

from __future__ import annotations

from datetime import date

import pytest

from orar.domain.rooms import TipSala, normalizeaza_sala
from orar.domain.weeks import (
    AncoraSaptamana,
    CalendarAcademic,
    Paritate,
    parse_ancore,
    parse_interval_saptamani,
)

# --------------------------------------------------------------------------- sali


@pytest.mark.parametrize(
    ("brut", "nume", "tip"),
    [
        ("L-507", "L.507", TipSala.FIZICA),
        ("L.506", "L.506", TipSala.FIZICA),
        ("S-214", "S.214", TipSala.FIZICA),
        ("S.213", "S.213", TipSala.FIZICA),
        ("Amf.501", "Amf.501", TipSala.FIZICA),
        ("L-414 Robotica", "L.414 Robotica", TipSala.FIZICA),
        ("IMAR (sala 309)", "IMAR 309", TipSala.EXTERNA),
        ("Fac.Fizica -Magurele", "Fac.Fizica -Magurele", TipSala.EXTERNA),
        ("ONLINE", "ONLINE", TipSala.VIRTUALA),
        ("", "Nespecificat", TipSala.VIRTUALA),
    ],
)
def test_normalizare_sala(brut, nume, tip):
    s = normalizeaza_sala(brut)
    assert s.nume == nume
    assert s.tip is tip


def test_separatorul_nu_conteaza_pentru_identitate():
    """`L-507` si `L.507` trebuie sa duca la aceeasi sala -- de asta exista modulul."""
    assert normalizeaza_sala("L-507").slug == normalizeaza_sala("L.507").slug
    assert normalizeaza_sala("S-214").slug == normalizeaza_sala("S.214").slug


def test_doar_salile_fizice_intra_in_ocupare():
    assert normalizeaza_sala("Amf.701").este_bookabila
    assert not normalizeaza_sala("ONLINE").este_bookabila
    assert not normalizeaza_sala("IMAR (sala 412)").este_bookabila


def test_sali_distincte_raman_distincte():
    assert normalizeaza_sala("L-507").slug != normalizeaza_sala("L.506").slug


# ------------------------------------------------------------------------ saptamani


#: Exact cele doua ancore publicate de FMI pentru semestrul II 2025-2026.
#: Sunt la doua saptamani calendaristice distanta, dar la una academica: intre ele cade
#: vacanta de Paste (13-17 aprilie), care nu se numara.
@pytest.fixture
def calendar() -> CalendarAcademic:
    return CalendarAcademic(
        ancore=[
            AncoraSaptamana(inceput=date(2026, 4, 6), numar=7, paritate=Paritate.IMPARA),
            AncoraSaptamana(inceput=date(2026, 4, 20), numar=8, paritate=Paritate.PARA),
        ]
    )


def test_ancora_se_normalizeaza_la_luni():
    a = AncoraSaptamana(inceput=date(2026, 4, 9), numar=7, paritate=Paritate.IMPARA)
    assert a.inceput == date(2026, 4, 6)


def test_saptamana_ancorei_e_exacta(calendar):
    s = calendar.saptamana(date(2026, 4, 8))
    assert (s.numar, s.paritate, s.exact) == (7, Paritate.IMPARA, True)


def test_a_doua_ancora(calendar):
    s = calendar.saptamana(date(2026, 4, 21))
    assert (s.numar, s.paritate, s.exact) == (8, Paritate.PARA, True)


def test_numerotarea_sare_peste_vacanta(calendar):
    """13-17 aprilie e intre ancore, dar numerotarea nu e contigua acolo => necunoscut.

    Aritmetica simpla ar fi raspuns "saptamana 8", ceea ce e gresit: FMI numeste
    saptamana 8 abia intervalul 20-24 aprilie.
    """
    assert calendar.saptamana(date(2026, 4, 15)) is None


def test_paritatea_e_paritatea_numarului(calendar):
    for zi, numar in [(date(2026, 4, 8), 7), (date(2026, 4, 21), 8)]:
        s = calendar.saptamana(zi)
        assert s.paritate is Paritate.din_numar(numar)


def test_extrapolarea_in_afara_ancorelor_e_marcata_inexacta(calendar):
    s = calendar.saptamana(date(2026, 4, 27))
    assert s is not None and s.numar == 9 and not s.exact


def test_in_afara_semestrului_nu_exista_saptamana(calendar):
    assert calendar.saptamana(date(2026, 8, 2)) is None
    assert calendar.saptamana(date(2026, 1, 5)) is None


def test_calendar_fara_ancore():
    assert CalendarAcademic().saptamana(date(2026, 4, 8)) is None


def test_parse_ancore_din_textul_paginii_fmi():
    text = (
        "Săptămâna 06.04.2026 – 09.04.2026 este săptămână impară (sapt 7). "
        "Săptămâna 20.04.2026 – 24.04.2026 este săptămână pară (sapt 8)."
    )
    ancore = parse_ancore(text)
    assert len(ancore) == 2
    assert ancore[0].numar == 7 and ancore[0].paritate is Paritate.IMPARA
    assert ancore[1].numar == 8 and ancore[1].paritate is Paritate.PARA


def test_ancorele_fara_numar_sunt_ignorate():
    assert parse_ancore("Săptămâna 1.10.2025 – 3.10.2025 este săptămână impară.") == []


@pytest.mark.parametrize(
    ("text", "asteptat"),
    [
        ("sapt 1-7", set(range(1, 8))),
        ("sapt 8-14", set(range(8, 15))),
        ("sapt 2", {2}),
        ("sapt 5-7", {5, 6, 7}),
        ("sapt 8-10", {8, 9, 10}),
        ("", None),
        # date calendaristice libere -- nu se pot raporta la saptamani academice
        ("25 mar, 29 apr, 27 mai, 24 iun", None),
        # saptamani ISO, alta scara decat cea academica (1..14) -> nu filtram dupa ele
        ("CU s23,24,25, 26", None),
        ("SE s20+21", None),
    ],
)
def test_parse_interval_saptamani(text, asteptat):
    assert parse_interval_saptamani(text) == asteptat
