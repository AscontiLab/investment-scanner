#!/usr/bin/env python3
"""
Investment Opportunity Scanner
───────────────────────────────
Scrapet Grundstücke und Crowdfunding-Beteiligungen für Ostdeutschland.

Quellen Grundstücke:  Kleinanzeigen.de, DGA, Zwangsversteigerungstermine.de
Quellen Crowdfunding: Bettervest, Bergfürst, Wiwin, Exporo
"""

import argparse
import csv
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from html import escape
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "scanner.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename=str(LOG_FILE),
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

MAX_PRICE   = 50_000   # € Maximalpreis Grundstücke
MIN_RENDITE = 4.0      # % p.a. Mindestrendite Crowdfunding

# DGA Company-Mapping
DGA_COMPANIES = {
    "D": "DGA",
    "S": "Sächsische",
    "N": "Norddeutsche",
    "W": "Westdeutsche",
    "P": "Plettner",
}

DGA_CATEGORIES = {
    "GRDBG": "Grundstück",
    "ETWTE": "Eigentumswohnung",
    "EFHZFH": "Ein-/Zweifamilienhaus",
    "MFHWGH": "Mehrfamilienhaus",
    "GE": "Gewerbe",
    "Special": "Sonderobjekt",
}

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

_AREA_RE = re.compile(r"(\d[\d.]*)\s*(?:m²|m2|qm)", re.IGNORECASE)
_REGION_RE = re.compile(
    r"\b(?:berlin|brandenburg|mecklenburg|sachsen-anhalt|sachsen)\b",
    re.IGNORECASE,
)

# ═══════════════════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def make_session() -> requests.Session:
    """Erstellt eine requests.Session mit Browser-Headers für alle Scraper."""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def safe_get(session: requests.Session, url: str) -> requests.Response | None:
    """GET mit Timeout und Exception-Handling. Gibt None bei Fehler zurück."""
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return r
    except requests.HTTPError as e:
        logger.warning("HTTP %s: %s", e.response.status_code if e.response else "?", url)
        return None
    except Exception as e:
        logger.warning("GET %s: %s", url, e)
        return None


def in_region(text: str | None) -> bool:
    """Prüft ob ein Ortstext zu einer der Zielregionen gehört (Wortgrenze)."""
    return bool(_REGION_RE.search(text or ""))


def parse_price(text: str | None) -> int | None:
    """Extrahiert integer Preis aus Text wie '45.000 €' oder '45000'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str | None) -> int | None:
    """Extrahiert integer Fläche aus Text. Unterstützt ha und m²/qm.

    Normalisiert deutsches Zahlenformat: '1.500' → 1500, '1,5' → 1.5.
    ha wird in m² umgerechnet (1 ha = 10.000 m²).
    """
    if not text:
        return None
    # ha: try first (higher priority — "1,5 ha" is unambiguous)
    ha_match = re.search(r"(\d[\d.,]*)\s*ha\b", text, re.IGNORECASE)
    if ha_match:
        raw = ha_match.group(1)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.search(r"\.\d{3}$", raw):
            raw = raw.replace(".", "")
        return int(float(raw) * 10_000)
    # m² / qm
    m2_match = _AREA_RE.search(text)
    if m2_match:
        raw = m2_match.group(1)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.search(r"\.\d{3}$", raw):
            raw = raw.replace(".", "")
        return int(float(raw))
    return None


def nutzungsidee(titel: str, flaeche_m2: int | None) -> str:
    """
    Regelbasierte Nutzungsidee basierend auf Titel-Keywords und Fläche.
    """
    if not titel:
        return "Stellplatz, Lagerplatz"
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


# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPER: GRUNDSTÜCKE
# ═══════════════════════════════════════════════════════════════════════════════

def scrape_kleinanzeigen(session: requests.Session) -> list[dict]:
    """
    Scrapet Grundstücke von Kleinanzeigen.de.
    Filtert nach Region und Maximalpreis.
    Gibt Liste von Dicts zurück.
    """
    url   = f"https://www.kleinanzeigen.de/s-grundstuecke-garten/preis::{MAX_PRICE}/c207"
    logger.info("Kleinanzeigen: %s", url)
    results = []

    for page in range(1, 4):  # max 3 Seiten
        if page > 1:
            time.sleep(PAUSE_S)
        page_url = url if page == 1 else url.replace("/c207", f"/seite:{page}/c207")
        r = safe_get(session, page_url)
        if r is None:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("article.aditem")
        if not items:
            logger.warning("Kleinanzeigen Seite %d: keine Einträge (HTML-Struktur prüfen!)", page)
            break

        page_count = 0
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
                if price is not None and price > MAX_PRICE:
                    continue
                if not in_region(loc_raw):
                    continue

                # Fläche aus Beschreibung oder Titel extrahieren
                flaeche = parse_area(title + " " + desc_raw)

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
                page_count += 1
            except Exception as e:
                logger.warning("Kleinanzeigen Parse-Fehler: %s", e)
                continue

        logger.info("Kleinanzeigen Seite %d: %d Einträge, %d nach Filter", page, len(items), page_count)
        if len(items) < 20:
            break

    logger.info("-> %d Kleinanzeigen-Grundstücke nach Filter", len(results))
    return results


def scrape_dga(session: requests.Session) -> list[dict]:
    """
    Scrapet Grundstück-Auktionen von Deutsche Grundstücksauktionen AG (dga-ag.de).

    Die Seite bettet alle Objekte als JSON in eine JS-Variable 'var locations' ein.
    Jeder Eintrag enthält ein 'filter'-Objekt mit region, limit, category,
    auctionNumber, company, rentedOrLeased, protectedAsAHistoricMonument, status
    sowie ein 'infoWindow'-HTML-Schnipsel mit Titel, Adresse und Objekt-Link.

    Filter: status in (aktuell, nachverkauf), limit <= MAX_PRICE, bundesweit.
    """
    url = "https://www.dga-ag.de/immobilie-ersteigern/immobilie-suchen-und-finden.html"
    logger.info("DGA-AG: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("DGA-AG nicht erreichbar")
        return []

    # Embedded JSON: var locations = [...];
    m = re.search(r"var locations = (\[.*?\]);", r.text, re.DOTALL)
    if not m:
        logger.warning("DGA-AG: JSON 'var locations' nicht gefunden (HTML-Struktur geändert?)")
        return []

    try:
        locations = json.loads(m.group(1))
    except Exception as e:
        logger.warning("DGA-AG JSON-Parse-Fehler: %s", e)
        return []

    allowed_statuses = {"aktuell", "nachverkauf"}

    results = []
    for entry in locations:
        try:
            f       = entry.get("filter", {})
            limit   = f.get("limit")          # auction limit in EUR (int)
            status  = str(f.get("status", "")).lower()

            # Status: nur aktuell und nachverkauf
            if status not in allowed_statuses:
                continue
            # Preisfilter (kein Limit fuer Nachverkauf)
            if status != "nachverkauf" and limit is not None and int(limit) > MAX_PRICE:
                continue

            # Company-Code und Name
            company_code = str(f.get("company", "D"))
            company_name = DGA_COMPANIES.get(company_code, "DGA")

            # Kategorie
            category_code = str(f.get("category", ""))
            category = DGA_CATEGORIES.get(category_code, category_code)

            # Auktionsnummer
            auction_number = str(f.get("auctionNumber", ""))

            # Zusatzfelder
            rented   = str(f.get("rentedOrLeased", ""))
            monument = str(f.get("protectedAsAHistoricMonument", ""))
            region   = str(f.get("region", ""))

            # Quelle: "{Company} {Status}"
            status_label = "Nachverkauf" if status == "nachverkauf" else "Auktion"
            quelle = f"{company_name} {status_label}"

            # Parse the infoWindow HTML snippet for title, address, link
            iw_soup = BeautifulSoup(entry.get("infoWindow", ""), "html.parser")
            title   = iw_soup.find("h2")
            title   = title.get_text(strip=True)[:120] if title else ""
            if not title:
                continue
            a_el    = iw_soup.find("a", href=True)
            href    = a_el["href"] if a_el else ""
            if href and not href.startswith("http"):
                href = "https://www.dga-ag.de" + href

            # Address: first <p> tags in .gmap-text hold street and city
            gmap_text = iw_soup.select_one(".gmap-text")
            ort = ""
            if gmap_text:
                paras = gmap_text.find_all("p")
                ort   = " ".join(p.get_text(strip=True) for p in paras[:2])

            # Full text for area extraction
            full_text = title + " " + ort

            flaeche = parse_area(full_text)

            price = int(limit) if limit is not None else None

            results.append({
                "kategorie":      "Grundstück",
                "quelle":         quelle,
                "titel":          title,
                "ort":            ort,
                "flaeche_m2":     flaeche,
                "preis_eur":      price,
                "eur_pro_m2":     round(price / flaeche, 2) if price and flaeche else None,
                "nutzung":        nutzungsidee(title, flaeche),
                "link":           href or url,
                "company":        company_code,
                "auction_number": auction_number,
                "category":       category,
                "category_code":  category_code,
                "status":         status,
                "rented":         rented,
                "monument":       monument,
                "region":         region,
            })
        except Exception as e:
            logger.warning("DGA-AG Parse-Fehler: %s", e)
            continue

    logger.info("-> %d DGA-Auktionen nach Filter", len(results))
    return results


def scrape_zvg(session: requests.Session) -> list[dict]:
    """
    Scrapet Zwangsversteigerungstermine vom amtlichen ZVG-Portal (zvg-portal.de).

    Das Portal liefert pro Bundesland eine HTML-Seite mit einem border=0-Table.
    Jeder Verfahrenseintrag besteht aus mehreren <TR>-Zeilen:
      - Aktenzeichen-Zeile (enthält Link zur Detailansicht)
      - Amtsgericht-Zeile
      - Objekt/Lage-Zeile (Typ + Adresse)
      - Verkehrswert-Zeile (Preis in €)
      - Termin-Zeile
      - Bekanntmachungs-PDF-Zeile
      - Leere Trennzeile

    Wir iterieren über alle <TR>, sammeln Kontext pro Verfahren und
    schreiben einen Eintrag, sobald wir einen Verkehrswert gefunden haben.
    """
    # land_abk codes for east German states
    bundeslaender = {
        "Berlin":          "be",
        "Brandenburg":     "br",
        "Mecklenburg-VP":  "mv",
        "Sachsen":         "sn",
        "Sachsen-Anhalt":  "st",
    }

    def _flush(cur: dict, land_name: str) -> dict | None:
        """Turn accumulated ZVG row data into a result dict, or None if over budget."""
        price = cur.get("price")
        title = cur.get("title", f"ZVG {land_name}")
        ort   = cur.get("ort", land_name)
        href  = cur.get("href", "")
        text  = title + " " + ort

        if price is not None and int(price) > MAX_PRICE:
            return None

        flaeche = parse_area(text)

        return {
            "kategorie":  "Grundstück",
            "quelle":     "Zwangsversteigerung",
            "titel":      title[:120],
            "ort":        ort,
            "flaeche_m2": flaeche,
            "preis_eur":  price,
            "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
            "nutzung":    nutzungsidee(title, flaeche),
            "link":       href,
        }

    zvg_url = "https://www.zvg-portal.de/index.php?button=Suchen"
    results = []

    for land, code in bundeslaender.items():
        logger.info("ZVG %s: POST land_abk=%s", land, code)
        try:
            resp = session.post(
                zvg_url,
                data={
                    "land_abk": code,
                    "ger_name": "",
                    "ger_id":   "0",
                    "order_by": "2",
                    "obj_liste": "",
                    "obj_arr":   "",
                },
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("ZVG %s nicht erreichbar: %s", land, e)
            time.sleep(PAUSE_S)
            continue

        # The portal uses ISO-8859-1 encoding
        content = resp.content.decode("latin-1")
        soup    = BeautifulSoup(content, "html.parser")

        # The main data table has border=0 (the border=1 tables are pagination widgets)
        data_table = None
        for t in soup.find_all("table"):
            if t.get("border") == "0":
                data_table = t
                break

        if data_table is None:
            logger.warning("ZVG %s: Datentabelle nicht gefunden", land)
            time.sleep(PAUSE_S)
            continue

        rows = data_table.find_all("tr")
        land_count = 0

        # State machine: accumulate fields across rows until we have a complete entry
        current: dict = {}

        for row in rows:
            try:
                row_text = row.get_text(" ", strip=True)

                # Separator row (colspan=3 with only a <hr>) → flush entry
                if not row_text or (row.find("hr") and len(row.find_all("td")) == 1):
                    if current.get("price") is not None:
                        rec = _flush(current, land)
                        if rec is not None:
                            results.append(rec)
                            land_count += 1
                    current = {}
                    continue

                # Aktenzeichen row: contains the detail link
                if "Aktenzeichen" in row_text:
                    a_el = row.find("a", href=True)
                    if a_el:
                        href = a_el["href"]
                        if href and not href.startswith("http"):
                            href = "https://www.zvg-portal.de/" + href.lstrip("/")
                        current["href"] = href
                    continue

                # Objekt/Lage row: extract object type + address
                if "Objekt/Lage" in row_text:
                    tds = row.find_all("td")
                    if len(tds) >= 2:
                        raw = tds[1].get_text(" ", strip=True)
                        # Format: "Typ: Adresse" – split on colon
                        if ":" in raw:
                            obj_type, _, addr = raw.partition(":")
                            current["title"] = obj_type.strip()
                            current["ort"]   = addr.strip()
                        else:
                            current["title"] = raw[:120]
                    continue

                # Verkehrswert row: extract numeric price
                if "Verkehrswert" in row_text:
                    # Handles: "10.800,00 €", "45.000,- €", "45.000,00 EUR"
                    # Requires German decimal notation XX.XXX,XX (always used on ZVG portal)
                    price_match = re.search(
                        r"(\d[\d.]*,\d{2})", row_text
                    )
                    if price_match:
                        raw_price = price_match.group(1)
                        # Normalize German thousands dot + decimal comma
                        if "," in raw_price:
                            raw_price = raw_price.replace(".", "").replace(",", ".")
                        elif re.search(r"\.\d{3}$", raw_price):
                            raw_price = raw_price.replace(".", "")
                        price = int(float(raw_price))
                        if price < 100:
                            price = None  # implausibly low: treat as parse error
                        current["price"] = price
                    continue

            except Exception as e:
                logger.warning("ZVG %s Parse-Fehler: %s", land, e)
                continue

        # Flush last entry if table ended without a separator
        if current.get("price") is not None:
            rec = _flush(current, land)
            if rec is not None:
                results.append(rec)
                land_count += 1

        logger.info("ZVG %s: %d Einträge nach Filter", land, land_count)
        time.sleep(PAUSE_S)

    logger.info("-> %d ZVG-Einträge gesamt nach Filter", len(results))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPER: CROWDFUNDING / BETEILIGUNGEN
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_rendite(text: str | None) -> float | None:
    """Extrahiert Rendite-Prozentsatz aus Text wie '6,5 % p.a.' oder 'Zinsen: 6.5%'.

    Bevorzugt p.a.-Angaben und Zins/Rendite-Schlüsselwörter gegenüber dem ersten
    Prozentwert im Text (der oft ein Finanzierungsfortschritt wie '52%' ist).
    Werte über 30 % p.a. werden als unrealistisch verworfen (→ None).
    """
    if not text:
        return None
    # Priority 1: explicit p.a. yield
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%\s*p\.?\s*a\.?", text, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    # Priority 2: anchored keyword
    m = re.search(
        r"(?:Zins(?:en|satz)?|Rendite|Verzinsung)\s*[:\s]\s*(\d+[.,]\d+|\d+)\s*%",
        text, re.IGNORECASE
    )
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    # Priority 3: fallback (first %)
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%", text)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    return None


def scrape_bergfuerst(session: requests.Session) -> list[dict]:
    """
    Scrapet aktive Immobilien-Crowdinvestments von Bergfürst.

    Die Seite /investitionsmoeglichkeiten enthält Projekt-Karten als
    .panel-investment divs mit data-href-Attribut. Aktive Angebote
    erkennt man am Ribbon-Text 'Jetzt zeichnen'.
    """
    url = "https://www.bergfuerst.com/investitionsmoeglichkeiten"
    logger.info("Bergfürst: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Bergfürst nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select(".panel-investment")
    if not cards:
        logger.warning("Bergfürst: keine .panel-investment-Karten gefunden (Struktur geändert?)")
        return []

    results = []
    for card in cards:
        try:
            ribbon_el = card.select_one(".tile-ribbon-container")
            ribbon    = ribbon_el.get_text(strip=True) if ribbon_el else ""

            # Nur aktive Angebote (kein Gold-Plan, kein Zurückgezahlt)
            if "Jetzt zeichnen" not in ribbon:
                continue

            title_el = card.select_one(".tile-title")
            loc_el   = card.select_one(".tile-location")
            if not title_el:
                continue

            titel = title_el.get_text(strip=True)
            ort   = loc_el.get_text(strip=True) if loc_el else ""

            text  = card.get_text(" ", strip=True)
            rendite = _parse_rendite(text)
            if rendite is None:
                continue
            if rendite < MIN_RENDITE:
                logger.info("Bergfürst skip (rendite %.2f%% < %.1f%%): %s", rendite, MIN_RENDITE, titel)
                continue

            months_m = re.search(r"(\d+)\s*Monate", text)
            laufzeit = f"{months_m.group(1)} Monate" if months_m else ""

            data_href = card.get("data-href", "")
            if data_href and not data_href.startswith("http"):
                link = "https://www.bergfuerst.com" + data_href
            else:
                link = data_href or url

            results.append({
                "kategorie":     "Beteiligung",
                "plattform":     "Bergfürst",
                "titel":         titel,
                "typ":           "Immobilien",
                "rendite_pct":   rendite,
                "laufzeit":      laufzeit,
                "min_anlage_eur": None,
                "status":        "aktiv",
                "link":          link,
            })
        except Exception as e:
            logger.warning("Bergfürst Parse-Fehler: %s", e)
            continue

    logger.info("-> %d Bergfürst-Angebote nach Filter", len(results))
    return results


def scrape_wiwin(session: requests.Session) -> list[dict]:
    """
    Scrapet aktive Crowdinvestments von Wiwin (wiwin.de/crowdinvesting).

    Die Seite ist WordPress/WP Bakery. Projekt-Karten sind .wpb_wrapper-Divs
    mit einer .kq-product-v3-horizontal-title-Klasse als Titel. Jede Karte
    enthält Verzinsung, Laufzeit, Mindestanlage und einen 'Mehr erfahren'-Link.
    """
    url = "https://wiwin.de/crowdinvesting"
    logger.info("Wiwin: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Wiwin nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    raw_cards = soup.select(".wpb_wrapper")
    if not raw_cards:
        logger.warning("Wiwin: keine .wpb_wrapper-Karten gefunden (Struktur geändert?)")
        return []

    results = []
    seen: set[str] = set()

    for card in raw_cards:
        try:
            title_el = card.select_one(".kq-product-v3-horizontal-title")
            if not title_el:
                continue
            titel = title_el.get_text(strip=True)
            if not titel or titel in seen:
                continue
            seen.add(titel)

            text = card.get_text(" ", strip=True)

            # Rendite aus "Verzinsung X,XX % p. a."
            rendite_m = re.search(r"Verzinsung\s+(\d+[.,]\d+|\d+)\s*%", text)
            rendite = float(rendite_m.group(1).replace(",", ".")) if rendite_m else _parse_rendite(text)
            if rendite is None:
                continue
            if rendite < MIN_RENDITE:
                logger.info("Wiwin skip (rendite %.2f%% < %.1f%%): %s", rendite, MIN_RENDITE, titel)
                continue

            # Laufzeit: Datum hinter "Laufzeit "
            laufzeit_m = re.search(r"Laufzeit\s+([\d.]+)", text)
            laufzeit = laufzeit_m.group(1) if laufzeit_m else ""

            # Mindestanlage: "ab 250,00 €" oder "100 Euro"
            min_m = re.search(
                r"(?:Mindest\w*\s+)?ab\s+(\d[\d.,]*)\s*(?:€|Euro)",
                text, re.IGNORECASE
            )
            min_anlage = None
            if min_m:
                raw_min = min_m.group(1).replace(".", "").replace(",", ".")
                try:
                    min_anlage = int(float(raw_min))
                except ValueError:
                    pass

            a_el = card.find("a", href=True)
            link = a_el["href"] if a_el else url

            # Typ aus Titel (nicht vollem Karten-Text, um Spill-over zu vermeiden):
            # Wind/Solar → Energie, Wohnen/Immobil → Immobilien, sonst allgemein
            low_title = titel.lower()
            if any(k in low_title for k in ["wind", "solar", "energie", "erneuerbar", "repowering"]):
                typ = "Erneuerbare Energien"
            elif any(k in low_title for k in ["immobil", "wohnen", "wohn"]):
                typ = "Immobilien"
            else:
                typ = "Crowdinvesting"

            results.append({
                "kategorie":     "Beteiligung",
                "plattform":     "Wiwin",
                "titel":         titel,
                "typ":           typ,
                "rendite_pct":   rendite,
                "laufzeit":      laufzeit,
                "min_anlage_eur": min_anlage,
                "status":        "aktiv",
                "link":          link,
            })
        except Exception as e:
            logger.warning("Wiwin Parse-Fehler: %s", e)
            continue

    logger.info("-> %d Wiwin-Angebote nach Filter", len(results))
    return results


def scrape_bettervest(session: requests.Session) -> list[dict]:
    """
    Scrapet Crowdinvestments von Bettervest (bettervest.com/de/projekte/).

    Die Seite ist WordPress/Elementor. Zum Zeitpunkt der Implementierung
    zeigt die Projektliste nur Platzhalter-Texte ('Platzhalter Projekt 1 …').
    Echte Projekte werden via Login/JavaScript nachgeladen.
    Fallback: Plattform-Link für manuelle Prüfung.
    """
    url = "https://www.bettervest.com/de/projekte/"
    logger.info("Bettervest: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Bettervest nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    results = []
    # Check whether real project data is present (i.e. rendite percentages
    # appear alongside real names, not placeholder text)
    has_real_projects = (
        re.search(r"\d+[.,]\d+\s*%", body_text)
        and "Platzhalter" not in body_text
    )

    if has_real_projects:
        # Future-proof: try to parse project cards if the site ever returns
        # real HTML listings. For now this branch is not reached.
        cards = soup.select(".elementor-widget-container")
        for card in cards:
            try:
                text = card.get_text(" ", strip=True)
                rendite = _parse_rendite(text)
                if rendite is None or rendite < MIN_RENDITE:
                    continue
                titel = (card.find("h2") or card.find("h3") or card.find("h4"))
                titel = titel.get_text(strip=True) if titel else "Bettervest Projekt"
                a_el  = card.find("a", href=True)
                link  = a_el["href"] if a_el else url
                months_m = re.search(r"(\d+)\s*(?:Monate|Monat)\b", text)
                results.append({
                    "kategorie":     "Beteiligung",
                    "plattform":     "Bettervest",
                    "titel":         titel,
                    "typ":           "PV/Energie",
                    "rendite_pct":   rendite,
                    "laufzeit":      f"{months_m.group(1)} Monate" if months_m else "",
                    "min_anlage_eur": None,
                    "status":        "aktiv",
                    "link":          link,
                })
            except Exception as e:
                logger.warning("Bettervest Parse-Fehler: %s", e)
                continue
        if not results:
            logger.warning("Bettervest: Real-data-Zweig aktiv, aber keine qualifizierenden Projekte gefunden.")
    else:
        # Site only shows placeholder text or requires login for real listings
        logger.warning(
            "Bettervest: Nur Platzhalter-Projekte sichtbar "
            "(Login erforderlich oder keine aktiven Projekte). Fallback-Eintrag."
        )
        results.append({
            "kategorie":     "Beteiligung",
            "plattform":     "Bettervest",
            "titel":         "Manuelle Prüfung empfohlen (JS/Login-Rendering)",
            "typ":           "PV/Energie",
            "rendite_pct":   None,
            "laufzeit":      "",
            "min_anlage_eur": None,
            "status":        "prüfen",
            "link":          url,
        })

    logger.info("-> %d Bettervest-Angebote (inkl. Fallback)", len(results))
    return results


def scrape_exporo(session: requests.Session) -> list[dict]:
    """
    Scrapet Crowdinvestments von Exporo (exporo.de/immobilien).

    Exporo nutzt Webflow als CMS. Die Projekt-Karten werden im statischen HTML
    mit Platzhalter-Werten ('Projekt Standort', '8,0 %', 'Name des Entwicklers')
    ausgeliefert; echte Projekte erscheinen nur nach Login oder via
    JavaScript-Nachladen aus dem Exporo-App-Backend (app.exporo.de).
    Fallback: Link zur Invest-Übersicht für manuelle Prüfung.
    """
    url = "https://exporo.de/immobilien"
    app_url = "https://app.exporo.de"
    logger.info("Exporo: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Exporo nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    results = []
    # Detect real vs placeholder content:
    # Placeholder cards always contain literal "Name des Entwicklers"
    placeholder_marker = "Name des Entwicklers"
    has_real_projects = (
        re.search(r"\d+[.,]\d+\s*%", body_text)
        and placeholder_marker not in body_text
    )

    if has_real_projects:
        # Future-proof: parse Webflow CMS cards if real HTML is ever served
        for card in soup.select("[class*='c-project']"):
            try:
                text = card.get_text(" ", strip=True)
                rendite = _parse_rendite(text)
                if rendite is None or rendite < MIN_RENDITE:
                    continue
                titel_el = card.select_one("[class*='title'], h2, h3")
                titel = titel_el.get_text(strip=True) if titel_el else "Exporo Projekt"
                a_el  = card.find("a", href=True)
                link  = a_el["href"] if a_el else app_url
                laufzeit_m = re.search(r"(\d+)\s*(?:Monate|Monat)\b", text)
                results.append({
                    "kategorie":     "Beteiligung",
                    "plattform":     "Exporo",
                    "titel":         titel,
                    "typ":           "Immobilien",
                    "rendite_pct":   rendite,
                    "laufzeit":      f"{laufzeit_m.group(1)} Monate" if laufzeit_m else "",
                    "min_anlage_eur": None,
                    "status":        "aktiv",
                    "link":          link,
                })
            except Exception as e:
                logger.warning("Exporo Parse-Fehler: %s", e)
                continue
        if not results:
            logger.warning("Exporo: Real-data-Zweig aktiv, aber keine qualifizierenden Projekte gefunden.")
    else:
        logger.warning(
            "Exporo: Nur Platzhalter-Daten im HTML sichtbar "
            "(Webflow/JS-Rendering, Login erforderlich). Fallback-Eintrag."
        )
        results.append({
            "kategorie":     "Beteiligung",
            "plattform":     "Exporo",
            "titel":         "Manuelle Prüfung empfohlen (JS/Login-Rendering)",
            "typ":           "Immobilien",
            "rendite_pct":   None,
            "laufzeit":      "",
            "min_anlage_eur": None,
            "status":        "prüfen",
            "link":          app_url,
        })

    logger.info("-> %d Exporo-Angebote (inkl. Fallback)", len(results))
    return results


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


def _safe_href(url: str) -> str:
    """Gibt url zurück wenn http/https, sonst '#'."""
    return url if url.startswith(("https://", "http://")) else "#"


def _quelle_tag(quelle: str) -> str:
    tags = {
        "Kleinanzeigen":       "tag",
        "DGA Auktion":         "tag2",
        "Zwangsversteigerung": "tag3",
    }
    css = tags.get(quelle, "tag")
    return f'<span class="{css}">{escape(quelle)}</span>'


def _plattform_tag(plattform: str) -> str:
    return f'<span class="tag">{escape(plattform)}</span>'


def build_grundstuecke_table(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Keine Grundstücke gefunden.</div>'
    headers = ["Quelle", "Titel", "Ort", "Fläche", "Preis", "€/m²", "Nutzungsidee", "Link"]
    row_parts = []
    for b in sorted(items, key=lambda x: x.get("preis_eur") or 999_999):
        flaeche = f"{b['flaeche_m2']:,} m²".replace(",", ".") if b.get("flaeche_m2") else "–"
        preis   = f"{b['preis_eur']:,} €".replace(",", ".") if b.get("preis_eur") else "–"
        epm2    = f"{b['eur_pro_m2']:.1f}".replace(".", ",") if b.get("eur_pro_m2") else "–"
        href    = _safe_href(b['link'])
        row_parts.append(f"""<tr>
          <td>{_quelle_tag(b['quelle'])}</td>
          <td><strong>{escape(b['titel'][:80])}</strong></td>
          <td>{escape(b.get('ort', '–'))}</td>
          <td>{flaeche}</td>
          <td>{preis}</td>
          <td>{epm2}</td>
          <td style="color:#555577;font-size:0.82em">{escape(b.get('nutzung', '–'))}</td>
          <td><a href="{href}" target="_blank" rel="noopener noreferrer">→ Inserat</a></td>
        </tr>""")
    rows = "".join(row_parts)
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def build_beteiligungen_table(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Keine Beteiligungen gefunden.</div>'
    headers = ["Plattform", "Projekt", "Typ", "Rendite p.a.", "Laufzeit", "Mind. Anlage", "Status", "Link"]
    row_parts = []
    for b in sorted(items, key=lambda x: -(x.get("rendite_pct") or 0)):
        rendite    = f"{b['rendite_pct']:.1f} %" if b.get("rendite_pct") else "–"
        min_anlage = f"{b['min_anlage_eur']:,} €".replace(",", ".") if b.get("min_anlage_eur") else "–"
        href       = _safe_href(b['link'])
        row_parts.append(f"""<tr>
          <td>{_plattform_tag(b['plattform'])}</td>
          <td><strong>{escape(b['titel'][:80])}</strong></td>
          <td>{escape(b.get('typ', '–'))}</td>
          <td style="color:#1a7a30;font-weight:700">{rendite}</td>
          <td>{escape(b.get('laufzeit', '–'))}</td>
          <td>{min_anlage}</td>
          <td>{escape(b.get('status', '–'))}</td>
          <td><a href="{href}" target="_blank" rel="noopener noreferrer">→ Projekt</a></td>
        </tr>""")
    rows = "".join(row_parts)
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def generate_html(grundstuecke: list[dict], beteiligungen: list[dict],
                  warnings: list[str]) -> str:
    now       = datetime.now()
    date_str  = now.strftime("%d.%m.%Y")
    timestamp = now.strftime("%d.%m.%Y %H:%M")

    preise_m2 = [b["eur_pro_m2"] for b in grundstuecke if b.get("eur_pro_m2")]
    avg_epm2  = f"{sum(preise_m2)/len(preise_m2):.0f} €/m²" if preise_m2 else "–"

    renditen  = [b["rendite_pct"] for b in beteiligungen if b.get("rendite_pct")]
    best_rend = f"{max(renditen):.1f} %" if renditen else "–"

    warn_html = "".join(f'<div class="warn">&#9888;&#65039; {escape(w)}</div>' for w in warnings)

    max_price_fmt   = f"{MAX_PRICE:,}".replace(",", ".")
    min_rendite_fmt = f"{MIN_RENDITE:.1f}".replace(".", ",")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Investment Scanner {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<h1>&#128188; Investment Scanner — {date_str}</h1>

<div class="summary">
  <div class="card"><div class="val">{len(grundstuecke)}</div><div class="lbl">&#127968; Grundstücke</div></div>
  <div class="card"><div class="val">{len(beteiligungen)}</div><div class="lbl">&#128176; Beteiligungen</div></div>
  <div class="card"><div class="val">{avg_epm2}</div><div class="lbl">Ø €/m²</div></div>
  <div class="card"><div class="val">{best_rend}</div><div class="lbl">Beste Rendite</div></div>
</div>

{warn_html}

<h2>&#127968; Grundstücke (max. {max_price_fmt} €)</h2>
{build_grundstuecke_table(grundstuecke)}

<h2>&#128176; Beteiligungen & Crowdfunding (min. {min_rendite_fmt} % p.a.)</h2>
{build_beteiligungen_table(beteiligungen)}

<div class="footer">
  Generiert: {timestamp} &nbsp;|&nbsp;
  Quellen: Kleinanzeigen.de · DGA · ZVG-Portal · Bergfürst · Wiwin · Bettervest · Exporo<br>
  &#9888;&#65039; Diese Übersicht dient ausschließlich zu Informationszwecken. Keine Anlageberatung.
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment Scanner")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Keine externen API-Calls; erzeugt leeren Report für Smoke-Check.",
    )
    return parser.parse_args()


def _dedupe(items: list[dict]) -> list[dict]:
    """Entfernt Duplikate anhand von Link oder (Titel+Ort+Preis)."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        link = (it.get("link") or "").strip().lower()
        if link:
            key = f"link:{link}"
        else:
            title = (it.get("titel") or "").strip().lower()
            ort = (it.get("ort") or "").strip().lower()
            preis = str(it.get("preis_eur") or "")
            key = f"t:{title}|o:{ort}|p:{preis}"
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main() -> int:
    args = parse_args()
    now      = datetime.now()
    print("=" * 60)
    print(f"  Investment Scanner — {now.strftime('%d.%m.%Y %H:%M')}")
    print("=" * 60)

    date_str = now.strftime("%Y-%m-%d")
    out_dir  = OUTPUT_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    warnings = []

    grundstuecke: list[dict] = []
    beteiligungen: list[dict] = []

    if args.dry_run:
        print("[DRY-RUN] Keine externen API-Calls. Erzeuge leeren Report …")
    else:
        with make_session() as session:
            # ── GRUNDSTÜCKE ─────────────────────────────────────────────────
            logger.info("=== Grundstücke ===")

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

            # ── BETEILIGUNGEN ───────────────────────────────────────────────
            logger.info("=== Beteiligungen ===")

            for fn, name in [
                (scrape_bettervest, "Bettervest"),
                (scrape_bergfuerst, "Bergfürst"),
                (scrape_wiwin,      "Wiwin"),
                (scrape_exporo,     "Exporo"),
            ]:
                time.sleep(PAUSE_S)
                r = fn(session)
                beteiligungen.extend(r)
                real_results = [x for x in r if x.get("status") != "prüfen"]
                if not real_results:
                    warnings.append(f"{name}: keine echten Projekte (manuelle Prüfung empfohlen)")

    # ── REPORT ──────────────────────────────────────────────────────────────
    grundstuecke = _dedupe(grundstuecke)
    beteiligungen = _dedupe(beteiligungen)
    logger.info("Grundstücke: %d | Beteiligungen: %d", len(grundstuecke), len(beteiligungen))

    # ── Katalog-Anreicherung (DGA-Objekte mit Expose-Daten) ──────────────
    try:
        from dga_catalog import enrich_dga_properties
        grundstuecke = enrich_dga_properties(grundstuecke)
        logger.info("Katalog-Anreicherung abgeschlossen")
    except ImportError:
        logger.info("dga_catalog nicht verfuegbar — Katalogdaten uebersprungen")
    except Exception as e:
        logger.warning("Katalog-Anreicherung Fehler: %s", e)

    # ── DB-Integration ────────────────────────────────────────────────────
    try:
        from invest_db import init_db, upsert_property, log_scan_run
        init_db()
        all_items = grundstuecke + beteiligungen
        new_count = 0
        for item in all_items:
            # Mapping: DB erwartet link, source, title, location, price, area_m2
            db_record = {
                "link":     item.get("link", ""),
                "source":   item.get("quelle", item.get("plattform", "")),
                "title":    item.get("titel", ""),
                "location": item.get("ort", ""),
                "price":    item.get("preis_eur"),
                "area_m2":  item.get("flaeche_m2"),
            }
            # Zusätzliche DGA-Felder durchreichen
            for key in ("company", "auction_number", "category", "category_code",
                        "status", "rented", "monument", "region", "catalog_text"):
                if key in item:
                    db_record[key] = item[key]
            # Beteiligungsfelder durchreichen
            for key in ("rendite_pct", "laufzeit", "min_anlage_eur", "typ"):
                if key in item:
                    db_record[key] = item[key]
            if upsert_property(db_record):
                new_count += 1
        log_scan_run(len(all_items), new_count)
        logger.info("DB: %d Einträge, davon %d neu", len(all_items), new_count)
    except ImportError:
        logger.warning("invest_db nicht verfügbar — DB-Integration übersprungen")
    except Exception as e:
        logger.warning("DB-Integration Fehler: %s", e)

    html      = generate_html(grundstuecke, beteiligungen, warnings)
    html_path = out_dir / "investments.html"
    try:
        html_path.write_text(html, encoding="utf-8")
        logger.info("HTML: %s", html_path)
    except OSError as e:
        logger.warning("HTML schreiben fehlgeschlagen: %s", e)

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
            "Status":     b.get("status", ""),
            "Link":       b.get("link", ""),
        })

    if rows:
        # Kategorie first, then remaining columns alphabetically
        all_keys   = {k for r in rows for k in r}
        fieldnames = ["Kategorie"] + sorted(all_keys - {"Kategorie"})
        csv_path   = out_dir / "investments.csv"
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            logger.info("CSV:  %s", csv_path)
        except OSError as e:
            logger.warning("CSV schreiben fehlgeschlagen: %s", e)

    print("\n✓ Fertig!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
