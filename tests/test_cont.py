"""Conturi: parole, sesiuni, CSRF si filtrarea orarului dupa preferinte.

Contul nu inchide nimic -- orarul e public. El doar scuteste de cautare: cine si-a ales
grupa intra pe `/` si vede direct orarul ei, fara laboratoarele celeilalte semigrupe si
fara optionalele la care nu s-a inscris. Testele verifica exact asta, plus ca filtrarea
**se vede** si se poate scoate: un orar din care lipsesc tacit activitati e mai rau decat
unul complet.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import delete, select

from orar.db.models import Grupa, User, UserOptional
from orar.web.auth import hash_parola, verifica_parola

PAROLA = "parolabuna123"


@pytest.fixture(autouse=True)
def fara_conturi(db):
    """Fiecare test porneste fara conturi; sesiunea de baza e comuna intre teste."""
    db.execute(delete(UserOptional))
    db.execute(delete(User))
    db.commit()
    yield
    db.execute(delete(UserOptional))
    db.execute(delete(User))
    db.commit()


def _csrf(client, cale: str = "/inregistrare") -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', client.get(cale).text)
    assert m, f"{cale} nu contine token CSRF"
    return m.group(1)


def _inregistreaza(client, email: str = "ana@example.com", grupa_id: str = "") -> None:
    r = client.post(
        "/inregistrare",
        data={
            "nume": "Ana Pop",
            "email": email,
            "parola": PAROLA,
            "grupa_id": grupa_id,
            "csrf": _csrf(client),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:400]


# --------------------------------------------------------------------- parole


def test_parola_se_verifica():
    h = hash_parola(PAROLA)
    assert verifica_parola(PAROLA, h)
    assert not verifica_parola("altceva", h)


def test_doua_hashuri_ale_aceleiasi_parole_difera():
    """Sare diferita de fiecare data: doua conturi cu aceeasi parola nu se recunosc intre ele."""
    assert hash_parola(PAROLA) != hash_parola(PAROLA)


def test_parametrii_sunt_in_hash():
    """Ca sa putem creste costul mai tarziu fara sa invalidam conturile existente."""
    schema, n, r, p, _, _ = hash_parola(PAROLA).split("$")
    assert schema == "scrypt"
    assert int(n) >= 2**14 and int(r) >= 8 and int(p) >= 1


@pytest.mark.parametrize("stocat", [None, "", "aiurea", "bcrypt$1$2$3$4$5", "scrypt$a$b$c$d$e"])
def test_hash_stricat_nu_arunca(stocat):
    """Un rand corupt in baza inseamna "nu te pot autentifica", nu 500."""
    assert verifica_parola(PAROLA, stocat) is False


# ------------------------------------------------------------------ inregistrare


def test_inregistrare_si_autentificare(client):
    _inregistreaza(client)
    assert "Ana" in client.get("/").text


def test_parola_prea_scurta_e_respinsa(client, db):
    r = client.post(
        "/inregistrare",
        data={"nume": "X", "email": "x@y.ro", "parola": "scurt", "csrf": _csrf(client)},
    )
    assert r.status_code == 400
    assert db.scalar(select(User)) is None


def test_email_duplicat_e_respins(client):
    _inregistreaza(client)
    r = client.post(
        "/inregistrare",
        data={
            "nume": "Altcineva",
            "email": "ANA@example.com",  # aceeasi adresa, alt caz
            "parola": PAROLA,
            "csrf": _csrf(client),
        },
    )
    assert r.status_code == 409


def test_parola_nu_se_stocheaza_in_clar(client, db):
    _inregistreaza(client)
    user = db.scalar(select(User))
    assert PAROLA not in (user.parola_hash or "")
    assert user.parola_hash.startswith("scrypt$")


# ------------------------------------------------------------------- intrare


def test_intrare_cu_parola_buna(client):
    _inregistreaza(client)
    client.post("/iesire", data={"csrf": _csrf(client, "/")}, follow_redirects=False)
    r = client.post(
        "/intrare",
        data={"email": "ana@example.com", "parola": PAROLA, "csrf": _csrf(client, "/intrare")},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_mesajul_nu_spune_daca_adresa_exista(client):
    """Acelasi raspuns pentru cont inexistent si pentru parola gresita."""
    _inregistreaza(client)
    client.post("/iesire", data={"csrf": _csrf(client, "/")}, follow_redirects=False)

    gresita = client.post(
        "/intrare",
        data={"email": "ana@example.com", "parola": "altceva", "csrf": _csrf(client, "/intrare")},
    )
    inexistent = client.post(
        "/intrare",
        data={"email": "nimeni@example.com", "parola": PAROLA, "csrf": _csrf(client, "/intrare")},
    )
    assert gresita.status_code == inexistent.status_code == 401
    assert "Email sau parolă greșită." in gresita.text
    assert "Email sau parolă greșită." in inexistent.text


def test_fara_token_csrf_nu_te_autentifici(client):
    _inregistreaza(client)
    client.post("/iesire", data={"csrf": _csrf(client, "/")}, follow_redirects=False)
    r = client.post("/intrare", data={"email": "ana@example.com", "parola": PAROLA, "csrf": "fals"})
    assert "Sesiune expirată" in r.text
    assert "Ana" not in client.get("/").text, "nu trebuia sa fie logat"


def test_iesirea_cere_si_ea_token(client):
    _inregistreaza(client)
    client.post("/iesire", data={"csrf": "fals"}, follow_redirects=False)
    assert "Ana" in client.get("/").text, "un POST strain nu are voie sa te deconecteze"


# ---------------------------------------------------------------- preferinte


def test_preferintele_cer_autentificare(client):
    r = client.get("/preferinte", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/intrare"


def test_acasa_duce_direct_la_grupa_preferata(client, db):
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/grupa/{grupa.slug}"


def test_lista_completa_ramane_accesibila(client, db):
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    assert client.get("/acasa", follow_redirects=False).status_code == 200


def test_semigrupa_preferata_filtreaza_orarul(client, db):
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    client.post(
        "/preferinte",
        data={"grupa_id": str(grupa.id), "semigrupa": "Gr_1", "csrf": _csrf(client, "/preferinte")},
        follow_redirects=False,
    )
    filtrat = client.get("/grupa/244").text
    assert "Gr 2" not in filtrat and "Gr_2" not in filtrat
    assert "Gr 1" in filtrat or "Gr_1" in filtrat


def test_filtrarea_se_vede_si_se_poate_scoate(client, db):
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    client.post(
        "/preferinte",
        data={"grupa_id": str(grupa.id), "semigrupa": "Gr_1", "csrf": _csrf(client, "/preferinte")},
        follow_redirects=False,
    )
    pagina = client.get("/grupa/244")
    assert "filtrată" in pagina.text and "?tot=1" in pagina.text
    complet = client.get("/grupa/244?tot=1").text
    assert "Gr 2" in complet or "Gr_2" in complet


def test_preferintele_nu_afecteaza_orarul_altei_grupe(client, db):
    """Filtrele sunt ale grupei tale; pe orarul altcuiva ar ascunde activitati fara motiv."""
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    client.post(
        "/preferinte",
        data={"grupa_id": str(grupa.id), "semigrupa": "Gr_1", "csrf": _csrf(client, "/preferinte")},
        follow_redirects=False,
    )
    alta = client.get("/grupa/243").text
    assert "Gr 2" in alta or "Gr_2" in alta


def test_nu_te_poti_inscrie_la_un_nod_care_nu_e_optional(client, db):
    """Un `<input>` fabricat n-are voie sa lege contul de orice nod din arbore."""
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "244"))
    serie = db.scalar(select(Grupa).where(Grupa.tip == "serie"))
    _inregistreaza(client, grupa_id=str(grupa.id))
    client.post(
        "/preferinte",
        data={
            "grupa_id": str(grupa.id),
            "optional": [str(serie.id)],
            "csrf": _csrf(client, "/preferinte"),
        },
        follow_redirects=False,
    )
    db.expire_all()
    user = db.scalar(select(User))
    assert [g.id for g in user.optionale] == []


def test_pagina_publica_ramane_publica(client):
    """Fara cont, tot ce conteaza se vede la fel."""
    for cale in ("/", "/grupa/244", "/sala/701", "/sala"):
        assert client.get(cale, follow_redirects=False).status_code == 200, cale


def test_inscrierea_la_optionale_chiar_filtreaza(client, db):
    """Regresie: filtrul se uita la `ORA.ID_GRUPA` (pachetul), nu la `ORA_GRUPA.ID_GRUPA`.

    Cea din urma e *tinta* legaturii -- seria careia i se ofera pachetul -- deci e implinita
    oricum de lantul studentului, iar conditia nu filtra nimic.
    """
    grupa = db.scalar(select(Grupa).where(Grupa.slug == "331"))
    _inregistreaza(client, grupa_id=str(grupa.id))

    pachete = re.findall(r'name="optional" value="(\d+)"', client.get("/preferinte").text)
    assert len(pachete) >= 2, "grupa asta ar trebui sa aiba mai multe pachete legate"

    def cate(url: str) -> int:
        # In productie fiecare cerere are sesiunea ei; aici clientul si testul o impart,
        # deci colectia `user.optionale` ramane cea dinainte de POST daca n-o expiram.
        db.expire_all()
        m = re.search(r"<strong>(\d+)</strong> activități", client.get(url).text)
        return int(m.group(1))

    toate = cate("/grupa/331")
    client.post(
        "/preferinte",
        data={
            "grupa_id": str(grupa.id),
            "optional": [pachete[0]],
            "csrf": _csrf(client, "/preferinte"),
        },
        follow_redirects=False,
    )
    unul = cate("/grupa/331")
    assert unul < toate, "inscrierea la un singur pachet trebuie sa reduca lista"
    assert cate("/grupa/331?tot=1") == toate, "`?tot=1` arata tot"

    client.post(
        "/preferinte",
        data={"grupa_id": str(grupa.id), "optional": pachete, "csrf": _csrf(client, "/preferinte")},
        follow_redirects=False,
    )
    assert cate("/grupa/331") == toate, "inscris la toate = ca si cum n-ai filtra"
