"""Scraper: Exporo — Immobilien-Crowdinvestments (Webflow)."""

import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from .base import safe_get, parse_rendite

logger = logging.getLogger(__name__)


def scrape_exporo(session: requests.Session) -> list[dict]:
    """Scrapet Crowdinvestments von Exporo. Fallback bei JS-Rendering."""
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
    placeholder_marker = "Name des Entwicklers"
    has_real_projects = (
        re.search(r"\d+[.,]\d+\s*%", body_text)
        and placeholder_marker not in body_text
    )

    if has_real_projects:
        for card in soup.select("[class*='c-project']"):
            try:
                text = card.get_text(" ", strip=True)
                rendite = parse_rendite(text)
                if rendite is None or rendite < MIN_RENDITE:
                    continue
                titel_el = card.select_one("[class*='title'], h2, h3")
                titel = titel_el.get_text(strip=True) if titel_el else "Exporo Projekt"
                a_el = card.find("a", href=True)
                link = a_el["href"] if a_el else app_url
                laufzeit_m = re.search(r"(\d+)\s*(?:Monate|Monat)\b", text)
                results.append({
                    "kategorie": "Beteiligung",
                    "plattform": "Exporo",
                    "titel": titel,
                    "typ": "Immobilien",
                    "rendite_pct": rendite,
                    "laufzeit": f"{laufzeit_m.group(1)} Monate" if laufzeit_m else "",
                    "min_anlage_eur": None,
                    "status": "aktiv",
                    "link": link,
                })
            except Exception as e:
                logger.warning("Exporo Parse-Fehler: %s", e)
                continue
        if not results:
            logger.warning("Exporo: Real-data-Zweig aktiv, aber keine Projekte gefunden.")
    else:
        logger.warning("Exporo: Nur Platzhalter-Daten sichtbar. Fallback-Eintrag.")
        results.append({
            "kategorie": "Beteiligung",
            "plattform": "Exporo",
            "titel": "Manuelle Prüfung empfohlen (JS/Login-Rendering)",
            "typ": "Immobilien",
            "rendite_pct": None,
            "laufzeit": "",
            "min_anlage_eur": None,
            "status": "prüfen",
            "link": app_url,
        })

    logger.info("-> %d Exporo-Angebote (inkl. Fallback)", len(results))
    return results
