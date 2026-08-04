"""Interogarile care dau continut rutelor /grupa/{id} si /sala/{id}.

Nucleul e regula de mostenire ierarhica: orarul unei grupe = orele proprii + cele ale
**stramosilor** ei (seria, anul de specializare) + cele ale **descendentilor**
(semigrupele) + optionalele legate prin ORA_GRUPA.

    INFO an 2          <- curs comun pe tot anul   => se vede la 244
    +-- Seria 24       <- curs de serie            => se vede la 244
        +-- 244        <- seminar propriu
            +-- 244/1  <- laborator de semigrupa   => se vede la 244, marcat "Gr_1"
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, or_, select, text
from sqlalchemy.orm import Session, joinedload

from orar.db.models import Grupa, Ora, OraGrupa, Sala

__all__ = [
    "ids_stramosi",
    "ids_descendenti",
    "ids_relevante",
    "ore_pentru_grupa",
    "ore_pentru_sala",
    "OraAfisata",
    "gaseste_grupa",
    "gaseste_sala",
]


# CTE recursiv in sus: nodul + toti stramosii lui.
_SQL_STRAMOSI = text(
    """
    WITH RECURSIVE sus(id) AS (
        SELECT :gid
        UNION
        SELECT g."PARINTE" FROM "GRUPA" g JOIN sus ON g."ID_GRUPA" = sus.id
        WHERE g."PARINTE" IS NOT NULL
    )
    SELECT id FROM sus
    """
)

# CTE recursiv in jos: nodul + toti descendentii lui.
_SQL_DESCENDENTI = text(
    """
    WITH RECURSIVE jos(id) AS (
        SELECT :gid
        UNION
        SELECT g."ID_GRUPA" FROM "GRUPA" g JOIN jos ON g."PARINTE" = jos.id
    )
    SELECT id FROM jos
    """
)


def ids_stramosi(s: Session, grupa_id: int) -> set[int]:
    """Nodul + lantul de parinti pana la radacina."""
    return {r[0] for r in s.execute(_SQL_STRAMOSI, {"gid": grupa_id})}


def ids_descendenti(s: Session, grupa_id: int) -> set[int]:
    """Nodul + tot subarborele de sub el."""
    return {r[0] for r in s.execute(_SQL_DESCENDENTI, {"gid": grupa_id})}


def ids_relevante(s: Session, grupa_id: int) -> set[int]:
    """Toate nodurile ale caror ore trebuie sa apara in orarul acestei grupe."""
    return ids_stramosi(s, grupa_id) | ids_descendenti(s, grupa_id)


def _cu_relatii(stmt: Select) -> Select:
    return stmt.options(
        joinedload(Ora.materie),
        joinedload(Ora.profesor),
        joinedload(Ora.sala),
        joinedload(Ora.grupa),
    )


def ore_pentru_grupa(
    s: Session,
    grupa_id: int,
    *,
    perioada_id: int | None = None,
    include_optionale: bool = True,
    optionale_permise: set[int] | None = None,
) -> list[Ora]:
    """Orarul complet al unei grupe, cu mostenire pe verticala.

    `optionale_permise` restrange pachetele de optionale la cele la care userul e inscris
    (USER_OPTIONAL). Daca e None, se includ toate cele legate de grupa.

    Atentie la ce inseamna fiecare coloana: in `ORA_GRUPA`, `ID_GRUPA` e **tinta** legaturii
    (seria careia i se ofera pachetul), iar pachetul propriu-zis e `ORA.ID_GRUPA`. Deci
    inscrierile se filtreaza pe *proprietarul orei*, nu pe tinta; altfel conditia e implinita
    oricum de lantul studentului si nu filtreaza nimic.
    """
    ids = ids_relevante(s, grupa_id)

    conditii = [Ora.grupa_id.in_(ids)]
    if include_optionale:
        legate = select(OraGrupa.ora_id).where(OraGrupa.grupa_id.in_(ids))
        partajate = Ora.id.in_(legate)
        if optionale_permise is not None:
            pachete = select(Grupa.id).where(Grupa.tip == "optional")
            partajate = and_(
                partajate,
                or_(Ora.grupa_id.not_in(pachete), Ora.grupa_id.in_(optionale_permise)),
            )
        conditii.append(partajate)

    stmt = _cu_relatii(select(Ora).where(or_(*conditii)))
    if perioada_id is not None:
        stmt = stmt.where(Ora.perioada_id == perioada_id)

    return list(s.execute(stmt).unique().scalars())


def ore_pentru_sala(s: Session, sala_id: int, *, perioada_id: int | None = None) -> list[Ora]:
    """Tot ce ocupa o sala, indiferent de grupa."""
    stmt = _cu_relatii(select(Ora).where(Ora.sala_id == sala_id))
    if perioada_id is not None:
        stmt = stmt.where(Ora.perioada_id == perioada_id)
    return list(s.execute(stmt).unique().scalars())


def gaseste_grupa(s: Session, identificator: str) -> Grupa | None:
    """Rezolva /grupa/{identificator} dupa id numeric, slug sau nume.

    Asa merg si /grupa/244 (slug) si /grupa/17 (id intern), fara ca utilizatorul sa
    trebuiasca sa stie care e care.
    """
    ident = identificator.strip()
    if ident.isdigit():
        # Slug-ul are prioritate: "244" e numarul grupei, mult mai probabil decat un id intern.
        if g := s.scalar(select(Grupa).where(Grupa.slug == ident)):
            return g
        if g := s.get(Grupa, int(ident)):
            return g
    return s.scalar(select(Grupa).where(or_(Grupa.slug == ident, Grupa.nume == ident)).limit(1))


def gaseste_sala(s: Session, identificator: str) -> Sala | None:
    """Rezolva /sala/{identificator} dupa id, slug, nume canonic sau forma nenormalizata."""
    from orar.domain.rooms import normalizeaza_sala

    ident = identificator.strip()
    if g := s.scalar(select(Sala).where(or_(Sala.slug == ident, Sala.nume == ident))):
        return g

    # "/sala/701" -> "Amf.701"; "/sala/L-507" -> "L.507"
    norm = normalizeaza_sala(ident)
    if g := s.scalar(select(Sala).where(or_(Sala.slug == norm.slug, Sala.nume == norm.nume))):
        return g

    if ident.isdigit():
        if g := s.scalar(select(Sala).where(Sala.nume.like(f"%.{ident}"))):
            return g
        return s.get(Sala, int(ident))
    return None


@dataclass
class OraAfisata:
    """O ora pregatita pentru randare, cu contextul de care are nevoie sablonul."""

    ora: Ora
    #: True daca ora vine de la un stramos (serie/an), nu de la grupa ceruta.
    mostenita: bool
    #: Numele nodului de la care vine, ex. "Seria 24".
    provenienta: str
