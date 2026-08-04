"""Ce citeste watcher-ul de pe pagina FMI.

Fixtura de mai jos nu e o pagina inventata: reproduce exact capcanele celei reale, in
aceeasi ordine -- doua semestre, eticheta `Orarul grupelor` de doua ori, si inca sase
linkuri `bit.ly` care nu sunt orare de grupe (tutoriate, profesori, detalii tutori).
Prototipul lua primul `bit.ly` din HTML si nimerea, dupa cum se intampla, alt semestru sau
orarul tutorilor; testele astea sunt scrise ca sa nu se mai poata intampla.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from orar.domain.weeks import Paritate
from orar.ingest.watcher import Schimbare, SursaOrar, compara, parseaza

PAGINA = """
<html><body>
<h2>Semestrul II</h2>
<p>S&#259;pt&#259;m&#226;na <b>06.04.2026 &#8211; 09.04.2026</b> este
   <b>s&#259;pt&#259;m&#226;n&#259; impar&#259;</b> (sapt 7).
   S&#259;pt&#259;m&#226;na <b>20.04.2026 &#8211; 24.04.2026</b> este
   <b>s&#259;pt&#259;m&#226;n&#259; par&#259;</b> (sapt 8).</p>
<ul>
  <li><a href="https://bit.ly/sem2grupe">Orarul grupelor</a>
      <span>(actualizat 26.04.2026, ora 19:30)</span></li>
  <li><a href="https://bit.ly/sem2prof">Orarul profesorilor</a>
      <span>(actualizat 26.04.2026, ora 19:30)</span></li>
  <li><a href="https://bit.ly/sem2tut">Orar tutoriate</a>
      <span>(actualizat 28.05.2026, ora 20:00)</span></li>
  <li><a href="https://bit.ly/sem2det">Detalii tutori, linkuri grupuri tutoriat</a></li>
</ul>
<h2>Semestrul I</h2>
<p>S&#259;pt&#259;m&#226;na <b>1.10.2025 &#8211; 3.10.2025</b> este
   <b>s&#259;pt&#259;m&#226;n&#259; impar&#259;</b>.</p>
<ul>
  <li><a href="https://bit.ly/sem1grupe">Orarul grupelor</a>
      <span>(actualizat 02.12.2025, ora 21:00)</span></li>
  <li><a href="https://bit.ly/sem1prof">Orarul profesorilor</a>
      <span>(actualizat 02.12.2025, ora 21:00)</span></li>
  <li><a href="https://bit.ly/sem1tut">Orar tutoriate</a>
      <span>(actualizat 02.12.2025, ora 13:00)</span></li>
</ul>
</body></html>
"""


@pytest.fixture(scope="module")
def stare():
    return parseaza(PAGINA)


def test_gaseste_toate_cele_patru_orare(stare):
    assert {(s.semestru, s.fel) for s in stare.surse} == {
        (2, "grupe"),
        (2, "profesori"),
        (1, "grupe"),
        (1, "profesori"),
    }


def test_nu_confunda_semestrele(stare):
    """Eticheta `Orarul grupelor` apare de doua ori; conteaza sub ce titlu de semestru sta."""
    assert stare.sursa(2, "grupe").url == "https://bit.ly/sem2grupe"
    assert stare.sursa(1, "grupe").url == "https://bit.ly/sem1grupe"


def test_ignora_linkurile_care_nu_sunt_orare_de_grupe(stare):
    urls = {s.url for s in stare.surse}
    assert "https://bit.ly/sem2tut" not in urls
    assert "https://bit.ly/sem2det" not in urls


def test_ia_data_publicata_de_facultate(stare):
    assert stare.sursa(2, "grupe").actualizat == datetime(2026, 4, 26, 19, 30)
    assert stare.sursa(1, "grupe").actualizat == datetime(2025, 12, 2, 21, 0)


def test_data_nu_se_imprumuta_de_la_sursa_urmatoare():
    """Un orar fara data proprie ramane fara, nu o ia pe a celui de sub el."""
    pagina = """<h2>Semestrul II</h2>
      <a href="https://x/a">Orarul grupelor</a>
      <p>o propozitie</p><p>alta</p><p>a treia</p><p>a patra</p><p>a cincea</p>
      <p>a sasea</p><p>a saptea</p>
      <a href="https://x/b">Orarul profesorilor</a> (actualizat 01.02.2026, ora 10:00)"""
    st = parseaza(pagina)
    assert st.sursa(2, "grupe").actualizat is None
    assert st.sursa(2, "profesori").actualizat == datetime(2026, 2, 1, 10, 0)


def test_citeste_ancorele_de_saptamana(stare):
    """Ancora fara `(sapt N)` -- cea de la semestrul I -- se ignora: fara numar, paritatea

    singura nu fixeaza numerotarea."""
    assert [(a.inceput, a.numar, a.paritate) for a in stare.ancore] == [
        (date(2026, 4, 6), 7, Paritate.IMPARA),
        (date(2026, 4, 20), 8, Paritate.PARA),
    ]


def test_semestrul_curent_e_cel_mai_recent_actualizat(stare):
    assert stare.semestru_curent == 2


def test_pagina_fara_orare_da_avertisment():
    st = parseaza("<html><body><p>site in constructie</p></body></html>")
    assert not st.surse
    assert st.avertismente


def test_eticheta_dublata_in_acelasi_semestru_nu_se_ghiceste():
    """Doua linkuri identice ca eticheta sub acelasi semestru: semnalam, nu alegem la noroc."""
    st = parseaza(
        """<h2>Semestrul II</h2>
           <a href="https://x/1">Orarul grupelor</a>
           <a href="https://x/2">Orarul grupelor</a>"""
    )
    assert st.sursa(2, "grupe").url == "https://x/1"
    assert any("de mai multe ori" in a for a in st.avertismente)


# ------------------------------------------------------------------ comparatia


def _sursa(actualizat: datetime | None = None) -> SursaOrar:
    return SursaOrar(semestru=2, fel="grupe", url="https://x", actualizat=actualizat)


def test_sursa_noua_se_ingesteaza(stare):
    assert [c.sursa.cheie for c in compara(stare, {})] == [s.cheie for s in stare.surse]


def test_sursa_neschimbata_nu_se_reia(stare):
    cunoscute = {s.cheie: s.actualizat for s in stare.surse}
    assert compara(stare, cunoscute) == []


def test_sursa_mai_noua_se_reia(stare):
    cunoscute = {s.cheie: datetime(2020, 1, 1) for s in stare.surse}
    assert len(compara(stare, cunoscute)) == len(stare.surse)


def test_fara_data_publicata_nu_reluam_degeaba():
    """Un ingest costa ~6 minute de captura; fara semnal clar, nu il pornim."""
    from orar.ingest.watcher import StarePublicata

    st = StarePublicata(surse=[_sursa(None)])
    assert compara(st, {(2, "grupe"): datetime(2020, 1, 1)}) == []


def test_schimbarea_spune_de_ce():
    s = Schimbare(_sursa(datetime(2026, 4, 26, 19, 30)), "actualizat")
    assert "sem 2" in str(s) and "grupe" in str(s)
