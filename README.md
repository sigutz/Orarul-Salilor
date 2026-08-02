# Orarul Sălilor — FMI

Orarul Facultății de Matematică și Informatică (Universitatea din București), navigabil
**pe grupe** și **pe săli**, cu ierarhia reală Specializare → Serie → Grupă → Semigrupă.

- `/grupa/244` — orarul unei formațiuni, inclusiv **cursurile moștenite de la serie și an**
- `/sala/701` — gradul de ocupare al unei săli: când e ocupată, ce materie, ce profesor, ce grupă
- `/sala` — toate sălile, cu procentul de ocupare

Datele se extrag din orarul public al facultății, **fără apeluri către servicii plătite**.

## Instalare

Necesită Python ≥ 3.12 (testat pe 3.14).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Pornire

```bash
.venv/bin/alembic upgrade head                            # creează schema
.venv/bin/python -m orar.cli load tests/golden/date.json  # populează baza
.venv/bin/uvicorn orar.web.app:app --reload               # http://127.0.0.1:8000
```

Alte comenzi:

```bash
.venv/bin/python -m orar.cli stats        # câte rânduri sunt în bază
.venv/bin/python -m orar.cli reset        # șterge baza
.venv/bin/python -m orar.cli -v load …    # + avertismente și probleme de calitate a datelor
.venv/bin/python -m pytest                # 88 de teste
```

Baza e un fișier SQLite în `data/orar.db`; se poate muta cu `ORAR_DB=/alt/loc.db`.

## Cum e organizat

```
src/orar/
├── domain/      logică pură, fără I/O
│   ├── hierarchy.py   „INFO Grupa 144" → an 1, seria 14, grupa 144
│   ├── rooms.py       normalizarea sălilor + clasificare fizică/externă/virtuală
│   ├── weeks.py       calendarul academic: numărul și paritatea săptămânii
│   └── grid.py        așează activitățile în grila de 5 zile × 12 ore
├── db/          modele SQLAlchemy, interogările ierarhice, migrări Alembic
├── ingest/      load.py (JSON → bază) + consolidate.py (vezi mai jos)
└── web/         FastAPI + Jinja2 + HTMX, CSS scris de mână
```

### Două lucruri care nu sunt evidente

**1. Fiecare pagină din orarul FMI e autonomă.** Pagina grupei 244 conține și cursurile
ținute cu toată seria 24 — deci același curs apare identic pe paginile 241, 242, 243, 244.
Încărcat naiv, un curs de serie devine 4 rânduri `ORA`, sala pare rezervată de 4 ori
simultan, iar ierarhia rămâne goală. `ingest/consolidate.py` detectează activitățile
identice și le urcă la cel mai apropiat strămoș comun: **1143 → 837 de rânduri**, din care
56 devin ore de serie/an. Abia după asta `/sala/{id}` arată ocuparea reală.

**2. Numerotarea săptămânilor sare peste vacanțe.** FMI publică:
*„Săptămâna 06.04.2026 – 09.04.2026 este săptămână impară (sapt 7)"* și
*„Săptămâna 20.04.2026 – 24.04.2026 este săptămână pară (sapt 8)"* — două săptămâni
calendaristice distanță, dar una academică (între ele e vacanța de Paște). De aceea
`domain/weeks.py` ține **toate** ancorele publicate și marchează rezultatul ca aproximativ
când nu cade exact pe una, în loc să împartă naiv la 7.

## Sursa datelor

Orarul e generat cu **aSc Orare** și publicat ca PDF vectorial pe Google Drive, linkat de pe
<https://fmi.unibuc.ro/orar/>. PDF-ul **are strat de text, dar Drive blochează descărcarea**,
iar preview-ul servește doar pagini rasterizate — deci extragerea cere segmentare + OCR.
Semantica paginii și geometria măsurată sunt documentate în
[`docs/formatul-orarului.md`](docs/formatul-orarului.md).

Baza actuală se încarcă din `tests/golden/date.json` (98 de pagini, 1143 de activități),
care servește și ca set de referință pentru parserul determinist.

### Stadiu

| | |
| :--- | :--- |
| ✅ Schemă, ierarhie, consolidare, import | funcțional |
| ✅ `/grupa/{id}`, `/sala/{id}`, căutare | funcțional |
| ⬜ Captură + segmentare + OCR (înlocuiește sursa JSON) | de făcut |
| ⬜ Watcher + sincronizare automată | de făcut |
| ⬜ Autentificare și preferințe de utilizator | de făcut |
| ⬜ Planuri de învățământ (credite, formă de evaluare) | de făcut |

Coloanele `MATERIE.CREDITE`, `TIP_MATERIE`, `FORMA_EVALUARE`, `TIP_DISCIPLINA`,
`NR_ORE_C/S/L/P` **nu există în orar** — vin din „Planurile de învățământ" și rămân `NULL`
până atunci. Nicio rută curentă nu depinde de ele.

## Calitatea datelor

`orar.cli -v load` raportează problemele găsite în sursă. În setul curent: **27 de activități
cu durate contradictorii** — aceeași oră apare cu lungimi diferite pe pagini diferite
(ex. `Algebra II` e 8–10 pe trei pagini și 8–11 pe a patra). Sunt erori de extragere ale
sursei, nu ale importului. Consolidarea le **raportează fără să ghicească**: votul majoritar
ar da un răspuns greșit în cel puțin un caz verificat vizual. Segmentarea geometrică va
elimina toată clasa asta de erori, pentru că lățimea unei celule e pură aritmetică pe caroiaj.
