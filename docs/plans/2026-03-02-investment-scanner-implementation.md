# Investment Scanner — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Python-Script das Grundstücke (Kleinanzeigen, DGA, Zwangsversteigerungen) und Crowdfunding-Beteiligungen (Bettervest, Bergfürst, Wiwin, Exporo) scrapet und als HTML-Report ausgibt.

**Architecture:** Jede Quelle hat eine eigene `scrape_*()` Funktion die eine Liste von Dicts zurückgibt. `main()` ruft alle Scraper auf, filtert nach Region/Preis/Rendite, und erzeugt HTML + CSV. Fehler einer Quelle crashen das Script nicht — sie erzeugen eine Warnung im Report.

**Tech Stack:** Python 3.10+, requests, beautifulsoup4, datetime, pathlib, csv — alles standardmäßig verfügbar oder via pip.

---

### Task 1: Projekt-Skeleton, Konfiguration, Hilfsfunktionen

**Files:**
- Create: `investment_scanner.py`
- Create: `run_scanner.sh`

**Kontext:**
Alle Konfigurationswerte stehen als Konstanten am Dateianfang. Hilfsfunktionen `make_session()` (requests.Session mit Browser-Headers) und `safe_get(session, url)` (mit Timeout + Exception-Handling) werden von allen Scrapern genutzt.

**Step 1: `investment_scanner.py` anlegen mit folgendem Inhalt:**

```python
#!/usr/bin/env python3
"""
Investment Opportunity Scanner
───────────────────────────────
Scrapet Grundstücke und Crowdfunding-Beteiligungen für Ostdeutschland.

Quellen Grundstücke:  Kleinanzeigen.de, DGA, Zwangsversteigerungstermine.de
Quellen Crowdfunding: Bettervest, Bergfürst, Wiwin, Exporo
"""

import csv
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

MAX_PRICE   = 50_000   # € Maximalpreis Grundstücke
MIN_RENDITE = 4.0      # % p.a. Mindestrendite Crowdfunding
REGIONS     = ["berlin", "brandenburg", "mecklenburg", "sachsen", "sachsen-anhalt"]

OUTPUT_DIR  = Path(__file__).parent / "output"
PAUSE_S     = 1.5   # Sekunden Pause zwischen Requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ═══════════════════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def safe_get(session: requests.Session, url: str) -> requests.Response | None:
    """GET mit Timeout und Exception-Handling. Gibt None bei Fehler zurück."""
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"    Warning: GET {url}: {e}")
        return None


def in_region(text: str) -> bool:
    """Prüft ob ein Ortstext zu einer der Zielregionen gehört."""
    t = text.lower()
    return any(r in t for r in REGIONS)


def parse_price(text: str) -> int | None:
    """Extrahiert integer Preis aus Text wie '45.000 €' oder '45000'."""
    import re
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str) -> int | None:
    """Extrahiert integer Fläche aus Text wie '2.500 m²' oder '2500 qm'."""
    import re
    digits = re.sub(r"[^\d]", "", text.split("m")[0].split("q")[0])
    return int(digits) if digits else None


if __name__ == "__main__":
    print("Investment Scanner — Skeleton OK")
```

**Step 2: Syntax-Check:**
```bash
cd /root/investment_scanner
python3 -c "import investment_scanner; print('Syntax OK')"
```
Erwartet: `Syntax OK`

**Step 3: `run_scanner.sh` anlegen:**
```bash
#!/bin/bash
cd /root/investment_scanner
python3 investment_scanner.py 2>&1 | tee logs/scanner_$(date +%Y-%m-%d).log
```
```bash
chmod +x run_scanner.sh
```

**Step 4: Commit:**
```bash
cd /root/investment_scanner
git add investment_scanner.py run_scanner.sh
git commit -m "feat: add project skeleton, config, and helper functions"
```

---

### Task 2: Nutzungsideen-Logik

**Files:**
- Modify: `investment_scanner.py` — nach `parse_area()`

**Kontext:**
Rein regelbasierte Funktion. Gibt einen lesbaren String zurück. Kategorie kommt
aus dem Inseratstitel (Schlüsselwörter). Fläche in m².

**Step 1: Funktion einfügen:**

```python
def nutzungsidee(titel: str, flaeche_m2: int | None) -> str:
    """
    Regelbasierte Nutzungsidee basierend auf Titel-Keywords und Fläche.
    """
    t = titel.lower()
    f = flaeche_m2 or 0

    if any(k in t for k in ["wald", "forst", "holz"]):
        return "Holzertrag, Erholungswald"
    if any(k in t for k in ["bauland", "baugrundstück", "bauplatz", "wohnbauland"]):
        return "Tiny House, Ferienwohnung, Neubau"
    if any(k in t for k in ["gewerbe", "industrie", "lager"]):
        return "Stellplatz, Lagerplatz, Automatenstandort"
    if any(k in t for k in ["freizeit", "camping", "erholung", "gartenland"]):
        return "Freizeitgrundstück, Camping"
    if any(k in t for k in ["acker", "landwirtschaft", "wiese", "grünland"]):
        if f >= 2000:
            return "PV-Anlage (Pacht/Eigen), Landwirtschaft"
        return "Kleingarten, Freizeitgrundstück"
    # Kein Keyword → nach Fläche entscheiden
    if f >= 5000:
        return "PV-Anlage (Pacht/Eigen)"
    if f >= 500:
        return "Kleingarten, Gartennutzung"
    return "Stellplatz, Lagerplatz"
```

**Step 2: Schnelltest:**
```bash
cd /root/investment_scanner
python3 -c "
import investment_scanner as iv
assert 'PV' in iv.nutzungsidee('Ackerland Brandenburg', 5000)
assert 'Wald' in iv.nutzungsidee('Waldgrundstück bei Rostock', 3000) or 'Holz' in iv.nutzungsidee('Waldgrundstück bei Rostock', 3000)
assert 'Tiny House' in iv.nutzungsidee('Baugrundstück Berlin', 500)
assert 'Kleingarten' in iv.nutzungsidee('Ackerland', 800)
assert 'Stellplatz' in iv.nutzungsidee('Sonstiges Grundstück', 100)
print('nutzungsidee OK')
"
```
Erwartet: `nutzungsidee OK`

**Step 3: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add regelbasierte nutzungsidee() function"
```

---

### Task 3: Kleinanzeigen.de Scraper

**Files:**
- Modify: `investment_scanner.py` — neue Funktion `scrape_kleinanzeigen()`

**Kontext:**
Kleinanzeigen.de (ehemals eBay Kleinanzeigen) listet Grundstücke in Kategorie
`c211` (Grundstücke). Die Suchergebnisse sind server-seitig gerendert.

Such-URL für Grundstücke bis 50.000 €, ohne Ortsfilter, um alle Regionen abzudecken:
`https://www.kleinanzeigen.de/s-grundstuecke/preis::50000/c211`

HTML-Struktur der Ergebnisse (Stand 2026, ggf. per Browser-Inspektion prüfen):
- `<article class="aditem">` — ein Eintrag
- `<a class="ellipsis">` — Titel + Link (`href`)
- `<p class="aditem-main--middle--price-shipping--price">` — Preis
- `<div class="aditem-main--top--left">` — Ort
- `<p class="aditem-main--middle--description">` — Beschreibung (enthält oft Fläche)

**WICHTIG:** HTML-Struktur vor Implementierung per `curl` oder Browser prüfen!
```bash
curl -s -A "Mozilla/5.0" "https://www.kleinanzeigen.de/s-grundstuecke/preis::50000/c211" | grep -i "aditem" | head -5
```
Falls die Klassen abweichen, Selektoren entsprechend anpassen.

**Step 1: Funktion einfügen (nach `nutzungsidee`):**

```python
# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPER: GRUNDSTÜCKE
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_kleinanzeigen(session: requests.Session) -> list[dict]:
    """
    Scrapet Grundstücke von Kleinanzeigen.de.
    Filtert nach Region und Maximalpreis.
    Gibt Liste von Dicts zurück.
    """
    url   = f"https://www.kleinanzeigen.de/s-grundstuecke/preis::{MAX_PRICE}/c211"
    print(f"  Kleinanzeigen: {url}")
    results = []

    for page in range(1, 4):  # max 3 Seiten
        page_url = url if page == 1 else url.replace("/c211", f"/seite:{page}/c211")
        r = safe_get(session, page_url)
        if r is None:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("article.aditem")
        if not items:
            print(f"    Seite {page}: keine Einträge (HTML-Struktur prüfen!)")
            break

        for item in items:
            try:
                title_el = item.select_one("a.ellipsis")
                price_el  = item.select_one(".aditem-main--middle--price-shipping--price")
                loc_el    = item.select_one(".aditem-main--top--left")
                desc_el   = item.select_one(".aditem-main--middle--description")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href  = "https://www.kleinanzeigen.de" + title_el.get("href", "")
                price_raw = price_el.get_text(strip=True) if price_el else ""
                loc_raw   = loc_el.get_text(strip=True)   if loc_el   else ""
                desc_raw  = desc_el.get_text(strip=True)  if desc_el  else ""

                price = parse_price(price_raw)
                if price and price > MAX_PRICE:
                    continue
                if not in_region(loc_raw):
                    continue

                # Fläche aus Beschreibung oder Titel extrahieren
                import re
                area_match = re.search(r"(\d[\d.,]*)\s*(m²|qm|ha)", title + " " + desc_raw, re.I)
                flaeche = None
                if area_match:
                    val_str = area_match.group(1).replace(".", "").replace(",", "")
                    einheit = area_match.group(2).lower()
                    flaeche = int(val_str)
                    if "ha" in einheit:
                        flaeche *= 10_000

                results.append({
                    "kategorie":    "Grundstück",
                    "quelle":       "Kleinanzeigen",
                    "titel":        title,
                    "ort":          loc_raw,
                    "flaeche_m2":   flaeche,
                    "preis_eur":    price,
                    "eur_pro_m2":   round(price / flaeche, 2) if price and flaeche else None,
                    "nutzung":      nutzungsidee(title, flaeche),
                    "link":         href,
                })
            except Exception as e:
                print(f"    Parse-Fehler: {e}")
                continue

        print(f"    Seite {page}: {len(items)} Einträge gefunden")
        if len(items) < 20:
            break
        time.sleep(PAUSE_S)

    print(f"  → {len(results)} Kleinanzeigen-Grundstücke nach Filter")
    return results
```

**Step 2: Schnelltest (live):**
```bash
cd /root/investment_scanner
python3 -c "
import investment_scanner as iv
s = iv.make_session()
r = iv.scrape_kleinanzeigen(s)
print(f'{len(r)} Ergebnisse')
if r:
    print('Beispiel:', r[0])
"
```
Erwartet: Mindestens 1 Ergebnis, kein Traceback. Falls 0 Ergebnisse: HTML-Selektoren
per `curl` prüfen und anpassen (siehe Kontext oben).

**Step 3: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add scrape_kleinanzeigen() for Grundstücke"
```

---

### Task 4: DGA + Zwangsversteigerung Scrapers

**Files:**
- Modify: `investment_scanner.py` — zwei neue Funktionen

**Kontext:**

**DGA (Deutsche Grundstücksauktionen):** `https://www.dga.de/auktionen/`
Listet Auktionsobjekte. Filtere nach Bundesland. Die Objekte haben Typ, Ort, Preis, Auktionsdatum.
Vor Implementierung HTML-Struktur prüfen:
```bash
curl -s -A "Mozilla/5.0" "https://www.dga.de/auktionen/" | grep -i "objekt\|auktion\|preis" | head -10
```

**Zwangsversteigerungstermine:** `https://www.zvg-portal.de/index.php?button=Suchen&All=1`
Das offizielle Justiz-Portal für Zwangsversteigerungen. Filtere nach Bundesland.
Alternativ: `https://www.zwangsversteigerungstermine.de/`

**Step 1: DGA-Scraper einfügen (nach `scrape_kleinanzeigen`):**

```python
def scrape_dga(session: requests.Session) -> list[dict]:
    """
    Scrapet Auktionen von Deutsche Grundstücksauktionen (dga.de).
    """
    url = "https://www.dga.de/auktionen/"
    print(f"  DGA: {url}")
    r = safe_get(session, url)
    if r is None:
        print("    ⚠️ DGA nicht erreichbar")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []

    # Selektoren ggf. anpassen nach HTML-Inspektion!
    items = soup.select(".auction-item, .objekt, article, .listing-item")
    if not items:
        # Fallback: alle Links die auf Objekte verweisen
        items = [a for a in soup.find_all("a", href=True)
                 if "/auktion" in a.get("href", "") or "/objekt" in a.get("href", "")]

    for item in items:
        try:
            text  = item.get_text(" ", strip=True)
            title = item.get_text(strip=True)[:120]
            href  = item.get("href", "") if item.name == "a" else ""
            if href and not href.startswith("http"):
                href = "https://www.dga.de" + href

            if not in_region(text):
                continue

            price = parse_price(text)
            if price and price > MAX_PRICE:
                continue

            flaeche = parse_area(text)
            results.append({
                "kategorie":  "Grundstück",
                "quelle":     "DGA Auktion",
                "titel":      title,
                "ort":        "",
                "flaeche_m2": flaeche,
                "preis_eur":  price,
                "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
                "nutzung":    nutzungsidee(title, flaeche),
                "link":       href or url,
            })
        except Exception:
            continue

    print(f"  → {len(results)} DGA-Auktionen nach Filter")
    return results


def scrape_zvg(session: requests.Session) -> list[dict]:
    """
    Scrapet Zwangsversteigerungen vom amtlichen ZVG-Portal.
    """
    results = []
    # Bundesländer-Codes für die Zielregionen
    bundeslaender = {
        "Berlin":          "10",
        "Brandenburg":     "12",
        "Mecklenburg-VP":  "13",
        "Sachsen":         "14",
        "Sachsen-Anhalt":  "15",
    }

    for land, code in bundeslaender.items():
        url = f"https://www.zvg-portal.de/index.php?button=Suchen&land={code}&All=1"
        print(f"  ZVG {land}: {url}")
        r = safe_get(session, url)
        if r is None:
            print(f"    ⚠️ ZVG {land} nicht erreichbar")
            time.sleep(PAUSE_S)
            continue

        soup  = BeautifulSoup(r.text, "html.parser")
        rows  = soup.select("table tr")

        for row in rows[1:]:  # Header überspringen
            try:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                text    = row.get_text(" ", strip=True)
                title   = cols[0].get_text(strip=True)[:120] if cols else ""
                ort     = cols[1].get_text(strip=True)       if len(cols) > 1 else land
                link_el = row.find("a", href=True)
                href    = link_el["href"] if link_el else url
                if href and not href.startswith("http"):
                    href = "https://www.zvg-portal.de/" + href.lstrip("/")

                price   = parse_price(text)
                if price and price > MAX_PRICE:
                    continue

                flaeche = parse_area(text)
                results.append({
                    "kategorie":  "Grundstück",
                    "quelle":     "Zwangsversteigerung",
                    "titel":      title or f"ZVG {land}",
                    "ort":        ort,
                    "flaeche_m2": flaeche,
                    "preis_eur":  price,
                    "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
                    "nutzung":    nutzungsidee(title, flaeche),
                    "link":       href,
                })
            except Exception:
                continue

        print(f"    → {land}: {len([x for x in results if x['quelle']=='Zwangsversteigerung'])} Einträge")
        time.sleep(PAUSE_S)

    print(f"  → {len(results)} ZVG-Einträge nach Filter")
    return results
```

**Step 2: Schnelltest:**
```bash
cd /root/investment_scanner
python3 -c "
import investment_scanner as iv
s = iv.make_session()
r1 = iv.scrape_dga(s)
print(f'DGA: {len(r1)} Ergebnisse')
r2 = iv.scrape_zvg(s)
print(f'ZVG: {len(r2)} Ergebnisse')
print('OK — kein Traceback')
"
```
Erwartet: Kein Traceback. Ergebnisse können 0 sein wenn Portale nicht erreichbar
oder HTML-Selektoren angepasst werden müssen.

**Step 3: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add scrape_dga() and scrape_zvg() for Grundstücke"
```

---

### Task 5: Crowdfunding Scrapers (Bettervest, Bergfürst, Wiwin, Exporo)

**Files:**
- Modify: `investment_scanner.py` — vier neue Funktionen

**Kontext:**
Crowdfunding-Plattformen listen aktive Projekte auf. Wir suchen nach:
- Rendite ≥ MIN_RENDITE (4%)
- Typ: Immobilie, PV/Energie, Nachhaltig
- Mindestanlage (zur Info, kein Filter)

**WICHTIG:** Diese Seiten können JavaScript-gerendert sein. Vor Implementierung prüfen:
```bash
curl -s -A "Mozilla/5.0" "https://www.bettervest.com/de/projekte/" | grep -i "rendite\|projekt\|zinsen" | head -5
```
Falls kein sinnvoller Inhalt → Netzwerk-Tab im Browser öffnen, API-Call suchen (oft `/api/projects` o.ä.).

**Step 1: Vier Crowdfunding-Scraper einfügen:**

```python
# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPER: CROWDFUNDING / BETEILIGUNGEN
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_rendite(text: str) -> float | None:
    """Extrahiert Rendite aus Text wie '6,5 % p.a.' oder '6.5%'."""
    import re
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%", text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def scrape_bettervest(session: requests.Session) -> list[dict]:
    """Scrapet aktive Projekte von bettervest.com (Fokus PV/Energie)."""
    url = "https://www.bettervest.com/de/projekte/"
    print(f"  Bettervest: {url}")
    r = safe_get(session, url)
    if r is None:
        print("    ⚠️ Bettervest nicht erreichbar")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []

    # Selektoren nach HTML-Inspektion anpassen
    items = soup.select(".project-item, .project-card, .campaign, article")
    print(f"    {len(items)} Projekt-Elemente gefunden")

    for item in items:
        try:
            text     = item.get_text(" ", strip=True)
            title_el = item.select_one("h2, h3, .project-title, .title")
            link_el  = item.select_one("a[href]")
            title    = title_el.get_text(strip=True) if title_el else text[:80]
            href     = link_el["href"] if link_el else url
            if href and not href.startswith("http"):
                href = "https://www.bettervest.com" + href

            rendite = _parse_rendite(text)
            if rendite and rendite < MIN_RENDITE:
                continue

            results.append({
                "kategorie":       "Beteiligung",
                "plattform":       "Bettervest",
                "titel":           title,
                "typ":             "PV/Energie",
                "rendite_pct":     rendite,
                "laufzeit":        "",
                "min_anlage_eur":  None,
                "status":          "aktiv",
                "link":            href,
            })
        except Exception:
            continue

    print(f"  → {len(results)} Bettervest-Projekte nach Filter")
    return results


def scrape_bergfuerst(session: requests.Session) -> list[dict]:
    """Scrapet aktive Projekte von bergfuerst.com (Immobilien)."""
    url = "https://www.bergfuerst.com/projekte"
    print(f"  Bergfürst: {url}")
    r = safe_get(session, url)
    if r is None:
        print("    ⚠️ Bergfürst nicht erreichbar")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []
    items   = soup.select(".project, .investment-card, article, .offer")
    print(f"    {len(items)} Projekt-Elemente gefunden")

    for item in items:
        try:
            text     = item.get_text(" ", strip=True)
            title_el = item.select_one("h2, h3, .name, .title")
            link_el  = item.select_one("a[href]")
            title    = title_el.get_text(strip=True) if title_el else text[:80]
            href     = link_el["href"] if link_el else url
            if href and not href.startswith("http"):
                href = "https://www.bergfuerst.com" + href

            rendite = _parse_rendite(text)
            if rendite and rendite < MIN_RENDITE:
                continue

            import re
            laufzeit_m = re.search(r"(\d+)\s*(Monate|Jahre|Monat|Jahr)", text, re.I)
            laufzeit   = laufzeit_m.group(0) if laufzeit_m else ""

            min_m = re.search(r"ab\s*(\d[\d.,]*)\s*€", text, re.I)
            min_anlage = parse_price(min_m.group(1)) if min_m else None

            results.append({
                "kategorie":      "Beteiligung",
                "plattform":      "Bergfürst",
                "titel":          title,
                "typ":            "Immobilie",
                "rendite_pct":    rendite,
                "laufzeit":       laufzeit,
                "min_anlage_eur": min_anlage,
                "status":         "aktiv",
                "link":           href,
            })
        except Exception:
            continue

    print(f"  → {len(results)} Bergfürst-Projekte nach Filter")
    return results


def scrape_wiwin(session: requests.Session) -> list[dict]:
    """Scrapet aktive Projekte von wiwin.de (Nachhaltig/PV)."""
    url = "https://www.wiwin.de/investments"
    print(f"  Wiwin: {url}")
    r = safe_get(session, url)
    if r is None:
        print("    ⚠️ Wiwin nicht erreichbar")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []
    items   = soup.select(".investment, .project-card, article, .card")
    print(f"    {len(items)} Projekt-Elemente gefunden")

    for item in items:
        try:
            text     = item.get_text(" ", strip=True)
            title_el = item.select_one("h2, h3, .investment-title, .title")
            link_el  = item.select_one("a[href]")
            title    = title_el.get_text(strip=True) if title_el else text[:80]
            href     = link_el["href"] if link_el else url
            if href and not href.startswith("http"):
                href = "https://www.wiwin.de" + href

            rendite = _parse_rendite(text)
            if rendite and rendite < MIN_RENDITE:
                continue

            typ = "PV/Energie" if any(k in text.lower() for k in ["solar", "pv", "wind", "energie"]) else "Nachhaltig"

            results.append({
                "kategorie":      "Beteiligung",
                "plattform":      "Wiwin",
                "titel":          title,
                "typ":            typ,
                "rendite_pct":    rendite,
                "laufzeit":       "",
                "min_anlage_eur": None,
                "status":         "aktiv",
                "link":           href,
            })
        except Exception:
            continue

    print(f"  → {len(results)} Wiwin-Projekte nach Filter")
    return results


def scrape_exporo(session: requests.Session) -> list[dict]:
    """Scrapet aktive Projekte von exporo.de (Immobilien-Crowdfunding)."""
    url = "https://exporo.de/invest/"
    print(f"  Exporo: {url}")
    r = safe_get(session, url)
    if r is None:
        print("    ⚠️ Exporo nicht erreichbar")
        return []

    soup    = BeautifulSoup(r.text, "html.parser")
    results = []
    items   = soup.select(".project-card, .investment, article, .offer-card")
    print(f"    {len(items)} Projekt-Elemente gefunden")

    for item in items:
        try:
            text     = item.get_text(" ", strip=True)
            title_el = item.select_one("h2, h3, .project-name, .title")
            link_el  = item.select_one("a[href]")
            title    = title_el.get_text(strip=True) if title_el else text[:80]
            href     = link_el["href"] if link_el else url
            if href and not href.startswith("http"):
                href = "https://exporo.de" + href

            rendite = _parse_rendite(text)
            if rendite and rendite < MIN_RENDITE:
                continue

            import re
            laufzeit_m = re.search(r"(\d+)\s*(Monate|Jahre|Monat|Jahr)", text, re.I)
            laufzeit   = laufzeit_m.group(0) if laufzeit_m else ""

            results.append({
                "kategorie":      "Beteiligung",
                "plattform":      "Exporo",
                "titel":          title,
                "typ":            "Immobilie",
                "rendite_pct":    rendite,
                "laufzeit":       laufzeit,
                "min_anlage_eur": None,
                "status":         "aktiv",
                "link":           href,
            })
        except Exception:
            continue

    print(f"  → {len(results)} Exporo-Projekte nach Filter")
    return results
```

**Step 2: Schnelltest:**
```bash
cd /root/investment_scanner
python3 -c "
import investment_scanner as iv
s = iv.make_session()
for fn in [iv.scrape_bettervest, iv.scrape_bergfuerst, iv.scrape_wiwin, iv.scrape_exporo]:
    r = fn(s)
    print(f'{fn.__name__}: {len(r)} Ergebnisse')
print('OK — kein Traceback')
"
```

**Step 3: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add crowdfunding scrapers (Bettervest, Bergfürst, Wiwin, Exporo)"
```

---

### Task 6: HTML-Report (CSS + build_tables + generate_html)

**Files:**
- Modify: `investment_scanner.py` — CSS-String + 3 Funktionen

**Kontext:**
Gleiche Architektur wie der Sports Scanner — CSS als String, dann `build_grundstuecke_table()`,
`build_beteiligungen_table()`, `generate_html()`. Zwei Sektionen, Summary-Cards oben.

**Step 1: CSS-String und Hilfsfunktionen einfügen (vor `generate_html`):**

```python
# ═══════════════════════════════════════════════════════════════════════════════
# HTML REPORT
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background:#f4f7fb; margin:0; padding:20px; color:#1a1a2e; }
h1   { color:#1a3a6e; border-bottom:2px solid #c8d8f0; padding-bottom:10px; }
h2   { color:#1a56a0; margin-top:28px; }
.summary { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.card { background:#f0f5ff; border:1px solid #c8d8f0; border-radius:8px;
        padding:14px 22px; min-width:130px; }
.card .val { font-size:1.9em; font-weight:700; color:#1a56a0; }
.card .lbl { color:#555577; font-size:0.8em; margin-top:2px; }
table { width:100%; border-collapse:collapse; background:#ffffff;
        border:1px solid #dde3ed; border-radius:8px; overflow:hidden; margin:14px 0; }
th  { background:#eef2fa; padding:9px 12px; text-align:left;
      color:#444466; font-size:0.82em; border-bottom:1px solid #dde3ed; }
td  { padding:8px 12px; border-bottom:1px solid #eef2fa; font-size:0.88em; color:#1a1a2e; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#f5f8ff; }
.tag  { background:#1a56a0; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.tag2 { background:#1a7a30; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.tag3 { background:#e07000; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.warn { background:#fff8e8; border-left:3px solid #e09000; padding:10px 14px;
        color:#664400; font-size:0.82em; border-radius:0 6px 6px 0; margin:8px 0; }
.empty { color:#777799; padding:18px; text-align:center;
         background:#f7f9ff; border:1px solid #dde3ed; border-radius:8px; }
a    { color:#1a56a0; text-decoration:none; }
a:hover { text-decoration:underline; }
.footer { color:#777799; font-size:0.78em; margin-top:30px;
          border-top:1px solid #dde3ed; padding-top:14px; }
"""


def _quelle_tag(quelle: str) -> str:
    tags = {
        "Kleinanzeigen":      "tag",
        "DGA Auktion":        "tag2",
        "Zwangsversteigerung":"tag3",
    }
    css = tags.get(quelle, "tag")
    return f'<span class="{css}">{quelle}</span>'


def _plattform_tag(plattform: str) -> str:
    return f'<span class="tag">{plattform}</span>'


def build_grundstuecke_table(bets: list[dict]) -> str:
    if not bets:
        return '<div class="empty">Keine Grundstücke gefunden.</div>'
    headers = ["Quelle", "Titel", "Ort", "Fläche", "Preis", "€/m²", "Nutzungsidee", "Link"]
    rows = ""
    for b in sorted(bets, key=lambda x: x.get("preis_eur") or 999_999):
        flaeche = f"{b['flaeche_m2']:,} m²".replace(",", ".") if b.get("flaeche_m2") else "–"
        preis   = f"{b['preis_eur']:,} €".replace(",", ".") if b.get("preis_eur") else "–"
        epm2    = f"{b['eur_pro_m2']:.1f}" if b.get("eur_pro_m2") else "–"
        rows += f"""<tr>
          <td>{_quelle_tag(b['quelle'])}</td>
          <td><strong>{b['titel'][:80]}</strong></td>
          <td>{b.get('ort', '–')}</td>
          <td>{flaeche}</td>
          <td>{preis}</td>
          <td>{epm2}</td>
          <td style="color:#555577;font-size:0.82em">{b.get('nutzung','–')}</td>
          <td><a href="{b['link']}" target="_blank">→ Inserat</a></td>
        </tr>"""
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def build_beteiligungen_table(bets: list[dict]) -> str:
    if not bets:
        return '<div class="empty">Keine Beteiligungen gefunden.</div>'
    headers = ["Plattform", "Projekt", "Typ", "Rendite p.a.", "Laufzeit", "Mind. Anlage", "Link"]
    rows = ""
    for b in sorted(bets, key=lambda x: -(x.get("rendite_pct") or 0)):
        rendite    = f"{b['rendite_pct']:.1f} %" if b.get("rendite_pct") else "–"
        min_anlage = f"{b['min_anlage_eur']:,} €".replace(",", ".") if b.get("min_anlage_eur") else "–"
        rows += f"""<tr>
          <td>{_plattform_tag(b['plattform'])}</td>
          <td><strong>{b['titel'][:80]}</strong></td>
          <td>{b.get('typ','–')}</td>
          <td style="color:#1a7a30;font-weight:700">{rendite}</td>
          <td>{b.get('laufzeit','–')}</td>
          <td>{min_anlage}</td>
          <td><a href="{b['link']}" target="_blank">→ Projekt</a></td>
        </tr>"""
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def generate_html(grundstuecke: list[dict], beteiligungen: list[dict],
                  warnings: list[str]) -> str:
    date_str  = datetime.now().strftime("%d.%m.%Y")
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Ø €/m²
    preise_m2 = [b["eur_pro_m2"] for b in grundstuecke if b.get("eur_pro_m2")]
    avg_epm2  = f"{sum(preise_m2)/len(preise_m2):.0f} €/m²" if preise_m2 else "–"

    # Beste Rendite
    renditen  = [b["rendite_pct"] for b in beteiligungen if b.get("rendite_pct")]
    best_rend = f"{max(renditen):.1f} %" if renditen else "–"

    warn_html = "".join(f'<div class="warn">⚠️ {w}</div>' for w in warnings)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Investment Scanner {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<h1>💼 Investment Scanner — {date_str}</h1>

<div class="summary">
  <div class="card"><div class="val">{len(grundstuecke)}</div><div class="lbl">🏡 Grundstücke</div></div>
  <div class="card"><div class="val">{len(beteiligungen)}</div><div class="lbl">💰 Beteiligungen</div></div>
  <div class="card"><div class="val">{avg_epm2}</div><div class="lbl">Ø €/m²</div></div>
  <div class="card"><div class="val">{best_rend}</div><div class="lbl">Beste Rendite</div></div>
</div>

{warn_html}

<h2>🏡 Grundstücke (max. {MAX_PRICE:,} €)".replace(",", ".")</h2>
{build_grundstuecke_table(grundstuecke)}

<h2>💰 Beteiligungen & Crowdfunding (min. {MIN_RENDITE} % p.a.)</h2>
{build_beteiligungen_table(beteiligungen)}

<div class="footer">
  Generiert: {timestamp} &nbsp;|&nbsp;
  Quellen: Kleinanzeigen.de · DGA · ZVG-Portal · Bettervest · Bergfürst · Wiwin · Exporo<br>
  ⚠️ Diese Übersicht dient ausschließlich zu Informationszwecken. Keine Anlageberatung.
</div>
</body>
</html>"""
```

**WICHTIG:** In `generate_html` gibt es einen Syntax-Fehler in der h2-Zeile durch
das `.replace()` nach dem f-string-Ende. Diese Zeile korrekt schreiben:
```python
<h2>🏡 Grundstücke (max. {MAX_PRICE:,} €)</h2>
```
(Kein `.replace()` nötig — Python-Format gibt `50,000` aus, für Deutsche Darstellung
entweder manuell `f"{MAX_PRICE:_}".replace("_",".")` oder einfach `50.000` hardcoden.)

**Step 2: Syntax-Check:**
```bash
cd /root/investment_scanner
python3 -c "import investment_scanner; print('Syntax OK')"
```

**Step 3: Schnelltest generate_html:**
```bash
python3 -c "
import investment_scanner as iv
mock_g = [{'quelle':'Kleinanzeigen','titel':'Ackerland Brandenburg','ort':'Potsdam',
           'flaeche_m2':3000,'preis_eur':25000,'eur_pro_m2':8.3,
           'nutzung':'PV-Anlage','link':'https://example.com'}]
mock_b = [{'plattform':'Bettervest','titel':'Solaranlage Sachsen','typ':'PV/Energie',
           'rendite_pct':5.5,'laufzeit':'36 Monate','min_anlage_eur':500,
           'status':'aktiv','link':'https://example.com'}]
html = iv.generate_html(mock_g, mock_b, ['Test-Warnung'])
assert '<table>' in html
assert 'Ackerland' in html
assert 'Bettervest' in html
assert '5.5' in html
print('generate_html OK')
"
```

**Step 4: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add CSS, build_grundstuecke_table, build_beteiligungen_table, generate_html"
```

---

### Task 7: main() + CSV-Export + run_scanner.sh

**Files:**
- Modify: `investment_scanner.py` — `main()` + CSV-Block

**Kontext:**
`main()` ruft alle Scraper auf, sammelt Warnings, erzeugt HTML + CSV.
CSV enthält alle Einträge (Grundstücke + Beteiligungen) in einer Datei mit
Spalte `Kategorie`.

**Step 1: `main()` am Dateiende einfügen (vor `if __name__ == "__main__":`):**

```python
# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print(f"  Investment Scanner — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("=" * 60)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir  = OUTPUT_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    session  = make_session()
    warnings = []

    # ── GRUNDSTÜCKE ─────────────────────────────────────────────────────────
    print("\n[🏡 Grundstücke] Scraping …")
    grundstuecke = []

    r = scrape_kleinanzeigen(session)
    grundstuecke.extend(r)
    if not r:
        warnings.append("Kleinanzeigen: keine Ergebnisse (Selektoren prüfen)")
    time.sleep(PAUSE_S)

    r = scrape_dga(session)
    grundstuecke.extend(r)
    if not r:
        warnings.append("DGA: keine Ergebnisse")
    time.sleep(PAUSE_S)

    r = scrape_zvg(session)
    grundstuecke.extend(r)
    if not r:
        warnings.append("ZVG-Portal: keine Ergebnisse")
    time.sleep(PAUSE_S)

    # ── BETEILIGUNGEN ───────────────────────────────────────────────────────
    print("\n[💰 Beteiligungen] Scraping …")
    beteiligungen = []

    for fn, name in [
        (scrape_bettervest, "Bettervest"),
        (scrape_bergfuerst, "Bergfürst"),
        (scrape_wiwin,      "Wiwin"),
        (scrape_exporo,     "Exporo"),
    ]:
        r = fn(session)
        beteiligungen.extend(r)
        if not r:
            warnings.append(f"{name}: keine Ergebnisse")
        time.sleep(PAUSE_S)

    # ── REPORT ──────────────────────────────────────────────────────────────
    print(f"\n[📊 Report] Grundstücke: {len(grundstuecke)}")
    print(f"[📊 Report] Beteiligungen: {len(beteiligungen)}")

    html      = generate_html(grundstuecke, beteiligungen, warnings)
    html_path = out_dir / "investments.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[📊 Report] HTML: {html_path}")

    # ── CSV ─────────────────────────────────────────────────────────────────
    rows = []
    for b in grundstuecke:
        rows.append({
            "Kategorie": "Grundstück",
            "Quelle":    b.get("quelle", ""),
            "Titel":     b.get("titel", ""),
            "Ort":       b.get("ort", ""),
            "Fläche m²": b.get("flaeche_m2", ""),
            "Preis €":   b.get("preis_eur", ""),
            "€/m²":      b.get("eur_pro_m2", ""),
            "Nutzung":   b.get("nutzung", ""),
            "Link":      b.get("link", ""),
        })
    for b in beteiligungen:
        rows.append({
            "Kategorie":  "Beteiligung",
            "Quelle":     b.get("plattform", ""),
            "Titel":      b.get("titel", ""),
            "Typ":        b.get("typ", ""),
            "Rendite %":  b.get("rendite_pct", ""),
            "Laufzeit":   b.get("laufzeit", ""),
            "Mind. €":    b.get("min_anlage_eur", ""),
            "Link":       b.get("link", ""),
        })

    if rows:
        import csv as csv_mod
        csv_path = out_dir / "investments.csv"
        fieldnames = sorted({k for r in rows for k in r})
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv_mod.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"[📊 Report] CSV:  {csv_path}")

    print("\n✓ Fertig!")
    return 0
```

**Step 2: `if __name__` Block anpassen:**
```python
if __name__ == "__main__":
    raise SystemExit(main())
```

**Step 3: Vollständiger Trockenlauf:**
```bash
cd /root/investment_scanner
timeout 180 python3 investment_scanner.py 2>&1
```
Erwartet: Kein Traceback, `✓ Fertig!` am Ende.
HTML-Datei unter `output/YYYY-MM-DD/investments.html` prüfen:
```bash
ls -la output/*/investments.html
```

**Step 4: Commit:**
```bash
git add investment_scanner.py
git commit -m "feat: add main(), CSV export, full pipeline"
```

---

## Fertig!

Nach Task 7 ist der Investment Scanner einsatzbereit:
- `python3 investment_scanner.py` → scrapet alle Quellen → HTML + CSV
- Scraper die 0 Ergebnisse liefern → Warnings im Report, kein Crash
- HTML-Report unter `output/YYYY-MM-DD/investments.html` öffnen
- Bei JS-gerenderten Seiten (0 Elemente gefunden): Browser-Netzwerk-Tab öffnen,
  API-Endpunkt suchen und Scraper entsprechend anpassen
