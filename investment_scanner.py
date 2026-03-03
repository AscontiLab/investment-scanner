#!/usr/bin/env python3
"""
Investment Opportunity Scanner
───────────────────────────────
Scrapet Grundstücke und Crowdfunding-Beteiligungen für Ostdeutschland.

Quellen Grundstücke:  Kleinanzeigen.de, DGA, Zwangsversteigerungstermine.de
Quellen Crowdfunding: Bettervest, Bergfürst, Wiwin, Exporo
"""

import csv
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


if __name__ == "__main__":
    print("Investment Scanner — Skeleton OK")
