# Formatul orarului FMI — specificație

Documentul descrie **exact** ce conține o pagină de orar FMI și cum se citește ea.
E specificația de la care pornesc `ingest/segment.py` și `ingest/ocr.py`.

Semantica de mai jos provine din promptul folosit cu Gemini în prototip (validat pe 98 de
pagini / 1143 de activități), iar geometria a fost măsurată direct pe imaginile capturate.

---

## 1. Sursa

- Orarul e generat cu **aSc Orare** (footer: `Orar generat:DD.MM.YYYY` stânga, `aSc Orare` dreapta).
- Publicat ca **PDF vectorial** (`Producer: Acrobat Distiller`, `Title: orar.roz`) pe Google Drive,
  linkat de pe <https://fmi.unibuc.ro/orar/> prin `bit.ly`.
- PDF-ul are strat de text, **dar Drive blochează descărcarea** → accesibil doar rasterizat.
  De aici necesitatea segmentării + OCR. Vezi `docs/` și §2 din plan.
- O pagină = o **formațiune de studiu** (grupă, serie, an, sau pagină de opționale).

## 2. Geometria paginii

Măsurată pe toate cele 98 de pagini capturate (fiecare exact 1610×1120 px).
Valorile de mai jos sunt **proporții**, nu pixeli hardcodați — parserul le derivă din
dreptunghiul exterior detectat, ca să fie independent de rezoluția de captură.

```
┌──────────────────────────────────────────────────────────┐
│                    INFO Grupa 144                        │  ← titlu = numele formațiunii
│  Universitatea din Bucuresti, Facultatea de Matematica…   │  ← subtitlu constant
│  ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐     │
│  │    │ 8  │ 9  │ 10 │ …  │ …  │ …  │ …  │ 18 │ 19 │     │  ← header: 12 coloane orare
│  │    │8:00│9:00│…   │    │    │    │    │    │    │     │     (8:00–8:50 … 19:00–19:50)
│  ├────┼────┴────┴────┴────┴────┴────┴────┴────┴────┤     │
│  │ Lu │                                            │     │  ← 5 rânduri de zi
│  │ Mon│         celule colorate = activități       │     │
│  ├────┼────────────────────────────────────────────┤     │
│  │ Ma │                                            │     │
│  │ …  │                                            │     │
│  └────┴────────────────────────────────────────────┘     │
│  Orar generat:26.04.2026                     aSc Orare   │  ← footer
└──────────────────────────────────────────────────────────┘
```

| Element | Valoare măsurată (la 1610×1120) | Regulă generală |
| :--- | :--- | :--- |
| Chenar exterior tabel | `x ∈ [28, 1582]`, `y ∈ [109, 1068]` | detectat ca cel mai mare dreptunghi negru |
| Separator header | `y = 177` | prima linie orizontală sub header |
| Limita coloană-zi / grilă | `x = 142` | prima linie verticală după eticheta de zi |
| Pas coloană orară | **exact 120 px** | `(X1 − Xgrid) / 12` |
| Înălțime rând de zi | `(1068 − 177)/5 = 178.2 px` | `(Y1 − Yheader) / 5` |

**Maparea orei:** coloana `h ∈ [8..19]` ocupă `x ∈ [Xgrid + (h−8)·pas, Xgrid + (h−7)·pas]`.

**Benzi (lanes):** un rând de zi se subîmparte pe verticală în 1..N benzi, când mai multe
activități coexistă în același interval (semigrupe diferite sau săptămâni alternante).
**Măsurat: până la 5 benzi** într-o singură zi (`tests/fixtures/pag_57.png`, vineri).
Benzile *nu* au înălțime fixă — se deduc din intervalele `y` distincte ale dreptunghiurilor găsite.

**Culoarea NU identifică materia.** Verificat pe 40 de pagini: 124 de culori distincte, iar
aceeași materie primește până la 21 de culori (`POO`). aSc colorează *per lecție*. Culoarea e
utilă exclusiv la **segmentare** — celulele alăturate au culori diferite, deci se separă curat.

## 3. Conținutul unei celule

Layout intern **fix**, deci extragerea se face pe **poziție**, nu prin parsare de text liber:

```
┌──────────────────────────────────────┐
│ Dumitru B                    Gr_1    │  ← profesor (stânga-sus) | semigrupă (dreapta-sus)
│    LbForm&Autom (Lab, SI)            │  ← materie (tip[, frecvență]) [sapt X-Y]
│                            L-507     │  ← sala (dreapta-jos)
└──────────────────────────────────────┘
```

În benzile dense layout-ul se comprimă la 2 linii, dar alinierea laterală rămâne:
`linia 1` = profesor (stânga) + `Gr_N` (dreapta); `linia 2` = `Materie (tip) [sapt]` (stânga) + sala (dreapta).

### Câmpuri

| Câmp | Descriere | Valori observate (n = 1143) |
| :--- | :--- | :--- |
| `ore` | Intervalul acoperit de celulă, `"start-end"`. Convenție **capăt exclusiv**: `"14-17"` = 3 coloane = 14:00→17:00. | — |
| `profesor` | Stânga-sus. Mai mulți profesori separați prin `" / "`. Poate lipsi (celula are doar număr de grupă). | 33 de celule cu profesori multipli |
| `materie` | Abreviere aSc (`LbForm&Autom`, `Geom&AlgLin`, `POO`). | — |
| `tip` | În paranteză după materie. | `Lab` 465, `curs` 400, `sem` 115, `seminar` 96, `curs+seminar` 25, `sem+Lab` 21, `proiect` 4, gol 17 |
| `frecventa` | `SI` = săptămână impară, `SP` = pară. Al doilea element din paranteză. | gol 847, `SI` 149, `SP` 147 |
| `saptamani` | Textul exact dintre paranteze drepte, ex. `sapt 1-7`. | 16 pagini; `sapt 1-7` ×51, `sapt 8-14` ×52, restul rare |
| `semigrupa` | `Gr 1` / `Gr_1` / `Gr1` → normalizat `Gr_1..Gr_4`. | gol 801, `Gr_1` 139, `Gr_2` 138, `Gr_3` 42, `Gr_4` 22 |
| `sala` | Dreapta-jos. | 38 de valori distincte — vezi §4 |

### Regex pentru partea structurată

```
^(?P<materie>.+?)\s*
 \((?P<tip>curs|seminar|sem|Lab|sem\+Lab|curs\+seminar|proiect)
   (?:,\s*(?P<frecventa>SI|SP))?\)\s*
 (?:\[(?P<sapt>[^\]]+)\])?$
```

### Reguli

1. Celulă **albă/necolorată** → nicio activitate, se ignoră.
2. Două activități suprapuse vizual în același interval → **două intrări separate**.
3. Pagini de titlu/cuprins/goale → `grupa = ""`, toate zilele `[]`.
4. Câmp absent din imagine → `""`. **Nu se inventează date.**

## 4. Sălile — necesită normalizare

Aceeași sală apare scrisă inconsecvent: `L-507` vs `L.506`, `S-214` vs `S.213`.
Separatorul (`-` sau `.`) nu poartă informație → se normalizează la o formă canonică.

**Săli reale:** `Amf.501/503/701/703`, `L-106/202/401/402/404/507/508/509/511`,
`L.410/411/413/506`, `L-414 Robotica`, `S-214/415/512`, `S.102/107/108/109/111/203/209/210/211/213`.

**Non-săli** (marcate `SALA.TIP = virtual`, excluse din calculul gradului de ocupare):
`ONLINE`, `Magurele`, `Fac.Fizica -Magurele`, `IMAR (sala 309/412/414)`, `lab.`, și string-ul gol.

## 5. Titlul paginii → ierarhie

Codificare regulată: în `NNN`, **cifra 1 = anul**, **cifrele 1–2 = seria**, tot numărul = grupa.

| Formă titlu | Exemplu | Interpretare |
| :--- | :--- | :--- |
| `<SPEC> Grupa NNN` | `INFO Grupa 144` | an 1, seria 14, grupa 144 |
| `<SPEC> Master NNN (COD - Denumire)` | `INFO Master 408 (SD - Sisteme distribuite)` | master, an 1 (4xx) / an 2 (5xx) |
| `<SPEC> Seriile A,B,C: …` | `INFO Seriile 33,34,35: Optionale an III` | se leagă la mai multe serii prin `ORA_GRUPA` |
| `Optionale an N - <SPEC> (k)` | `Optionale an III - MATE (1)` | pachet de opționale |
| `Facultative an N (…)` / `Limbi straine - an N (…)` | | transversale pe specializări |
| `(studenti Fizica/Robotica, an N, grupa N01ROB)` | | caz special |
| `Conferinte si Seminarii` | | fără grupă-țintă |

Serii per specializare: MATE `10/20/30` · MATE APL. `22/32` · MATE-INFO `21/31` ·
INFO `13,14,15 / 23,24,25 / 33,34,35` · CTI `16/26/36`.

## 6. Ce NU se găsește în orar

`MATERIE.CREDITE`, `TIP_MATERIE`, `FORMA_EVALUARE`, `TIP_DISCIPLINA`, `NR_ORE_C/S/L/P` **nu apar
nicăieri** în orar. Sursa lor e folderul *Planurile de învățământ*
(<https://drive.google.com/drive/folders/1cg-GOlmDhAYBiqHJAd_iEes8QKm2GE1U>), ingestat separat.

## 7. Paritatea săptămânilor

Pagina FMI publică ancora, în text:
> Săptămâna 06.04.2026 – 09.04.2026 este **săptămână impară** (sapt 7).

Din ea, `domain/weeks.py` calculează pentru orice dată numărul săptămânii și paritatea SI/SP,
folosite la filtrarea activităților cu `frecventa` sau `saptamani`.
