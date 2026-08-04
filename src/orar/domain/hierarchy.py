"""Decodarea titlului unei pagini de orar in pozitia ei din ierarhia academica.

Fiecare pagina din PDF-ul FMI are un titlu care identifica formatiunea de studiu.
Codificarea numerelor de grupa e regulata (verificat pe toate cele 98 de titluri):

    NNN  ->  cifra 1 = anul de studiu
             cifrele 1-2 = seria
             tot numarul = grupa

    "INFO Grupa 144"  ->  an 1, seria 14, grupa 144

Ierarhia rezultata (vezi `docs/formatul-orarului.md` §5):

    INFO an 2                 Nivel.SPECIALIZARE
    +-- Seria 24              Nivel.SERIE
        +-- 244               Nivel.GRUPA
            +-- 244/1         Nivel.SEMIGRUPA   (din eticheta "Gr_1" din celula)

Masteratele nu au serii, deci grupa atarna direct de specializare.
Paginile de optionale/facultative/limbi nu sunt formatiuni propriu-zise: se leaga de
grupele-tinta prin tabela de jonctiune ORA_GRUPA, nu prin PARINTE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Nivel",
    "TipPagina",
    "TitluOrar",
    "parse_titlu",
    "normalizeaza_specializare",
    "normalizeaza_semigrupa",
    "SPECIALIZARI",
]


class Nivel(StrEnum):
    """Nivelul unui nod in arborele GRUPA (coloana GRUPA.TIP)."""

    SPECIALIZARE = "specializare"
    SERIE = "serie"
    GRUPA = "grupa"
    SEMIGRUPA = "semigrupa"
    OPTIONAL = "optional"


class TipPagina(StrEnum):
    """Ce fel de pagina de orar am parsat."""

    GRUPA = "grupa"
    MASTER = "master"
    OPTIONAL_SERII = "optional_serii"
    OPTIONAL = "optional"
    FACULTATIV = "facultativ"
    LIMBI = "limbi"
    SPECIAL = "special"
    NECUNOSCUT = "necunoscut"


# Coduri canonice de specializare. Cheile sunt formele intalnite in titluri
# (normalizate: uppercase, fara punct final, spatii colapsate).
SPECIALIZARI: dict[str, str] = {
    "MATE": "MATE",
    "MATEMATICA": "MATE",
    "MATE APL": "MATE-APL",
    "MATE APLICATE": "MATE-APL",
    "MATEMATICA APLICATA": "MATE-APL",
    "MATE-INFO": "MATE-INFO",
    "MATE INFO": "MATE-INFO",
    "MATEMATICA-INFORMATICA": "MATE-INFO",
    "INFO": "INFO",
    "INFORMATICA": "INFO",
    "CTI": "CTI",
}

# Denumiri lizibile, pentru afisare in UI.
DENUMIRI_SPECIALIZARE: dict[str, str] = {
    "MATE": "Matematică",
    "MATE-APL": "Matematici Aplicate",
    "MATE-INFO": "Matematică-Informatică",
    "INFO": "Informatică",
    "CTI": "Calculatoare și Tehnologia Informației",
}

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def normalizeaza_specializare(text: str) -> str | None:
    """Aduce o scriere oarecare a specializarii la codul canonic."""
    cheie = re.sub(r"\s+", " ", text.strip().upper()).rstrip(".")
    return SPECIALIZARI.get(cheie)


def normalizeaza_semigrupa(text: str) -> str | None:
    """ "Gr 1" / "Gr_1" / "Gr1" / "gr. 2"  ->  "Gr_1" / "Gr_2".

    Intoarce None daca textul nu contine o eticheta de semigrupa.
    """
    if not text:
        return None
    m = re.search(r"\bGr\.?[\s_]*([1-4])\b", text, re.IGNORECASE)
    return f"Gr_{m.group(1)}" if m else None


def _an_din_roman_sau_cifra(text: str) -> int | None:
    text = text.strip().upper()
    if text in _ROMAN:
        return _ROMAN[text]
    return int(text) if text.isdigit() else None


@dataclass(frozen=True)
class TitluOrar:
    """Rezultatul decodarii unui titlu de pagina."""

    raw: str
    tip: TipPagina
    specializare: str | None = None
    an: int | None = None
    serie: str | None = None
    grupa: str | None = None
    #: Seriile vizate de o pagina de optionale ("INFO Seriile 33,34,35: ...").
    serii_tinta: tuple[str, ...] = ()
    #: Specializarile vizate de o pagina transversala (facultative, limbi straine).
    specializari_tinta: tuple[str, ...] = ()
    #: Codul programului de master, ex. "BDTS".
    program: str | None = None
    #: Denumirea desfasurata a programului, ex. "Baze de date si tehnologii software".
    denumire_program: str | None = None
    #: Eticheta scurta pentru afisare.
    eticheta: str = ""
    #: Slug stabil, folosit in URL-uri.
    slug: str = ""
    note: tuple[str, ...] = field(default=(), compare=False)

    @property
    def este_formatiune(self) -> bool:
        """True daca pagina descrie o grupa reala (nu un pachet de optionale)."""
        return self.tip in (TipPagina.GRUPA, TipPagina.MASTER)


def _slugify(text: str) -> str:
    text = text.lower()
    for a, b in (
        ("ă", "a"),
        ("â", "a"),
        ("î", "i"),
        ("ș", "s"),
        ("ş", "s"),
        ("ț", "t"),
        ("ţ", "t"),
    ):
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _split_specializari(text: str) -> tuple[str, ...]:
    """ "(Mate, Mate-Info, Mate Apl., Info, CTI)" -> coduri canonice."""
    out: list[str] = []
    for bucata in re.split(r"[,;]| si | și ", text):
        cod = normalizeaza_specializare(bucata)
        if cod and cod not in out:
            out.append(cod)
    return tuple(out)


# ---------------------------------------------------------------------------
# Sabloanele de titlu, in ordinea in care se incearca.
# ---------------------------------------------------------------------------

# "INFO Grupa 144", "MATE APL. Grupa 221", "MATE-INFO Grupa 211"
_RE_GRUPA = re.compile(r"^(?P<spec>[A-Za-z][\w\s.\-]*?)\s+Grupa\s+(?P<nr>\d{3})\s*$", re.IGNORECASE)

# "INFO Master 408 (SD - Sisteme distribuite)"
_RE_MASTER = re.compile(
    r"^(?P<spec>[A-Za-z][\w\s.\-]*?)\s+Master\s+(?P<nr>\d{3})"
    r"(?:\s*\((?P<cod>[^\s)]+)\s*[-–]\s*(?P<den>[^)]*)\))?\s*$",
    re.IGNORECASE,
)

# "INFO Seriile 33,34,35: Optionale an III - INFO (Curs)"
_RE_SERII = re.compile(
    r"^(?P<spec>[A-Za-z][\w\s.\-]*?)\s+Seriile\s+(?P<serii>[\d,\s]+)\s*:\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

# "Optionale an III - MATE (1)", "Optionale an I Master INFO"
_RE_OPTIONAL = re.compile(
    r"^Optionale?\s+an\s+(?P<an>[IVX]+|\d+)\s*(?:[-–]\s*)?(?P<rest>.*)$", re.IGNORECASE
)

# "Facultative an II (Mate, Mate-Info, Mate Apl., Info, CTI)"
_RE_FACULTATIV = re.compile(
    r"^Facultative\s+an\s+(?P<an>[IVX]+|\d+)\s*(?:\((?P<spec>[^)]*)\))?\s*$", re.IGNORECASE
)

# "Limbi straine - an I (Mate Info, CTI)"
_RE_LIMBI = re.compile(
    r"^Limbi\s+strain[ei]\s*[-–]?\s*an\s+(?P<an>[IVX]+|\d+)\s*(?:\((?P<spec>[^)]*)\))?\s*$",
    re.IGNORECASE,
)

# "(studenti Fizica/Robotica, an 2, grupa 201ROB)"
_RE_ROBOTICA = re.compile(
    r"studenti\s+Fizica/Robotica,\s*an\s*(?P<an>\d+),\s*grupa\s*(?P<grupa>\w+)", re.IGNORECASE
)


# Confuziile pe care recunoasterea le face constant la fontul asteia: `I` majuscul si `l`
# mic sunt aproape identice in Arial, la fel `0` si `O`. Le reparam *inainte* de parsare,
# fiindca pica exact pe partile care duc ierarhia: `an III`, `Master 403`, `Seriile 33,34`.
# Corectam numai in interiorul unui token deja omogen -- un cuvant care e altfel numai cifre
# romane, sau altfel numai cifre -- deci nu putem strica un cuvant obisnuit.
_RE_ROMAN_STRICAT = re.compile(r"\b(?=[IVXl]{2,})[IVXl]+\b")
_RE_NUMAR_STRICAT = re.compile(r"\b(?=\d*[O]\d)[\dO]{3}\b")


def _repara_specializare(m: re.Match[str]) -> str:
    """`CTl` -> `CTI`, dar numai daca rezultatul e un cod de specializare cunoscut."""
    token = m.group(0)
    if token in SPECIALIZARI or "l" not in token:
        return token
    reparat = token.replace("l", "I")
    return reparat if reparat in SPECIALIZARI else token


def curata_titlu(titlu: str) -> str:
    """Repara confuziile de glife dintr-un titlu citit cu OCR."""
    raw = re.sub(r"\s+", " ", (titlu or "").strip())
    raw = _RE_ROMAN_STRICAT.sub(lambda m: m.group(0).replace("l", "I"), raw)
    raw = _RE_NUMAR_STRICAT.sub(lambda m: m.group(0).replace("O", "0"), raw)
    # Codurile de specializare sunt o lista inchisa, deci `CTl` se repara fara risc.
    raw = re.sub(r"\b[A-Za-z]{2,4}\b", _repara_specializare, raw)
    # `Seriile` iese des `Serile`: nu e confuzie de glif, ci o litera pierduta intre doi `i`.
    return re.sub(r"\bSeri+le\b", "Seriile", raw, flags=re.IGNORECASE)


def parse_titlu(titlu: str) -> TitluOrar:
    """Decodeaza titlul unei pagini de orar.

    Nu arunca niciodata: un titlu nerecunoscut intoarce ``TipPagina.NECUNOSCUT``,
    ca o pagina ciudata sa nu opreasca tot ingestul (vezi §9 din plan).
    """
    raw = curata_titlu(titlu)
    if not raw:
        return TitluOrar(raw="", tip=TipPagina.NECUNOSCUT, eticheta="", slug="")

    if m := _RE_GRUPA.match(raw):
        return _construieste_grupa(raw, m.group("spec"), m.group("nr"))

    if m := _RE_MASTER.match(raw):
        return _construieste_master(raw, m)

    if m := _RE_SERII.match(raw):
        serii = tuple(s.strip() for s in m.group("serii").split(",") if s.strip())
        spec = normalizeaza_specializare(m.group("spec"))
        an = int(serii[0][0]) if serii and serii[0][:1].isdigit() else None
        return TitluOrar(
            raw=raw,
            tip=TipPagina.OPTIONAL_SERII,
            specializare=spec,
            an=an,
            serii_tinta=serii,
            eticheta=m.group("rest").strip(),
            slug=_slugify(raw),
        )

    if m := _RE_FACULTATIV.match(raw):
        return TitluOrar(
            raw=raw,
            tip=TipPagina.FACULTATIV,
            an=_an_din_roman_sau_cifra(m.group("an")),
            specializari_tinta=_split_specializari(m.group("spec") or ""),
            eticheta=raw,
            slug=_slugify(raw),
        )

    if m := _RE_LIMBI.match(raw):
        return TitluOrar(
            raw=raw,
            tip=TipPagina.LIMBI,
            an=_an_din_roman_sau_cifra(m.group("an")),
            specializari_tinta=_split_specializari(m.group("spec") or ""),
            eticheta=raw,
            slug=_slugify(raw),
        )

    if m := _RE_OPTIONAL.match(raw):
        rest = m.group("rest").strip()
        # "Master INFO" -> specializarea e in rest; altfel "MATE (1)" / "MATE-INFO (Informatica)"
        este_master = bool(re.search(r"\bMaster\b", rest, re.IGNORECASE))
        curat = re.sub(r"\bMaster\b", "", rest, flags=re.IGNORECASE)
        curat = re.sub(r"\([^)]*\)", "", curat).strip()
        return TitluOrar(
            raw=raw,
            tip=TipPagina.OPTIONAL,
            specializare=normalizeaza_specializare(curat),
            an=_an_din_roman_sau_cifra(m.group("an")),
            program="master" if este_master else None,
            eticheta=raw,
            slug=_slugify(raw),
        )

    if m := _RE_ROBOTICA.search(raw):
        return TitluOrar(
            raw=raw,
            tip=TipPagina.SPECIAL,
            an=int(m.group("an")),
            grupa=m.group("grupa"),
            eticheta=f"Fizică/Robotică {m.group('grupa')}",
            slug=_slugify(m.group("grupa")),
        )

    # Nerecunoscut de niciun sablon. Il marcam cinstit, dar NU il aruncam: pagina are
    # activitati reale care ocupa sali reale, iar /sala/{id} ar subestima ocuparea daca
    # le-am ignora. Loader-ul il ataseaza ca nod orfan (PARINTE = NULL) si logheaza.
    return TitluOrar(
        raw=raw,
        tip=TipPagina.NECUNOSCUT,
        eticheta=raw,
        slug=_slugify(raw),
        note=("titlu nerecunoscut de niciun sablon; atasat ca nod orfan",),
    )


def _construieste_grupa(raw: str, spec_text: str, nr: str) -> TitluOrar:
    spec = normalizeaza_specializare(spec_text)
    an = int(nr[0])
    serie = nr[:2]
    return TitluOrar(
        raw=raw,
        tip=TipPagina.GRUPA,
        specializare=spec,
        an=an,
        serie=serie,
        grupa=nr,
        eticheta=nr,
        slug=nr,
        note=() if spec else (f"specializare necunoscuta: {spec_text!r}",),
    )


def _construieste_master(raw: str, m: re.Match[str]) -> TitluOrar:
    spec = normalizeaza_specializare(m.group("spec"))
    nr = m.group("nr")
    # 4xx = anul I de master, 5xx = anul II.
    an = {"4": 1, "5": 2}.get(nr[0])
    cod = (m.group("cod") or "").strip() or None
    den = (m.group("den") or "").strip()
    return TitluOrar(
        raw=raw,
        tip=TipPagina.MASTER,
        specializare=spec,
        an=an,
        grupa=nr,
        program=cod,
        denumire_program=den or None,
        eticheta=f"{nr} ({cod})" if cod else nr,
        slug=nr,
        note=() if spec else (f"specializare necunoscuta: {m.group('spec')!r}",),
    )
