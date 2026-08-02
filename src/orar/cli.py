"""Linia de comanda: `orar <subcomanda>`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from orar.db.session import cale_db, sesiune


def _cmd_load(args: argparse.Namespace) -> int:
    from orar.ingest.consolidate import consolideaza
    from orar.ingest.load import incarca_din_json

    with sesiune() as s:
        rap = incarca_din_json(
            s, args.fisier, an_universitar=args.an, semestru=args.semestru
        )
        print(rap)
        if not args.fara_consolidare:
            print("\n--- consolidare (activitati de serie) ---")
            cons = consolideaza(s, an_universitar=args.an)
            print(cons)
            if cons.exemple and args.verbose:
                print("  exemple:")
                for e in cons.exemple:
                    print(f"    {e}")
            if cons.suspecte and args.verbose:
                print("\n  durate contradictorii in sursa (erori de extragere):")
                for e in cons.suspecte:
                    print(f"    {e}")
    if rap.avertismente and args.verbose:
        print("\n--- avertismente ---")
        for a in rap.avertismente:
            print(f"  {a}")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    cale = cale_db()
    if cale.exists():
        if not args.da:
            raspuns = input(f"Sterg {cale}? [y/N] ")
            if raspuns.strip().lower() not in ("y", "yes", "d", "da"):
                print("Anulat.")
                return 1
        cale.unlink()
        for sufix in ("-wal", "-shm"):
            (cale.parent / (cale.name + sufix)).unlink(missing_ok=True)
        print(f"Sters {cale}")
    else:
        print(f"{cale} nu exista.")
    return 0


def _cmd_stats(_args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from orar.db.models import Grupa, Materie, Ora, Profesor, Sala

    with sesiune() as s:
        for model, eticheta in (
            (Ora, "ore"),
            (Grupa, "noduri GRUPA"),
            (Profesor, "profesori"),
            (Materie, "materii"),
            (Sala, "sali"),
        ):
            n = s.scalar(select(func.count()).select_from(model))
            print(f"{eticheta:14} {n}")
        print("\npe tip de nod:")
        for tip, n in s.execute(
            select(Grupa.tip, func.count()).group_by(Grupa.tip).order_by(func.count().desc())
        ):
            print(f"  {tip:14} {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orar", description="Orarul Salilor (FMI)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("load", help="incarca un JSON de orar in baza de date")
    pl.add_argument("fisier", type=Path)
    pl.add_argument("--an", default="2025-2026")
    pl.add_argument("--semestru", type=int, default=2, choices=(1, 2))
    pl.add_argument(
        "--fara-consolidare",
        action="store_true",
        help="nu ridica activitatile comune la nodul de serie (util la depanare)",
    )
    pl.set_defaults(func=_cmd_load)

    pr = sub.add_parser("reset", help="sterge baza de date")
    pr.add_argument("--da", action="store_true", help="fara confirmare")
    pr.set_defaults(func=_cmd_reset)

    ps = sub.add_parser("stats", help="cate randuri sunt in baza")
    ps.set_defaults(func=_cmd_stats)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
