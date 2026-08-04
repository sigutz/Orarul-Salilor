"""Captura paginilor de orar din vizualizatorul Google Drive.

De ce prin browser si nu descarcand PDF-ul
------------------------------------------
Orarul e un PDF vectorial cu strat de text, dar fisierul e publicat pe Drive cu
descarcarea **blocata**: `uc?export=download` raspunde "the owner hasn't given you
permission to download this file". Preview-ul serveste doar pagini rasterizate, iar
endpoint-ul de imagine (`drive-viewer/<token>=sNNNN-`) e plafonat la 1024x724 -- prea
putin. Singura cale catre o rezolutie utila e sa randam pagina si sa o fotografiem.

Rezolutia e constrangerea care conteaza
---------------------------------------
La latimea la care captura prototipul (pagina de 1610 px, tabel de 1441), textul din benzile
dese are **9-11 px inaltime** (vezi `tests/fixtures/pag_57.png`, vineri: opt benzi suprapuse)
-- prea putin pentru orice OCR.

Plafonul lui Drive, masurat: randarea unei pagini se opreste la **3200x2262** px indiferent
cat crestem `device_scale_factor`. La `dsf=2` imaginea are 1600 px, la `dsf=4` are 3200, iar
la `dsf=6` tot 3200 (captura iese 4800 px, dar e doar marita, fara detaliu nou). Deci
`scala=4` atinge exact plafonul si nu are rost sa cerem mai mult.

La plafon: tabel de **2882 px**, iar in cea mai densa banda textul are **19-24 px** -- citibil.
`LATIME_MINIMA_TABEL` e pragul sub care captura **esueaza explicit**, in loc sa produca
imagini din care OCR-ul ar ghici.

Ce fotografiem
--------------
Vizualizatorul Drive e cu derulare continua: fiecare pagina e un `div` propriu care contine
un `img`. Fotografiem **div-ul paginii**, nu `div[role="main"]` -- acela prinde si bara de
unelte, si coloana de miniaturi, si pagina urmatoare, iar segmentarea nu mai gaseste tabelul.

Segmentarea (`segment.py`) nu depinde de rezolutie -- deduce caroiajul din pagina -- deci
o captura mai mare nu strica nimic, doar ajuta OCR-ul.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = [
    "OptiuniCaptura",
    "PaginaCapturata",
    "RezultatCaptura",
    "EroareCaptura",
    "captureaza_orar",
    "LATIME_MINIMA_TABEL",
]

#: Sub atata latime de tabel (px), OCR-ul din Etapa 5 nu are sanse pe benzile dese.
#: Plafonul lui Drive da 2882; sub 2400 textul dens scade sub ~16 px si devine ghicit.
LATIME_MINIMA_TABEL = 2400

#: Un `div` per pagina in vizualizatorul cu derulare continua.
SEL_PAGINA = "div.ndfHFb-c4YZDc-cYSp0e-DARUcf"
#: Cat de lata trebuie sa fie randarea ca sa o consideram pe cea definitiva, nu placeholder.
LATIME_MINIMA_RANDARE = 3000

_RE_ID_DRIVE = re.compile(r"(?:/file/d/|[?&]id=)([A-Za-z0-9_-]{20,})")


class EroareCaptura(RuntimeError):
    pass


@dataclass
class OptiuniCaptura:
    """Reglajele capturii. Valorile implicite tintesc ~4000 px latime de tabel."""

    director: Path = Path("data/screenshots")
    #: Marimea logica a ferestrei; Drive isi aseaza vizualizatorul dupa ea.
    latime_viewport: int = 1400
    inaltime_viewport: int = 1000
    #: Multiplicatorul de pixeli reali. 4 atinge exact plafonul de randare al Drive (3200 px
    #: pe latimea paginii); peste, imaginea e doar marita.
    scala: int = 4
    #: Cat asteptam dupa fiecare navigare, pentru randarea Drive.
    pauza_incarcare: float = 8.0
    #: Cat asteptam cel mult ca Drive sa inlocuiasca placeholder-ul neclar cu randarea buna.
    pauza_pagina: float = 12.0
    latime_minima_tabel: int = LATIME_MINIMA_TABEL
    #: Daca True, sarim paginile al caror continut nu s-a schimbat fata de rularea trecuta.
    incremental: bool = True
    headless: bool = True
    #: Opreste-te dupa atatea pagini (pentru probe rapide). None = toate.
    limita: int | None = None


@dataclass
class PaginaCapturata:
    numar: int
    cale: Path
    latime: int
    inaltime: int
    #: sha256 al fisierului, pentru captura incrementala.
    amprenta: str
    neschimbata: bool = False


@dataclass
class RezultatCaptura:
    pagini: list[PaginaCapturata] = field(default_factory=list)
    avertismente: list[str] = field(default_factory=list)

    @property
    def cate_noi(self) -> int:
        return sum(1 for p in self.pagini if not p.neschimbata)


def id_din_link(url: str) -> str:
    """Extrage id-ul fisierului Drive dintr-un link (inclusiv dintr-un bit.ly rezolvat)."""
    m = _RE_ID_DRIVE.search(url)
    if not m:
        raise EroareCaptura(f"nu am gasit un id de fisier Drive in {url!r}")
    return m.group(1)


def _amprenta(cale: Path) -> str:
    return hashlib.sha256(cale.read_bytes()).hexdigest()


def captureaza_orar(url: str, optiuni: OptiuniCaptura | None = None) -> RezultatCaptura:
    """Deschide orarul in Drive si salveaza fiecare pagina ca PNG.

    `url` poate fi bit.ly-ul de pe pagina FMI sau linkul Drive direct.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise EroareCaptura(
            "playwright nu e instalat. Ruleaza:\n"
            "  pip install -e '.[ingest]' && playwright install chromium"
        ) from e

    opt = optiuni or OptiuniCaptura()
    opt.director.mkdir(parents=True, exist_ok=True)
    rezultat = RezultatCaptura()

    with sync_playwright() as p:
        # Chromium-ul livrat de Playwright: fara `executable_path` catre un Chrome de
        # sistem, care pe multe masini nici nu exista.
        browser = p.chromium.launch(headless=opt.headless)
        context = browser.new_context(
            viewport={"width": opt.latime_viewport, "height": opt.inaltime_viewport},
            device_scale_factor=opt.scala,
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_url("**drive.google.com/**", timeout=30_000)
            except PWTimeout as e:
                raise EroareCaptura(
                    f"linkul nu a ajuns la Google Drive (a ramas la {page.url!r})"
                ) from e

            time.sleep(opt.pauza_incarcare)
            pagini = _pagini(page)
            # Locator-ul nu suporta len(); numarul de elemente se cere cu .count().
            total = pagini.count() if pagini is not None else 0
            if not total:
                raise EroareCaptura(
                    "nu am gasit paginile in vizualizator -- probabil s-a schimbat "
                    "structura Drive; verifica manual linkul"
                )

            nr_pagini = min(total, opt.limita) if opt.limita is not None else total
            log.info("am gasit %d pagini, capturez %d", total, nr_pagini)

            for i in range(nr_pagini):
                pagina = _captureaza_pagina(page, pagini, i, opt, rezultat)
                if pagina is not None:
                    rezultat.pagini.append(pagina)
        finally:
            context.close()
            browser.close()

    return rezultat


def _pagini(page):  # noqa: ANN001
    """Locatorul catre div-urile de pagina, cautand si in iframe-uri."""
    lista = page.locator(SEL_PAGINA)
    if lista.count():
        return lista
    for frame in page.frames:
        try:
            in_frame = frame.locator(SEL_PAGINA)
            if in_frame.count():
                return in_frame
        except Exception:  # pragma: no cover - frame detasat
            continue
    return None


def _asteapta_randare(element, limita: float) -> int:  # noqa: ANN001
    """Asteapta ca Drive sa puna randarea la rezolutie mare si intoarce latimea ei.

    Cand o pagina intra in cadru, Drive arata intai o versiune neclara si abia apoi
    o inlocuieste. Fotografiata prea devreme, iese exact imaginea de care OCR-ul nu are
    nevoie -- si nimic din pipeline nu ar mai semnala-o, pentru ca segmentarea reuseste
    si pe imagini neclare. Deci asteptam **randarea**, nu un numar de secunde.
    """
    scadent = time.monotonic() + limita
    latime = 0
    while time.monotonic() < scadent:
        latime = int(
            element.evaluate(
                "e => { const i = e.querySelector('img');"
                " return i && i.complete ? i.naturalWidth : 0; }"
            )
            or 0
        )
        if latime >= LATIME_MINIMA_RANDARE:
            return latime
        time.sleep(0.4)
    return latime


def _captureaza_pagina(page, pagini, index: int, opt: OptiuniCaptura, rezultat):  # noqa: ANN001
    """Aduce pagina `index` in cadru, o fotografiaza si verifica rezolutia."""
    import numpy as np
    from PIL import Image

    from orar.ingest.segment import EroareSegmentare, detecteaza_caroiaj

    cale = opt.director / f"pag_{index + 1:03d}.png"
    amprenta_veche = _amprenta(cale) if cale.exists() else None

    element = pagini.nth(index)
    try:
        element.scroll_into_view_if_needed(timeout=20_000)
    except Exception as e:
        rezultat.avertismente.append(f"pagina {index + 1}: nu am putut derula pana la ea ({e})")
        return None

    randare = _asteapta_randare(element, opt.pauza_pagina)
    if randare < LATIME_MINIMA_RANDARE:
        rezultat.avertismente.append(
            f"pagina {index + 1}: Drive a randat-o la doar {randare} px "
            f"in {opt.pauza_pagina:.0f}s; imaginea poate fi neclara"
        )

    try:
        element.screenshot(path=str(cale), timeout=30_000)
    except Exception as e:
        rezultat.avertismente.append(f"pagina {index + 1}: fotografierea a esuat ({e})")
        return None

    with Image.open(cale) as im:
        latime, inaltime = im.size
        img = np.asarray(im.convert("RGB"))

    # Verificam rezolutia pe *tabel*, nu pe imagine: marginile nu ajuta OCR-ul.
    try:
        caroiaj = detecteaza_caroiaj(img)
        latime_tabel = caroiaj.coloane[-1] - caroiaj.coloane[0]
    except EroareSegmentare:
        # Pagina de titlu sau cuprins -- o pastram, dar nu o judecam dupa caroiaj.
        latime_tabel = None

    if latime_tabel is not None and latime_tabel < opt.latime_minima_tabel:
        raise EroareCaptura(
            f"pagina {index + 1}: tabelul are doar {latime_tabel} px latime, sub pragul de "
            f"{opt.latime_minima_tabel}. La atata, textul din benzile dese ajunge sub ~16 px "
            f"si OCR-ul devine ghicit. Creste `scala` sau `latime_viewport`."
        )

    amprenta = _amprenta(cale)
    return PaginaCapturata(
        numar=index + 1,
        cale=cale,
        latime=latime,
        inaltime=inaltime,
        amprenta=amprenta,
        neschimbata=bool(opt.incremental and amprenta_veche == amprenta),
    )
