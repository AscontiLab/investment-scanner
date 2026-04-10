"""Scraper: Bergfuerst — Immobilien-Crowdinvestments."""

import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from .base import safe_get, parse_rendite

logger = logging.getLogger(__name__)


def scrape_bergfuerst(session: requests.Session) -> list[dict]:
    """Scrapet aktive Immobilien-Crowdinvestments von Bergfuerst."""
    url = "https://www.bergfuerst.com/investitionsmoeglichkeiten"
    logger.info("Bergfuerst: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Bergfuerst nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select(".panel-investment")
    if not cards:
        logger.warning("Bergfuerst: keine .panel-investment-Karten gefunden")
        return []

    results = []
    for card in cards:
        try:
            ribbon_el = card.select_one(".tile-ribbon-container")
            ribbon = ribbon_el.get_text(strip=True) if ribbon_el else ""

            if "Jetzt zeichnen" not in ribbon:
                continue

            title_el = card.select_one(".tile-title")
            loc_el = card.select_one(".tile-location")
            if not title_el:
                continue

            titel = title_el.get_text(strip=True)
            ort = loc_el.get_text(strip=True) if loc_el else ""
            text = card.get_text(" ", strip=True)
            rendite = parse_rendite(text)
            if rendite is None or rendite < MIN_RENDITE:
                continue

            months_m = re.search(r"(\d+)\s*Monate", text)
            laufzeit = f"{months_m.group(1)} Monate" if months_m else ""

            data_href = card.get("data-href", "")
            if data_href and not data_href.startswith("http"):
                link = "https://www.bergfuerst.com" + data_href
            else:
                link = data_href or url

            results.append({
                "kategorie": "Beteiligung",
                "plattform": "Bergfürst",
                "titel": titel,
                "typ": "Immobilien",
                "rendite_pct": rendite,
                "laufzeit": laufzeit,
                "min_anlage_eur": None,
                "status": "aktiv",
                "link": link,
            })
        except Exception as e:
            logger.warning("Bergfuerst Parse-Fehler: %s", e)
            continue

    logger.info("-> %d Bergfuerst-Angebote nach Filter", len(results))
    return results
