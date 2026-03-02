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

_PRICE_RE = re.compile(r"\d+")
_AREA_RE  = re.compile(r"(\d[\d.]*)\s*(?:m²|m2|qm)", re.IGNORECASE)

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


if __name__ == "__main__":
    print("Investment Scanner — Skeleton OK")
