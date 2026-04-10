"""Scraper: Bettervest — PV/Energie-Crowdinvestments."""

import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from .base import safe_get, parse_rendite

logger = logging.getLogger(__name__)


def scrape_bettervest(session: requests.Session) -> list[dict]:
    """Scrapet Crowdinvestments von Bettervest. Fallback bei JS-Rendering."""
    url = "https://www.bettervest.com/de/projekte/"
    logger.info("Bettervest: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Bettervest nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    body_text = soup.get_text(" ", strip=True)

    results = []
    has_real_projects = (
        re.search(r"\d+[.,]\d+\s*%", body_text)
        and "Platzhalter" not in body_text
    )

    if has_real_projects:
        cards = soup.select(".elementor-widget-container")
        for card in cards:
            try:
                text = card.get_text(" ", strip=True)
                rendite = parse_rendite(text)
                if rendite is None or rendite < MIN_RENDITE:
                    continue
                titel = (card.find("h2") or card.find("h3") or card.find("h4"))
                titel = titel.get_text(strip=True) if titel else "Bettervest Projekt"
                a_el = card.find("a", href=True)
                link = a_el["href"] if a_el else url
                months_m = re.search(r"(\d+)\s*(?:Monate|Monat)\b", text)
                results.append({
                    "kategorie": "Beteiligung",
                    "plattform": "Bettervest",
                    "titel": titel,
                    "typ": "PV/Energie",
                    "rendite_pct": rendite,
                    "laufzeit": f"{months_m.group(1)} Monate" if months_m else "",
                    "min_anlage_eur": None,
                    "status": "aktiv",
                    "link": link,
                })
            except Exception as e:
                logger.warning("Bettervest Parse-Fehler: %s", e)
                continue
        if not results:
            logger.warning("Bettervest: Real-data-Zweig aktiv, aber keine Projekte gefunden.")
    else:
        logger.warning("Bettervest: Nur Platzhalter sichtbar. Fallback-Eintrag.")
        results.append({
            "kategorie": "Beteiligung",
            "plattform": "Bettervest",
            "titel": "Manuelle Prüfung empfohlen (JS/Login-Rendering)",
            "typ": "PV/Energie",
            "rendite_pct": None,
            "laufzeit": "",
            "min_anlage_eur": None,
            "status": "prüfen",
            "link": url,
        })

    logger.info("-> %d Bettervest-Angebote (inkl. Fallback)", len(results))
    return results
