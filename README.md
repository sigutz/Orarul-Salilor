# Orarul Sălilor — FMI

Orarul Facultății de Matematică și Informatică (Universitatea din București), navigabil
**pe grupe** și **pe săli**, cu ierarhia reală Specializare → Serie → Grupă → Semigrupă.

- `/grupa/244` — orarul unei formațiuni, inclusiv **cursurile moștenite de la serie și an**
- `/sala/701` — gradul de ocupare al unei săli: când e ocupată, ce materie, ce profesor, ce grupă
- `/sala` — toate sălile, cu procentul de ocupare
- `/preferinte` — grupa, semigrupa și opționalele tale; după aceea `/` deschide direct orarul tău
- `/admin/review` — celulele pe care extragerea nu le-a putut confirma, cu decupajul alături

Datele se extrag din orarul public al facultății, **fără apeluri către servicii plătite**:
captură din Google Drive, segmentare geometrică, apoi OCR local (ONNX pe CPU).

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

### Ingest din sursă

Necesită `pip install -e ".[ingest]" && playwright install chromium`.

```bash
.venv/bin/python -m orar.cli sincronizeaza --doar-verifica  # ce s-a schimbat pe fmi.unibuc.ro
.venv/bin/python -m orar.cli sincronizeaza                  # + reia ingestul dacă e cazul
.venv/bin/python -m orar.cli surse                          # ce orare cunoaștem, dacă-s la zi
.venv/bin/python -m orar.cli crosscheck --completeaza        # compară cu orarul profesorilor
.venv/bin/python -m orar.cli planuri --descarca              # credite și formă de evaluare
```

`sincronizeaza` face tot lanțul: citește pagina FMI, salvează ancorele de săptămână, compară
data publicată cu cea de la ultimul ingest reușit și — **doar dacă s-a schimbat** — capturează,
segmentează, citește și încarcă. La final rulează și verificarea încrucișată cu orarul
profesorilor (`--fara-crosscheck` o sare). Verificarea paginii e o cerere HTTP; ingestul
complet durează ~20 de minute.

Pașii se pot rula și separat:

```bash
.venv/bin/python -m orar.cli captureaza https://bit.ly/… -o data/screenshots/sem2-grupe
.venv/bin/python -m orar.cli load data/screenshots/sem2-grupe   # segmentare + OCR + bază
```

`load` acceptă fie un JSON, fie un director de capturi; în al doilea caz rulează tot lanțul.
Vocabularul pentru corecția OCR vine din baza existentă, iar la prima instalare din
`--referinta` (implicit `tests/golden/date.json`).

### Verificare periodică

Orarul se schimbă de câteva ori pe semestru, deci o verificare pe zi ajunge. Două variante:

```bash
# systemd timer / cron — recomandat, un singur proces indiferent câți workeri are web-ul
15 4 * * *  cd /opt/orar && .venv/bin/python -m orar.cli sincronizeaza >> /var/log/orar.log 2>&1
```

```bash
# sau în procesul web, dacă rulezi un singur worker
ORAR_SCHEDULER=1 .venv/bin/uvicorn orar.web.app:app
```

Planificatorul in-process **nu pornește implicit**: cu mai mulți workeri `uvicorn`, fiecare
și-ar porni propriul job și ar captura în paralel în același director.

### Conturi

```bash
ORAR_SECRET=$(openssl rand -hex 32) .venv/bin/uvicorn orar.web.app:app   # obligatoriu în producție
ORAR_HTTPS=1 …                                                           # cookie `Secure`, în spatele TLS
```

Fără `ORAR_SECRET` se generează una la pornire: sesiunile se pierd la repornire și nu sunt
valabile între procese. Parolele se stochează cu `hashlib.scrypt` (N=2¹⁵, ~70 ms), cu
parametrii scriși în hash ca să poată fi crescuți fără să invalideze conturile existente.
Nu există limitare a încercărilor de autentificare — dacă expui aplicația public, adaug-o în
față (nginx, fail2ban).

Alte comenzi:

```bash
.venv/bin/python -m orar.cli stats                          # câte rânduri sunt în bază
.venv/bin/python -m orar.cli reset                          # șterge baza
.venv/bin/python -m orar.cli -v load …                      # + avertismente și calitatea datelor
.venv/bin/python -m orar.cli segmenteaza data/screenshots/sem2-grupe/pag_016.png
.venv/bin/python -m orar.cli citeste   data/screenshots/sem2-grupe/pag_016.png
.venv/bin/python -m orar.cli evalueaza                       # acuratețe pe câmpuri
.venv/bin/python -m pytest -m "not slow"                    # 240 de teste, ~70 s
.venv/bin/python -m pytest                                  # + citirea completă, ~7 min
```

Baza e un fișier SQLite în `data/orar.db`; se poate muta cu `ORAR_DB=/alt/loc.db`.

## Cum e organizat

```
src/orar/
├── domain/      logică pură, fără I/O
│   ├── hierarchy.py   „INFO Grupa 144" → an 1, seria 14, grupa 144
│   ├── names.py       „Cheval H" ↔ „Cheval Andrei-Horatiu"
│   ├── abbrev.py      „StructDate" ↔ „Structuri de date"
│   ├── rooms.py       normalizarea sălilor + clasificare fizică/externă/virtuală
│   ├── weeks.py       calendarul academic: numărul și paritatea săptămânii
│   └── grid.py        așează activitățile în grila de 5 zile × 12 ore
├── db/          modele SQLAlchemy, interogările ierarhice, migrări Alembic
├── ingest/      watcher.py (ce publică FMI), capture.py (Drive → PNG),
│               segment.py (PNG → celule), ocr.py (celule → text),
│               lexicon.py (vocabulare închise), evaluate.py (acuratețe),
│               crosscheck.py (a doua sursă), plans.py (planuri de învățământ),
│               load.py (→ bază), consolidate.py (vezi mai jos)
├── worker/      sync.py (lanțul complet), scheduler.py (verificarea zilnică)
└── web/         FastAPI + Jinja2 + HTMX, CSS scris de mână
```

### Opt lucruri care nu sunt evidente

**1. Fiecare pagină din orarul FMI e autonomă.** Pagina grupei 244 conține și cursurile
ținute cu toată seria 24 — deci același curs apare identic pe paginile 241, 242, 243, 244.
Încărcat naiv, un curs de serie devine 4 rânduri `ORA`, sala pare rezervată de 4 ori
simultan, iar ierarhia rămâne goală. `ingest/consolidate.py` detectează activitățile
identice și le urcă la cel mai apropiat strămoș comun: **1146 → 784 de rânduri**, din care
59 devin ore de serie/an. Abia după asta `/sala/{id}` arată ocuparea reală.

**2. Segmentarea nu se poate lua după culoare.** aSc umple unele celule cu două tonuri
tăiate în diagonală — aceeași activitate, două culori — iar chenarele dintre celule au 1 px
și se amestecă cu umplerile la randare (între două verzuri, chenarul iese `(87,142,87)`, nu
negru). `ingest/segment.py` taie deci numai unde găsește un minim local de luminanță
*continuu* pe toată lățimea: continuitatea deosebește un chenar de un rând de text.

**3. Detectorul de text al OCR-ului încurcă, nu ajută.** Pe celulele astea rapidocr „din
cutie" rupe `Prunescu M` în `runescu` și taie `ESLA (curs) [sapt 3-4]` în patru bucăți: e
antrenat pe fotografii, nu pe dreptunghiuri de text vectorial pe fundal pastel. Dar decupajul
îl putem face noi, geometric — textul e negru curat, rândurile sunt despărțite de goluri albe.
Măsurat pe toate paginile, 34276 de goluri: raportate la înălțimea rândului, spațiile dintre
cuvinte stau sub 0.8 și separatorii de câmp peste 1.2, iar **între ele nu cade nimic**.
`ingest/ocr.py` taie la 1.0 și folosește din rapidocr doar recunoașterea — ieșirea devine
întreagă, iar pasul e de ~25× mai rapid.

**4. Setul de referință greșește, și se vede unde.** `tests/golden/date.json` (ieșirea
prototipului cu Gemini) taie benzile suprapuse: unde pagina are trei celule de `18-20` una
sub alta, el citește șase celule alăturate de câte o oră. Din 147 de dezacorduri pe `ore`, în
**134** intervalul nostru îl conține strict pe cel din referință — semnătura exactă a acestei
erori. Verificat pe pixeli, plus două grafii greșite care stricau vocabularul, șase celule
pierdute și un `frecventa` inventat: [`docs/formatul-orarului.md` §9](docs/formatul-orarului.md).

**5. Vocabularul nu are voie să se hrănească din propria ieșire.** Corecția OCR folosește
termenii din bază, iar baza e umplută tot de ingest. Fără grijă, o citire greșită intră ca
termen valid și de la a doua rulare devine „cuvânt cunoscut": aceeași celulă se potrivește
perfect cu propria ei greșeală și nu mai ajunge în coada de verificare. De aceea
`Lexicon.din_baza` numără doar termenii care apar în cel puțin un rând unde câmpul **nu** e
marcat nesigur. Verificat că e punct fix: 194 de profesori la intrare, 194 confirmați la
ieșire, niciunul în plus, niciunul pierdut — deci reluările nu derivează.

**6. `ORA_GRUPA.ID_GRUPA` nu e pachetul, e ținta.** În jonctiune, `ID_GRUPA` e formațiunea
*căreia i se oferă* opționalul (Seria 33), iar pachetul însuși e `ORA.ID_GRUPA`. Filtrul de
înscrieri scris pe coloana greșită trece oricum, fiindcă ținta e deja în lanțul studentului —
arăta că merge și nu filtra nimic. `db/queries.py` filtrează acum pe proprietarul orei;
regresia e prinsă de un test care numără activitățile înainte și după înscriere.

**7. Același orar e publicat de două ori, și a doua oară e util.** PDF-ul profesorilor (191
de pagini) are aceeași grilă, dar pivotată: profesorul e în titlu, formațiunile în mijlocul
celulei. Din el ies două lucruri pe care o singură sursă nu le poate da — numele **întregi**
(citite dintr-un titlu mare, nu dintr-o bandă de 20 px) și o confirmare independentă pe
fiecare activitate. Rezultat: **668 de activități găsite în ambele surse, 0 divergențe de
profesor**, și 181 de prescurtări din bază înlocuite cu numele complet. Prescurtarea aSc nu e
cea evidentă: `Cheval H` ← `Cheval Andrei-Horatiu` (inițiala **ultimului** prenume),
`BanuDem. I` ← `Banu Demergian Iulia`. Vezi `domain/names.py`.

**8. Numerotarea săptămânilor sare peste vacanțe.** FMI publică:
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

Drive plafonează randarea unei pagini la **3200×2262 px**, atins exact cu
`device_scale_factor=4`; peste atât imaginea e doar mărită. La plafon tabelul are 2882 px, iar
în cea mai densă bandă textul are 19–24 px — citibil. Sub `LATIME_MINIMA_TABEL` captura
eșuează explicit, în loc să producă imagini din care OCR-ul ar ghici.

`tests/golden/date.json` rămâne setul de referință pentru regresie (vezi §9 din documentație
pentru unde greșește el).

### Acuratețea extragerii

`orar evalueaza`, pe toate cele 98 de pagini (1140 de activități împerecheate):

| câmp | acuratețe | cerința din plan |
| :--- | ---: | ---: |
| `sala` | 100.00% | ≥ 99% |
| `frecventa` | 99.91% | ≥ 99% |
| `saptamani` | 99.82% | — |
| `semigrupa` | 99.82% | ≥ 99% |
| `tip` | 99.74% | ≥ 99% |
| `materie` | 99.56% | ≥ 97% |
| `profesor` | 99.56% | ≥ 95% |
| `ore` | (vezi mai jos) | — |

`ore` iese din aritmetică pe caroiaj, deci nu poate fi aproximativ; cele 147 de dezacorduri
sunt erori ale referinței, nu ale extragerii — 134 dintre ele au exact semnătura descrisă la
punctul 4 de mai sus.

Ce rămâne neconfirmat ajunge în `/admin/review`, nu tăcut în bază: **5 activități din 784**,
toate verificate manual. Patru sunt celule în care aSc a scris textul suprapus, literă peste
literă (`pag_028` și `pag_048`); a cincea e o notă în text liber. Nicio extragere nu le poate
citi, iar afișarea decupajului lângă valorile propuse e singurul mod onest de a le rezolva.

### Stadiu

| | |
| :--- | :--- |
| ✅ Schemă, ierarhie, consolidare, import | funcțional |
| ✅ `/grupa/{id}`, `/sala/{id}`, căutare | funcțional |
| ✅ Captură la rezoluție nativă + segmentare geometrică | funcțional |
| ✅ OCR local + lexicon + coadă de verificare | funcțional |
| ✅ Watcher + sincronizare automată | funcțional |
| ✅ Conturi, preferințe, filtrare pe semigrupă și opționale | funcțional |
| ✅ Verificare încrucișată cu orarul profesorilor | funcțional |
| 🟡 Planuri de învățământ (credite, formă de evaluare) | 4 fișiere din 9 |

Creditele și forma de evaluare vin din „Planurile de învățământ", ingestate separat cu
`orar planuri`: **39 de materii completate** din 161. Restul aparțin programelor MATE,
MATE-INFO, MATE APL, ASM și PSFS, ale căror PDF-uri au cifrele desenate ca contururi
vectoriale, nu ca text — vezi [`docs/planuri-de-invatamant.md`](docs/planuri-de-invatamant.md).
`SALA.NR_LOCURI` există în sursă, pe pagina 2 a orarului, și urmează să fie ingestat.
