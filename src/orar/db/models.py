"""Schema bazei de date.

Implementeaza schema ceruta (PROFESOR, SALA, GRUPA, PERIOADA, MATERIE, ORA, USER) plus
patru adaugiri agreate:

  GRUPA.TIP          nivelul nodului in arbore -- PARINTE da structura, nu si nivelul
  ORA_GRUPA          jonctiune many-to-many, pentru orele partajate de mai multe grupe
                     (optionale, facultative, limbi straine)
  USER_OPTIONAL      la ce optionale e inscris efectiv un student
  ORA.confidence /   provenienta si increderea OCR-ului, pentru coada de review (Etapa 5)
  ORA.sursa_pagina

Numele de tabele si de coloane respecta specificatia (majuscule), dar atributele Python
sunt in snake_case ca sa ramana idiomatice.
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Nomenclatoare
# ---------------------------------------------------------------------------


class Profesor(Base):
    __tablename__ = "PROFESOR"

    id: Mapped[int] = mapped_column("ID_PROFESOR", Integer, primary_key=True)
    nume: Mapped[str] = mapped_column("NUME", String(120), nullable=False, unique=True)
    titlu: Mapped[str | None] = mapped_column("TITLU", String(40))
    #: Slug pentru URL-uri (/profesor/{slug}).
    slug: Mapped[str] = mapped_column("SLUG", String(140), nullable=False, unique=True)

    ore: Mapped[list[Ora]] = relationship(back_populates="profesor")

    def __repr__(self) -> str:
        return f"<Profesor {self.nume!r}>"


class Sala(Base):
    __tablename__ = "SALA"

    id: Mapped[int] = mapped_column("ID_SALA", Integer, primary_key=True)
    nume: Mapped[str] = mapped_column("NUME", String(80), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column("SLUG", String(90), nullable=False, unique=True)
    #: fizica | externa | virtuala -- vezi domain.rooms.TipSala
    tip: Mapped[str] = mapped_column("TIP", String(16), nullable=False, default="fizica")

    ore: Mapped[list[Ora]] = relationship(back_populates="sala")

    __table_args__ = (
        CheckConstraint("TIP IN ('fizica','externa','virtuala')", name="ck_sala_tip"),
    )

    def __repr__(self) -> str:
        return f"<Sala {self.nume!r}>"


class Grupa(Base):
    """Nod in arborele Specializare -> Serie -> Grupa -> Semigrupa.

    `parinte` e cheia self-referentiala care tine ierarhia. Paginile de optionale sunt
    tot noduri aici (tip='optional'), dar se leaga de grupele-tinta prin ORA_GRUPA.
    """

    __tablename__ = "GRUPA"

    id: Mapped[int] = mapped_column("ID_GRUPA", Integer, primary_key=True)
    parinte_id: Mapped[int | None] = mapped_column(
        "PARINTE", ForeignKey("GRUPA.ID_GRUPA", ondelete="SET NULL"), index=True
    )
    nume: Mapped[str] = mapped_column("NUME", String(160), nullable=False)
    an_universitar: Mapped[str] = mapped_column("AN_UNIVERSITAR", String(12), nullable=False)

    # --- adaugire fata de specificatie ---
    #: specializare | serie | grupa | semigrupa | optional -- vezi domain.hierarchy.Nivel
    tip: Mapped[str] = mapped_column("TIP", String(16), nullable=False, default="grupa")
    slug: Mapped[str] = mapped_column("SLUG", String(180), nullable=False)
    #: Codul specializarii (INFO, MATE, CTI...), pentru filtrare rapida.
    specializare: Mapped[str | None] = mapped_column("SPECIALIZARE", String(16), index=True)
    an_studiu: Mapped[int | None] = mapped_column("AN_STUDIU", Integer)

    parinte: Mapped[Grupa | None] = relationship(
        back_populates="copii", remote_side="Grupa.id"
    )
    copii: Mapped[list[Grupa]] = relationship(
        back_populates="parinte", cascade="save-update, merge"
    )
    ore: Mapped[list[Ora]] = relationship(back_populates="grupa")

    __table_args__ = (
        UniqueConstraint("SLUG", "AN_UNIVERSITAR", name="uq_grupa_slug_an"),
        CheckConstraint(
            "TIP IN ('specializare','serie','grupa','semigrupa','optional')",
            name="ck_grupa_tip",
        ),
        Index("ix_grupa_tip_an", "TIP", "AN_UNIVERSITAR"),
    )

    def __repr__(self) -> str:
        return f"<Grupa {self.nume!r} ({self.tip})>"


class Perioada(Base):
    __tablename__ = "PERIOADA"

    id: Mapped[int] = mapped_column("ID_PERIOADA", Integer, primary_key=True)
    semestru: Mapped[int] = mapped_column("SEMESTRU", Integer, nullable=False)
    an_univ: Mapped[str] = mapped_column("AN_UNIV", String(12), nullable=False)

    ore: Mapped[list[Ora]] = relationship(back_populates="perioada")

    __table_args__ = (
        UniqueConstraint("SEMESTRU", "AN_UNIV", name="uq_perioada"),
        CheckConstraint("SEMESTRU IN (1,2)", name="ck_perioada_semestru"),
    )

    def __repr__(self) -> str:
        return f"<Perioada sem{self.semestru} {self.an_univ}>"


class Materie(Base):
    """Disciplina.

    Coloanele de plan de invatamant (credite, tip, forma de evaluare, numar de ore) NU se
    pot extrage din orar -- vin din "Planurile de invatamant" (Etapa 8). Raman NULL pana
    atunci; nicio ruta din MVP nu depinde de ele.
    """

    __tablename__ = "MATERIE"

    id: Mapped[int] = mapped_column("ID_MATERIE", Integer, primary_key=True)
    nume: Mapped[str] = mapped_column("NUME", String(160), nullable=False)
    slug: Mapped[str] = mapped_column("SLUG", String(180), nullable=False, unique=True)

    credite: Mapped[int | None] = mapped_column("CREDITE", Integer)
    tip_materie: Mapped[str | None] = mapped_column("TIP_MATERIE", String(40))
    forma_evaluare: Mapped[str | None] = mapped_column("FORMA_EVALUARE", String(40))
    tip_disciplina: Mapped[str | None] = mapped_column("TIP_DISCIPLINA", String(40))
    an: Mapped[int | None] = mapped_column("AN", Integer)
    semestru: Mapped[int | None] = mapped_column("SEMESTRU", Integer)
    nr_ore_c: Mapped[int | None] = mapped_column("NR_ORE_C", Integer)
    nr_ore_s: Mapped[int | None] = mapped_column("NR_ORE_S", Integer)
    nr_ore_l: Mapped[int | None] = mapped_column("NR_ORE_L", Integer)
    nr_ore_p: Mapped[int | None] = mapped_column("NR_ORE_P", Integer)

    ore: Mapped[list[Ora]] = relationship(back_populates="materie")

    def __repr__(self) -> str:
        return f"<Materie {self.nume!r}>"


# ---------------------------------------------------------------------------
# Tabela centrala
# ---------------------------------------------------------------------------

ZILE = ("Luni", "Marti", "Miercuri", "Joi", "Vineri", "Sambata", "Duminica")


class Ora(Base):
    """O activitate din orar: cine, ce, unde, cand, cu ce grupa."""

    __tablename__ = "ORA"

    id: Mapped[int] = mapped_column("ID_ORA", Integer, primary_key=True)

    profesor_id: Mapped[int | None] = mapped_column(
        "ID_PROFESOR", ForeignKey("PROFESOR.ID_PROFESOR"), index=True
    )
    materie_id: Mapped[int | None] = mapped_column(
        "ID_MATERIE", ForeignKey("MATERIE.ID_MATERIE"), index=True
    )
    sala_id: Mapped[int | None] = mapped_column("ID_SALA", ForeignKey("SALA.ID_SALA"), index=True)
    #: Grupa-proprietar (pagina din care provine ora). Partajarea trece prin ORA_GRUPA.
    grupa_id: Mapped[int] = mapped_column(
        "ID_GRUPA", ForeignKey("GRUPA.ID_GRUPA"), nullable=False, index=True
    )
    perioada_id: Mapped[int] = mapped_column(
        "ID_PERIOADA", ForeignKey("PERIOADA.ID_PERIOADA"), nullable=False, index=True
    )

    tip_ora_materie: Mapped[str | None] = mapped_column("TIP_ORA_MATERIE", String(24))
    ora_inceput: Mapped[time] = mapped_column("ORA_INCEPUT", Time, nullable=False)
    ora_sfarsit: Mapped[time] = mapped_column("ORA_SFARSIT", Time, nullable=False)
    zi_saptamana: Mapped[str] = mapped_column("ZI_SAPTAMANA", String(12), nullable=False)

    # --- specifice orarului FMI ---
    #: "SI" (saptamana impara) | "SP" (para) | NULL (in fiecare saptamana)
    frecventa: Mapped[str | None] = mapped_column("FRECVENTA", String(4))
    #: Textul brut al intervalului de saptamani, ex. "sapt 1-7".
    saptamani: Mapped[str | None] = mapped_column("SAPTAMANI", String(80))
    #: "Gr_1".."Gr_4" cand activitatea e doar pentru o semigrupa.
    semigrupa: Mapped[str | None] = mapped_column("SEMIGRUPA", String(8))

    # --- provenienta (adaugire) ---
    sursa_pagina: Mapped[str | None] = mapped_column("SURSA_PAGINA", String(60))
    confidence: Mapped[float | None] = mapped_column("CONFIDENCE")

    profesor: Mapped[Profesor | None] = relationship(back_populates="ore")
    materie: Mapped[Materie | None] = relationship(back_populates="ore")
    sala: Mapped[Sala | None] = relationship(back_populates="ore")
    grupa: Mapped[Grupa] = relationship(back_populates="ore")
    perioada: Mapped[Perioada] = relationship(back_populates="ore")
    grupe_partajate: Mapped[list[Grupa]] = relationship(
        secondary="ORA_GRUPA", viewonly=False, backref="ore_partajate"
    )

    __table_args__ = (
        CheckConstraint(
            "ZI_SAPTAMANA IN ('Luni','Marti','Miercuri','Joi','Vineri','Sambata','Duminica')",
            name="ck_ora_zi",
        ),
        CheckConstraint("ORA_INCEPUT < ORA_SFARSIT", name="ck_ora_interval"),
        CheckConstraint("FRECVENTA IS NULL OR FRECVENTA IN ('SI','SP')", name="ck_ora_frecventa"),
        # Cele doua interogari fierbinti: orarul unei grupe si ocuparea unei sali.
        Index("ix_ora_grupa_zi", "ID_GRUPA", "ZI_SAPTAMANA", "ORA_INCEPUT"),
        Index("ix_ora_sala_zi", "ID_SALA", "ZI_SAPTAMANA", "ORA_INCEPUT"),
    )

    def __repr__(self) -> str:
        return f"<Ora {self.zi_saptamana} {self.ora_inceput:%H:%M}-{self.ora_sfarsit:%H:%M}>"


class OraGrupa(Base):
    """Jonctiune: o ora poate fi partajata de mai multe grupe.

    Necesara pentru optionale/facultative/limbi straine, unde o singura activitate apare
    in orarul mai multor grupe sau serii.
    """

    __tablename__ = "ORA_GRUPA"

    ora_id: Mapped[int] = mapped_column(
        "ID_ORA", ForeignKey("ORA.ID_ORA", ondelete="CASCADE"), primary_key=True
    )
    grupa_id: Mapped[int] = mapped_column(
        "ID_GRUPA", ForeignKey("GRUPA.ID_GRUPA", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------------------
# Utilizatori
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "USER"

    id: Mapped[int] = mapped_column("ID", Integer, primary_key=True)
    nume: Mapped[str] = mapped_column("NUME", String(120), nullable=False)
    email: Mapped[str | None] = mapped_column("EMAIL", String(180), unique=True)
    parola_hash: Mapped[str | None] = mapped_column("PAROLA_HASH", String(255))
    #: Grupa preferata -- interfata afiseaza implicit orarul ei.
    grupa_id: Mapped[int | None] = mapped_column(
        "ID_GRUPA", ForeignKey("GRUPA.ID_GRUPA", ondelete="SET NULL"), index=True
    )
    #: Semigrupa preferata ("Gr_1"), ca sa filtram laboratoarele celeilalte semigrupe.
    semigrupa: Mapped[str | None] = mapped_column("SEMIGRUPA", String(8))

    grupa: Mapped[Grupa | None] = relationship()
    optionale: Mapped[list[Grupa]] = relationship(secondary="USER_OPTIONAL")

    def __repr__(self) -> str:
        return f"<User {self.nume!r}>"


class UserOptional(Base):
    """La ce pachete de optionale e inscris efectiv un student."""

    __tablename__ = "USER_OPTIONAL"

    user_id: Mapped[int] = mapped_column(
        "ID_USER", ForeignKey("USER.ID", ondelete="CASCADE"), primary_key=True
    )
    grupa_id: Mapped[int] = mapped_column(
        "ID_GRUPA", ForeignKey("GRUPA.ID_GRUPA", ondelete="CASCADE"), primary_key=True
    )
