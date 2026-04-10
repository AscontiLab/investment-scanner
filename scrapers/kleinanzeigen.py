"""Scraper: Kleinanzeigen.de — Grundstuecke."""

import time
import logging

import requests
from bs4 import BeautifulSoup

from config import MAX_PRICE, PAUSE_S
from .base import safe_get, in_region, parse_price, parse_area, nutzungsidee

logger = logging.getLogger(__name__)


def scrape_kleinanzeigen(session: requests.Session) -> list[dict]:
    """Scrapet Grundstuecke von Kleinanzeigen.de. Filtert nach Region und Maximalpreis."""
    url = f"https://www.kleinanzeigen.de/s-grundstuecke-garten/preis::{MAX_PRICE}/c207"
    logger.info("Kleinanzeigen: %s", url)
    results = []

    for page in range(1, 4):
        if page > 1:
            time.sleep(PAUSE_S)
        page_url = url if page == 1 else url.replace("/c207", f"/seite:{page}/c207")
        r = safe_get(session, page_url)
        if r is None:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("article.aditem")
        if not items:
            logger.warning("Kleinanzeigen Seite %d: keine Eintraege", page)
            break

        page_count = 0
        for item in items:
            try:
                title_el = item.select_one("a.ellipsis")
                price_el = item.select_one(".aditem-main--middle--price-shipping--price")
                loc_el = item.select_one(".aditem-main--top--left")
                desc_el = item.select_one(".aditem-main--middle--description")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = "https://www.kleinanzeigen.de" + title_el.get("href", "")
                price_raw = price_el.get_text(strip=True) if price_el else ""
                loc_raw = loc_el.get_text(strip=True) if loc_el else ""
                desc_raw = desc_el.get_text(strip=True) if desc_el else ""

                price = parse_price(price_raw)
                if price is not None and price > MAX_PRICE:
                    continue
                if not in_region(loc_raw):
                    continue

                flaeche = parse_area(title + " " + desc_raw)

                results.append({
                    "kategorie": "Grundstück",
                    "quelle": "Kleinanzeigen",
                    "titel": title,
                    "ort": loc_raw,
                    "flaeche_m2": flaeche,
                    "preis_eur": price,
                    "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
                    "nutzung": nutzungsidee(title, flaeche),
                    "link": href,
                })
                page_count += 1
            except Exception as e:
                logger.warning("Kleinanzeigen Parse-Fehler: %s", e)
                continue

        logger.info("Kleinanzeigen Seite %d: %d Eintraege, %d nach Filter", page, len(items), page_count)
        if len(items) < 20:
            break

    logger.info("-> %d Kleinanzeigen-Grundstuecke nach Filter", len(results))
    return results
