#!/usr/bin/env python3
"""
remove_model_entries.py
=======================
Elimina toate intrarile procesate de un anumit model dintr-un fisier JSON.

Utilizare:
    python remove_model_entries.py <fisier.json> --model gemini-2.5-flash-lite
    python remove_model_entries.py data/outputs/date.json --model gemini-2.5-flash-lite
    python remove_model_entries.py data/outputs/date.json --model gemini-2.5-flash-lite --no-backup

Scriptul:
  - face backup automat la fisier.json.backup (daca nu exista deja)
  - elimina toate intrarile unde "_model" == modelul specificat
  - salveaza JSON-ul curatat
  - afiseaza statistici
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        description="Elimina intrari procesate de un anumit model din JSON."
    )
    p.add_argument("json_file", type=Path, help="fisierul JSON de procesat")
    p.add_argument("--model", required=True,
                   help="numele modelului de eliminat (ex: gemini-2.5-flash-lite)")
    p.add_argument("--no-backup", action="store_true",
                   help="nu face backup inainte de modificare")
    return p.parse_args()


def main():
    args = parse_args()

    if not args.json_file.exists():
        print(f"Eroare: fisierul {args.json_file} nu exista.", file=sys.stderr)
        sys.exit(1)

    # citeste JSON-ul
    try:
        with open(args.json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Eroare la parsarea JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # asigura-te ca e lista
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        print(f"Eroare: fisierul nu contine o lista sau obiect JSON valid.",
              file=sys.stderr)
        sys.exit(1)

    initial_count = len(data)
    target_model = args.model

    # filtreaza
    filtered = []
    removed = []

    for entry in data:
        if not isinstance(entry, dict):
            filtered.append(entry)  # pastreaza chestii ciudate
            continue

        model = entry.get("_model", "")
        if model == target_model:
            grupa = entry.get("grupa", "(fara grupa)")
            source = entry.get("_source", "(fara source)")
            removed.append((source, grupa))
        else:
            filtered.append(entry)

    removed_count = len(removed)
    remaining_count = len(filtered)

    if removed_count == 0:
        print(f"✓  Nicio intrare cu model='{target_model}' gasita.")
        print(f"   Total intrari in fisier: {initial_count}")
        return

    # backup (daca nu exista deja)
    if not args.no_backup:
        backup_path = args.json_file.with_suffix(args.json_file.suffix + ".backup")
        if not backup_path.exists():
            shutil.copy2(args.json_file, backup_path)
            print(f"✓  Backup creat: {backup_path}")
        else:
            print(f"ℹ  Backup deja exista: {backup_path} (nu suprascriu)")

    # salveaza JSON-ul curatat
    with open(args.json_file, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"REZULTAT")
    print(f"{'='*60}")
    print(f"  Model eliminat    : {target_model}")
    print(f"  Intrari sterse    : {removed_count}")
    print(f"  Intrari ramase    : {remaining_count}")
    print(f"  Fisier actualizat : {args.json_file}")

    if removed:
        print(f"\nIntrari eliminate:")
        for source, grupa in removed:
            print(f"  - {source:<30} → {grupa}")

    print(f"\nPentru a reprocessa aceste {removed_count} imagini, "
          f"ruleaza din nou batch_process.py:")
    print(f"  python src/batch_process.py data/processed_ss/ --rpm 8")


if __name__ == "__main__":
    main()