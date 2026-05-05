#!/usr/bin/env python3
"""
gemeni_call.py
==============
Extrage orarul dintr-o imagine folosind Gemini si adauga rezultatul intr-un JSON.

Imbunatatiri:
  - "memorie de sesiune": modelele care esueaza repetat (>=2 ori 503) sunt
    marcate dead si sarite pentru tot restul rularii
  - retry mai scurt pe 503 (max 2 incercari, delay 2s/4s)
  - functia process_image() reutilizabila

Utilizare CLI:
    python gemeni_call.py <imagine> <json_output> [--model M] [--debug]

Utilizare ca modul:
    from gemeni_call import process_image, GeminiSession
    session = GeminiSession()
    for img in folder.glob("*.png"):
        process_image(session, img, Path("date.json"))
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# ── .env ──────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv, find_dotenv
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file, override=False)
except ImportError:
    print("Avertisment: pip install python-dotenv", file=sys.stderr)

# ── google-genai ──────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError, ServerError
except ImportError:
    print(
        "Eroare: lipseste 'google-genai'.\n"
        "  pip install google-genai pillow python-dotenv",
        file=sys.stderr,
    )
    sys.exit(1)

from PIL import Image


# ────────────────────────────── modele de fallback ────────────────────────────
FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-1.5-flash",
]

# cate esecuri consecutive 5xx pana cand un model e considerat "dead"
DEAD_MODEL_THRESHOLD = 2

# parametri retry pentru 5xx (mai scurt decat inainte)
MAX_RETRIES_5XX = 2
RETRY_DELAYS_5XX = [2, 4]  # secunde

# ────────────────────────────── PROMPT ────────────────────────────────────────

PROMPT = """Esti un asistent care extrage orare universitare din imagini.

Imaginea atasata contine orarul saptamanal al unei grupe/serii/an de la
Facultatea de Matematica si Informatica, Universitatea din Bucuresti.

STRUCTURA TABELULUI:
  - 5 zile pe verticala: Luni, Marti, Miercuri, Joi, Vineri
  - 12 intervale orare pe orizontala: 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19
  - fiecare CELULA COLORATA reprezinta o activitate (curs / seminar / laborator)

ATENTIE: unele pagini pot fi pagini de titlu, cuprins, sau goale, fara orar.
In acel caz returneaza grupa="" si toate zilele cu lista goala [].

CONTINUTUL UNEI CELULE COLORATE (in ordine, de sus in jos):
  1. Numele profesorului (ex: "Dragan M", "Iftimie S / Tazlaoanu C" pentru doi).
     ATENTIE: uneori in colt apare doar un numar de grupa (ex: "161", "Gr 1",
     "Gr_2") si NU exista profesor mentionat. In acel caz lasa "profesor": "".
  2. Numele materiei urmat de tip in paranteza
     (ex: "GraficaAsistDeCalc (curs)", "MatematiciSpeciale (sem, SI)",
     "ArhSistCalcul (Lab)", "IA [sapt 1-7] (Lab)").
  3. Eventual o eticheta de semigrupa: "Gr 1", "Gr_1", "Gr 2", "Gr_3", etc.
  4. Sala (ex: "Amf.503", "L-106", "S.209", "Fac.Fizica -Magurele",
     "Magurele, lab.", "ONLINE").

REGULI DE EXTRAGERE:

  1. "tip" poate fi: "curs", "seminar", "sem", "Lab", "sem+Lab", "proiect".

  2. "frecventa" poate fi: "SI" (saptamana impara), "SP" (saptamana para)
     sau "" daca nu este specificata. Apare in paranteza langa tip.
     Exemplu: "MatematiciSpeciale (sem, SI)" -> tip="sem", frecventa="SI".

  3. "saptamani" se completeaza cand apare ceva de forma "[sapt 1-7]",
     "[sapt 8-14]", "[sapt 1]", "[sapt 2]", "[sapt 5-7]", "[sapt 8-10]" etc.
     Pune textul exact dintre parantezele drepte (ex: "sapt 1-7").
     Daca nu exista, lasa "".

  4. "semigrupa" se completeaza cand celula contine "Gr 1", "Gr_1", "Gr 2",
     "Gr_2", "Gr 3", "Gr_3", "Gr 4", "Gr_4", "Gr1", "Gr2", etc.
     Pune valoarea normalizata: "Gr_1", "Gr_2", "Gr_3", "Gr_4".
     Daca nu apare nicio eticheta de semigrupa, lasa "".

  5. "ore" reprezinta intervalul pe care se intinde celula colorata.
     Format: "10-12", "14-16" etc. (ora_start - ora_end).
     Daca celula ocupa o singura coloana orara, formatul este "10-11".
     IMPORTANT: o singura celula poate ocupa mai multe ore consecutive -
     identifica pe baza latimii zonei colorate cate ore acopera.

  6. "profesor": daca apar mai multi profesori separati cu "/", pune-i toti
     exact asa cum apar (ex: "Iftimie S / Tazlaoanu C"). Daca celula nu are
     profesor (doar grupa/numar), lasa "" la profesor.

  7. Daca in acelasi interval orar exista DOUA activitati suprapuse vizual
     (de obicei culori diferite, una deasupra alteia, sau diagonale impartite),
     creeaza DOUA intrari separate in lista zilei respective.

  8. Daca o celula este ALBA / GOALA (fara culoare de fundal), o ignori complet.

  9. La capatul de sus al imaginii apare titlul grupei/seriei
     (ex: "CTI Grupa 161", "MATE Grupa 104",
     "INFO Master 408 (SD - Sisteme distribuite)", "Optionale an III - MATE (2)").
     Acesta este "grupa". Daca nu e tabel de orar, "grupa" = "".

  10. Pentru zilele fara activitati, returneaza o lista goala [].

  11. NU inventa date. Daca un camp nu apare in imagine, lasa-l "".

FORMATUL EXACT AL JSON-ULUI DE OUTPUT:

{
  "grupa": "<titlul exact al grupei/seriei sau '' daca nu e orar>",
  "Luni":     [
    {
      "ore": "...",
      "profesor": "...",
      "materie": "...",
      "tip": "...",
      "frecventa": "",
      "saptamani": "",
      "semigrupa": "",
      "sala": "..."
    }
  ],
  "Marti":    [ ... ],
  "Miercuri": [ ... ],
  "Joi":      [ ... ],
  "Vineri":   [ ... ]
}

Returneaza STRICT obiectul JSON. NU folosi markdown ```json. NU adauga explicatii.
Raspunsul tau trebuie sa inceapa cu { si sa se termine cu }.
"""


# ────────────────────────────── helpers ───────────────────────────────────────


def get_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Nu s-a gasit GEMINI_API_KEY in mediul/`.env`. "
            "Cheie noua: https://aistudio.google.com/apikey"
        )
    return api_key.strip().strip('"').strip("'")


def parse_retry_delay(err_message: str):
    m = re.search(r"retry in ([\d.]+)s", err_message)
    return float(m.group(1)) if m else None


# ────────────────────────────── GeminiSession ─────────────────────────────────


class GeminiSession:
    """
    Tine starea peste mai multe procesari:
      - clientul Gemini (initialiazat o data)
      - lista de modele "dead" (au esuat repetat in sesiunea curenta)
      - contorul de esecuri consecutive per model
    """

    def __init__(self, api_key: str | None = None):
        self.client = genai.Client(api_key=api_key or get_api_key())
        self.dead_models: set[str] = set()
        self._fail_count: dict[str, int] = {}

    def is_alive(self, model_name: str) -> bool:
        return model_name not in self.dead_models

    def mark_failure(self, model_name: str) -> None:
        self._fail_count[model_name] = self._fail_count.get(model_name, 0) + 1
        if self._fail_count[model_name] >= DEAD_MODEL_THRESHOLD:
            self.dead_models.add(model_name)
            print(f"    ☠  '{model_name}' marcat dead pentru aceasta sesiune "
                  f"({self._fail_count[model_name]} esecuri consecutive)",
                  file=sys.stderr)

    def mark_success(self, model_name: str) -> None:
        # reseteaza contorul la succes
        self._fail_count[model_name] = 0


# ────────────────────────────── apel Gemini cu retry ──────────────────────────


def call_gemini_with_retry(
    session: GeminiSession,
    image_path: Path,
    models: list[str],
    verbose: bool = True,
):
    """Returneaza (raspuns_text, model_folosit). Sare peste modelele dead."""
    if not image_path.exists():
        raise FileNotFoundError(f"Imaginea nu exista: {image_path}")

    img = Image.open(image_path)
    config = types.GenerateContentConfig(
        temperature=0.0,
        top_p=0.95,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )

    last_error = None

    for model_name in models:
        # sari peste modelele moarte in aceasta sesiune
        if not session.is_alive(model_name):
            if verbose:
                print(f"  ⊘ skip {model_name} (dead in sesiune)", file=sys.stderr)
            continue

        if verbose:
            print(f"  → model: {model_name}", file=sys.stderr)

        for attempt in range(1, MAX_RETRIES_5XX + 1):
            try:
                response = session.client.models.generate_content(
                    model=model_name,
                    contents=[PROMPT, img],
                    config=config,
                )
                session.mark_success(model_name)
                return response.text, model_name

            except ClientError as e:
                last_error = e
                msg = str(e)

                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    if "limit: 0" in msg:
                        if verbose:
                            print(f"    ✗ quota=0 → trec la urmatorul model",
                                  file=sys.stderr)
                        session.dead_models.add(model_name)  # quota 0 = dead permanent
                        break
                    delay = parse_retry_delay(msg) or RETRY_DELAYS_5XX[attempt - 1]
                    delay = min(delay, 60)
                    if verbose:
                        print(f"    ⏳ 429 ({attempt}/{MAX_RETRIES_5XX}), astept {delay:.1f}s",
                              file=sys.stderr)
                    time.sleep(delay)
                    continue

                if verbose:
                    print(f"    ✗ {e}", file=sys.stderr)
                break

            except ServerError as e:
                last_error = e
                if attempt < MAX_RETRIES_5XX:
                    delay = RETRY_DELAYS_5XX[attempt - 1]
                    if verbose:
                        print(f"    ⏳ 5xx ({attempt}/{MAX_RETRIES_5XX}), astept {delay}s",
                              file=sys.stderr)
                    time.sleep(delay)
                    continue
                else:
                    # ultima incercare a esuat → marcheaza esecul
                    if verbose:
                        print(f"    ✗ 5xx persistent pe {model_name}",
                              file=sys.stderr)
                    session.mark_failure(model_name)
                    break

    raise RuntimeError(f"Toate modelele au esuat. Ultima eroare: {last_error}")


# ────────────────────────────── parsare/normalizare ───────────────────────────


def extract_json(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("Nu s-a gasit JSON in raspuns.")
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i + 1])
    raise ValueError("JSON incomplet.")


def normalize_entry(entry: dict) -> dict:
    required_days = ("Luni", "Marti", "Miercuri", "Joi", "Vineri")
    if "grupa" not in entry:
        entry["grupa"] = ""
    for zi in required_days:
        if zi not in entry or not isinstance(entry.get(zi), list):
            entry[zi] = []
        for act in entry[zi]:
            for key in ("ore", "profesor", "materie", "tip",
                        "frecventa", "saptamani", "semigrupa", "sala"):
                act.setdefault(key, "")
    return entry


def append_to_json_file(json_path: Path, entry: dict) -> str:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []

    if json_path.exists() and json_path.stat().st_size > 0:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                existing = [existing]
            elif not isinstance(existing, list):
                raise ValueError(f"{json_path} nu e lista/obiect JSON.")
        except json.JSONDecodeError as e:
            print(f"Avertisment: {json_path} corupt ({e}). Suprascriu.", file=sys.stderr)
            existing = []

    # cheia de identificare: grupa + _source (ca paginile goale sa nu se ciocneasca)
    grupa = entry.get("grupa", "").strip()
    source = entry.get("_source", "").strip()
    replaced = False

    for i, item in enumerate(existing):
        if not isinstance(item, dict):
            continue
        same_grupa = grupa and item.get("grupa", "").strip() == grupa
        same_source = source and item.get("_source", "").strip() == source
        if same_grupa or same_source:
            existing[i] = entry
            replaced = True
            break

    if not replaced:
        existing.append(entry)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return "actualizata" if replaced else "adaugata"


# ────────────────────────────── API public ────────────────────────────────────


def process_image(
    session: GeminiSession,
    image_path: Path,
    json_path: Path,
    model: str | None = None,
    verbose: bool = True,
) -> dict:
    """Extrage orarul dintr-o imagine si il adauga in JSON. Returneaza intrarea."""
    if model:
        models = [model]
    else:
        models = [m for m in FALLBACK_MODELS if session.is_alive(m)]
        if not models:
            raise RuntimeError(
                "Toate modelele sunt marcate dead in aceasta sesiune. "
                "Restart sau astepta cateva minute."
            )

    raw, model_used = call_gemini_with_retry(session, image_path, models, verbose=verbose)

    entry = extract_json(raw)
    entry = normalize_entry(entry)
    entry["_model"] = model_used
    entry["_source"] = image_path.name

    action = append_to_json_file(json_path, entry)

    if verbose:
        grupa = entry.get("grupa", "") or "(fara orar)"
        total = sum(len(entry.get(z, [])) for z in
                    ("Luni", "Marti", "Miercuri", "Joi", "Vineri"))
        print(f"  ✓ {grupa!r} {action} ({total} activitati, model={model_used})",
              file=sys.stderr)

    return entry


# ────────────────────────────── CLI ───────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="Extrage orar cu Gemini.")
    p.add_argument("image", type=Path)
    p.add_argument("json_file", type=Path)
    p.add_argument("--model", default=None,
                   help=f"Forteaza un model (default: fallback prin {FALLBACK_MODELS})")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        session = GeminiSession()
    except RuntimeError as e:
        print(f"Eroare: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"→  Procesez {args.image.name} ...")

    try:
        entry = process_image(session, args.image, args.json_file, model=args.model)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Eroare: {e}", file=sys.stderr)
        sys.exit(2)

    print(f"\nGrupa : {entry.get('grupa', '') or '(fara orar)'}")
    for zi in ("Luni", "Marti", "Miercuri", "Joi", "Vineri"):
        print(f"  {zi:<9}: {len(entry.get(zi, []))} activitati")


if __name__ == "__main__":
    main()