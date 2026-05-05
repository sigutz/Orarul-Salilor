#!/usr/bin/env python3
"""
batch_process.py
================
Proceseaza in masa toate imaginile dintr-un folder si le adauga intr-un singur
fisier JSON (data/outputs/date.json by default).

Caracteristici:
  - sesiune partajata: modelele care esueaza repetat sunt sarite pentru tot batch-ul
  - rate limiting automat (8 RPM default, sub limita Gemini 2.5 Flash de 10)
  - skip imagini deja procesate (pe baza nume fisier in _source)
  - log de rezumat la final cu erori per imagine

Utilizare:
    python batch_process.py <folder_imagini> [--output date.json]

Exemple:
    python batch_process.py data/processed_ss/
    python batch_process.py data/processed_ss/ --rpm 12 --start-model gemini-2.5-flash-lite
    python batch_process.py data/processed_ss/ --force
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gemeni_call import process_image, GeminiSession, FALLBACK_MODELS


def already_processed(json_path: Path) -> set[str]:
    if not json_path.exists() or json_path.stat().st_size == 0:
        return set()
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        return {item.get("_source", "") for item in data if isinstance(item, dict)}
    except (json.JSONDecodeError, OSError):
        return set()


def parse_args():
    p = argparse.ArgumentParser(
        description="Proceseaza in masa imagini cu orare → un singur JSON.",
    )
    p.add_argument("folder", type=Path)
    p.add_argument("--output", "-o", type=Path,
                   default=Path("data/outputs/date.json"))
    p.add_argument("--rpm", type=int, default=8,
                   help="cereri/minut (default: 8)")
    p.add_argument("--pattern", default="*.png")
    p.add_argument("--force", action="store_true",
                   help="reproceseaza imaginile deja in JSON")
    p.add_argument("--model", default=None,
                   help="forteaza un model anume (skip fallback)")
    p.add_argument("--start-model", default=None,
                   help="muta acest model pe prima pozitie in fallback "
                        "(util cand stii ca primul e supraincarcat)")
    return p.parse_args()


def main():
    args = parse_args()

    if not args.folder.is_dir():
        print(f"Eroare: {args.folder} nu este un folder.", file=sys.stderr)
        sys.exit(1)

    images = sorted(args.folder.glob(args.pattern))
    if not images:
        print(f"Nu s-au gasit imagini ({args.pattern}) in {args.folder}.", file=sys.stderr)
        sys.exit(1)

    done = already_processed(args.output)
    if not args.force and done:
        before = len(images)
        images = [img for img in images if img.name not in done]
        skipped = before - len(images)
        if skipped:
            print(f"⏭   {skipped} imagini deja in {args.output} (skip)")

    if not images:
        print("✓  Toate imaginile sunt deja procesate. Foloseste --force pentru reluare.")
        return

    print(f"→  De procesat : {len(images)} imagini")
    print(f"→  Output      : {args.output}")
    print(f"→  Rate limit  : {args.rpm} cereri/minut "
          f"({60 / args.rpm:.1f}s intre cereri)")

    # init sesiune (un singur client + un singur tracker de modele dead)
    try:
        session = GeminiSession()
    except RuntimeError as e:
        print(f"Eroare: {e}", file=sys.stderr)
        sys.exit(1)

    # daca utilizatorul vrea sa porneasca direct cu un model anume,
    # il marcam pe primul ca dead pana il atingem
    if args.start_model and args.start_model in FALLBACK_MODELS:
        print(f"→  Pornesc cu  : {args.start_model}\n")
        for m in FALLBACK_MODELS:
            if m == args.start_model:
                break
            session.dead_models.add(m)
    else:
        print()

    delay_between = 60.0 / args.rpm
    successes = []
    failures = []
    start_time = time.time()

    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}")
        t0 = time.time()

        try:
            entry = process_image(
                session, img_path, args.output,
                model=args.model, verbose=True,
            )
            grupa = entry.get("grupa", "") or "(fara orar)"
            successes.append((img_path.name, grupa))
        except Exception as e:
            print(f"  ✗ EROARE: {e}", file=sys.stderr)
            failures.append((img_path.name, str(e)))

        elapsed = time.time() - t0
        if i < len(images) and elapsed < delay_between:
            sleep_for = delay_between - elapsed
            print(f"  ⏸  pauza {sleep_for:.1f}s pentru rate limit\n")
            time.sleep(sleep_for)
        else:
            print()

    total_time = time.time() - start_time

    print("=" * 60)
    print(f"REZUMAT  ({total_time:.1f}s = {total_time/60:.1f} min)")
    print("=" * 60)
    print(f"  ✓ Reusite : {len(successes)}")
    for fname, grupa in successes:
        print(f"      {fname:<25} → {grupa}")

    if failures:
        print(f"\n  ✗ Esuate  : {len(failures)}")
        for fname, err in failures:
            short_err = err.replace("\n", " ")[:100]
            print(f"      {fname:<25} → {short_err}")

    if session.dead_models:
        print(f"\n  ☠  Modele moarte in sesiune: {sorted(session.dead_models)}")

    print(f"\nOutput salvat in: {args.output}")


if __name__ == "__main__":
    main()