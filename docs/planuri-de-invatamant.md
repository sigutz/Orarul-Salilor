# Planurile de învățământ

A doua sursă de date, complet separată de orar. Orarul spune *când și unde* se ține o
activitate; planul spune *ce este* disciplina: câte credite, ce formă de evaluare, câte ore
de curs/seminar/laborator/proiect. Coloanele `MATERIE.CREDITE`, `FORMA_EVALUARE`,
`TIP_DISCIPLINA`, `AN`, `SEMESTRU` și `NR_ORE_C/S/L/P` **nu apar nicăieri în orar**.

Sursa: <https://drive.google.com/drive/folders/1cg-GOlmDhAYBiqHJAd_iEes8QKm2GE1U>, un folder
public cu 9 PDF-uri, câte unul pe program de studii.

## Formatul

Spre deosebire de orar, fișierele **se descarcă** direct (`uc?export=download`) — nu sunt
blocate. Tabelul e regulat, iar un rând acoperă **amândouă semestrele**:

```
 1.  Structuri algebrice în informatică   DF   2  2  -  -   E  4    -  -  -  -   -  -
     ^denumire                           ^tip  ^C ^S ^L ^P ^ev ^cr  \___ semestrul II ___/
```

Disciplina aparține semestrului în care are valori; celălalt e numai liniuțe. Contextul —
anul, programul, felul disciplinelor — vine din titlurile de secțiune și ține până la
următorul titlu:

- `Programul de studii universitare de master BAZE DE DATE ȘI TEHNOLOGII SOFTWARE`
- `ANUL II 2025-2026 - PLAN DE ÎNVĂȚĂMÂNT`
- `Discipline obligatorii` / `opționale` / `facultative`

La masterat, denumirile sunt **bilingve** (`Vedere artificială / Computer Vision`) și au un
cod în față (`Ob.11`, `Op.14`) care nu face parte din nume.

## Cinci fișiere din nouă nu se pot citi

`asm`, `mate`, `mate-apl`, `mate-info`, `psfs` folosesc un font cu codificare proprie, fără
tabelă ToUnicode. Literele sunt recuperabile — sunt deplasate cu +29 — dar **cifrele nu sunt
text deloc**: sunt desenate ca contururi vectoriale. Verificat cu `pdftohtml -xml`, care dă
fiecare fragment de text cu poziția lui; pe rândul lui *Algebră liniară* există exact trei
fragmente:

```
<text top="397" left="135">$OJHEU OLQLDU</text>   ← „Algebră liniară"
<text top="397" left="292">')</text>              ← „DF"
<text top="397" left="459">(</text>               ← „E"
```

Orele și creditele lipsesc, deși se văd în pagina randată. Adică exact datele pentru care
venisem. Ar fi nevoie de un segmentator de tabel + OCR pe celule — altă etapă de lucru, nu o
ajustare. Până atunci, `orar planuri` le raportează pe nume, ca fișiere fără strat de text.

## Legarea de orar

Orarul scrie `StructDate`, planul scrie `Structuri de date`. Potrivirea **nu** e fuzzy pe
șiruri — pe abrevieri de două litere ar da rezultate aiurea — ci structurală, pentru că aSc
construiește abrevierea după o regulă (`domain/abbrev.py`):

| Denumire | Abreviere | Ce se întâmplă |
| :--- | :--- | :--- |
| Structuri de date | `StructDate` | prefixe de cuvânt, fără „de" |
| Baze de date | `BD` | doar inițialele |
| Programare orientată pe obiecte | `POO` | idem |
| Geometrie și algebră liniară | `Geom&AlgLin` | „și" devine `&` |
| Limbaje formale și automate | `LbForm&Autom` | `Lb` nu e prefix, e schelet de consoane |

Regula unificată: **tăiem abrevierea la majuscule** și cerem ca fiecare bucată să fie o
*subsecvență* a cuvântului corespunzător, începând cu aceeași literă. Prefixul și scheletul
de consoane sunt amândouă subsecvențe, deci o singură condiție le acoperă. Scorul e cât din
denumire a fost folosită; pragul e 0.75.

## Ce a ieșit

Pe datele din 2025-2026: **206 discipline** citite din cele 4 fișiere bune, **39 de materii
din orar completate**. Restul de 120 nu au corespondent — aproape toate sunt discipline de la
MATE, MATE-INFO, MATE APL, ASM și PSFS, adică exact programele ale căror planuri nu se pot
citi.

Două abrevieri rămân **ambigue în sursă** și se raportează fără să se aleagă:

- `BD` → *Baze de date* sau *Big Data*
- `IA` → *Inteligență artificială* sau *Învățare automată*

Ambele perechi există în planuri și abrevierea chiar nu le distinge.
