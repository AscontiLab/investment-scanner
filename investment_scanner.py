#!/usr/bin/env python3
"""
Investment Opportunity Scanner
───────────────────────────────
Scrapet Grundstücke und Crowdfunding-Beteiligungen für Ostdeutschland.

Quellen Grundstücke:  Kleinanzeigen.de, DGA, Zwangsversteigerungstermine.de
Quellen Crowdfunding: Bettervest, Bergfürst, Wiwin, Exporo
"""

import csv
import json
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

MAX_PRICE   = 50_000   # € Maximalpreis Grundstücke
MIN_RENDITE = 4.0      # % p.a. Mindestrendite Crowdfunding
REGIONS     = ["berlin", "brandenburg", "mecklenburg", "sachsen-anhalt", "sachsen"]

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
    """Prüft ob ein Ortstext zu einer der Zielregionen gehört."""
    if not text:
        return False
    t = text.lower()
    return any(r in t for r in REGIONS)


def parse_price(text: str | None) -> int | None:
    """Extrahiert integer Preis aus Text wie '45.000 €' oder '45000'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str | None) -> int | None:
    """Extrahiert integer Fläche aus Text wie '2.500 m²' oder '2500 qm'."""
    if not text:
        return None
    m = _AREA_RE.search(text)
    if not m:
        return None
    return int(re.sub(r"[^\d]", "", m.group(1)))


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
                # ha hat keine Capture-Group in _AREA_RE → separat prüfen
                flaeche = None
                ha_match = re.search(
                    r"(\d[\d.,]*)\s*ha\b", title + " " + desc_raw, re.IGNORECASE
                )
                if ha_match:
                    raw = ha_match.group(1)
                    # Normalize German number formats to float:
                    # "1,5" (comma=decimal) → 1.5
                    # "1.500" (dot=thousands sep, 3 trailing digits) → 1500.0
                    # "2.5" (dot=decimal, <3 trailing digits) → 2.5
                    if "," in raw:
                        raw = raw.replace(".", "").replace(",", ".")
                    elif re.search(r"\.\d{3}$", raw):
                        raw = raw.replace(".", "")
                    flaeche = int(float(raw) * 10_000)
                else:
                    area_match = _AREA_RE.search(title + " " + desc_raw)
                    if area_match:
                        raw_m2 = area_match.group(1)
                        if "," in raw_m2:
                            raw_m2 = raw_m2.replace(".", "").replace(",", ".")
                        elif re.search(r"\.\d{3}$", raw_m2):
                            raw_m2 = raw_m2.replace(".", "")
                        flaeche = int(float(raw_m2))

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
    Jeder Eintrag enthält ein 'filter'-Objekt mit region, limit, category sowie
    ein 'infoWindow'-HTML-Schnipsel mit Titel, Adresse und Objekt-Link.
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

    # East-German region identifiers as used in the filter.region field
    east_regions = {
        "berlin", "brandenburg", "mecklenburg-vorpommern",
        "sachsen", "sachsen-anhalt",
    }

    results = []
    for entry in locations:
        try:
            f       = entry.get("filter", {})
            region  = str(f.get("region", "")).lower()
            limit   = f.get("limit")          # auction limit in EUR (int)
            status  = str(f.get("status", "")).lower()

            # Only active, in-region, within budget
            if status not in ("aktuell", ""):
                continue
            if not any(r in region for r in east_regions):
                continue
            if limit is not None and int(limit) > MAX_PRICE:
                continue

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

            flaeche = None
            ha_match = re.search(r"(\d[\d.,]*)\s*ha\b", full_text, re.IGNORECASE)
            if ha_match:
                raw = ha_match.group(1)
                if "," in raw:
                    raw = raw.replace(".", "").replace(",", ".")
                elif re.search(r"\.\d{3}$", raw):
                    raw = raw.replace(".", "")
                flaeche = int(float(raw) * 10_000)
            else:
                area_match = _AREA_RE.search(full_text)
                if area_match:
                    raw_m2 = area_match.group(1)
                    if "," in raw_m2:
                        raw_m2 = raw_m2.replace(".", "").replace(",", ".")
                    elif re.search(r"\.\d{3}$", raw_m2):
                        raw_m2 = raw_m2.replace(".", "")
                    flaeche = int(float(raw_m2))

            price = int(limit) if limit is not None else None

            results.append({
                "kategorie":  "Grundstück",
                "quelle":     "DGA Auktion",
                "titel":      title,
                "ort":        ort,
                "flaeche_m2": flaeche,
                "preis_eur":  price,
                "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
                "nutzung":    nutzungsidee(title, flaeche),
                "link":       href or url,
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

        flaeche = None
        ha_match = re.search(r"(\d[\d.,]*)\s*ha\b", text, re.IGNORECASE)
        if ha_match:
            raw = ha_match.group(1)
            if "," in raw:
                raw = raw.replace(".", "").replace(",", ".")
            elif re.search(r"\.\d{3}$", raw):
                raw = raw.replace(".", "")
            flaeche = int(float(raw) * 10_000)
        else:
            area_match = _AREA_RE.search(text)
            if area_match:
                raw_m2 = area_match.group(1)
                if "," in raw_m2:
                    raw_m2 = raw_m2.replace(".", "").replace(",", ".")
                elif re.search(r"\.\d{3}$", raw_m2):
                    raw_m2 = raw_m2.replace(".", "")
                flaeche = int(float(raw_m2))

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
                    # Handles: "10.800,00 €", "45.000,-", "45000 EUR", "45.000"
                    price_match = re.search(
                        r"(\d[\d.]*(?:,\d{1,2})?)\s*(?:EUR|€|-\s|$)", row_text
                    )
                    if price_match:
                        raw_price = price_match.group(1)
                        # Normalize German thousands dot + decimal comma
                        if "," in raw_price:
                            raw_price = raw_price.replace(".", "").replace(",", ".")
                        elif re.search(r"\.\d{3}$", raw_price):
                            raw_price = raw_price.replace(".", "")
                        current["price"] = int(float(raw_price))
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


if __name__ == "__main__":
    print("Investment Scanner — Skeleton OK")
