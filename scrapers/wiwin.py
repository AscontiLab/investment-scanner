"""Scraper: Wiwin — Crowdinvestments (Energie + Immobilien)."""

import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from .base import safe_get, parse_rendite

logger = logging.getLogger(__name__)


def scrape_wiwin(session: requests.Session) -> list[dict]:
    """Scrapet aktive Crowdinvestments von Wiwin."""
    url = "https://wiwin.de/crowdinvesting"
    logger.info("Wiwin: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Wiwin nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    raw_cards = soup.select(".wpb_wrapper")
    if not raw_cards:
        logger.warning("Wiwin: keine .wpb_wrapper-Karten gefunden")
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

            rendite_m = re.search(r"Verzinsung\s+(\d+[.,]\d+|\d+)\s*%", text)
            rendite = float(rendite_m.group(1).replace(",", ".")) if rendite_m else parse_rendite(text)
            if rendite is None or rendite < MIN_RENDITE:
                continue

            laufzeit_m = re.search(r"Laufzeit\s+([\d.]+)", text)
            laufzeit = laufzeit_m.group(1) if laufzeit_m else ""

            min_m = re.search(
                r"(?:Mindest\w*\s+)?ab\s+(\d[\d.,]*)\s*(?:€|Euro)",
                text, re.IGNORECASE,
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

            low_title = titel.lower()
            if any(k in low_title for k in ["wind", "solar", "energie", "erneuerbar", "repowering"]):
                typ = "Erneuerbare Energien"
            elif any(k in low_title for k in ["immobil", "wohnen", "wohn"]):
                typ = "Immobilien"
            else:
                typ = "Crowdinvesting"

            results.append({
                "kategorie": "Beteiligung",
                "plattform": "Wiwin",
                "titel": titel,
                "typ": typ,
                "rendite_pct": rendite,
                "laufzeit": laufzeit,
                "min_anlage_eur": min_anlage,
                "status": "aktiv",
                "link": link,
            })
        except Exception as e:
            logger.warning("Wiwin Parse-Fehler: %s", e)
            continue

    logger.info("-> %d Wiwin-Angebote nach Filter", len(results))
    return results
