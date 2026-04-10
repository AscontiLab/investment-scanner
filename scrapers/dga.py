"""Scraper: Deutsche Grundstuecksauktionen AG (dga-ag.de)."""

import json
import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MAX_PRICE, DGA_COMPANIES, DGA_CATEGORIES
from .base import safe_get, parse_area, nutzungsidee

logger = logging.getLogger(__name__)


def scrape_dga(session: requests.Session) -> list[dict]:
    """Scrapet Grundstueck-Auktionen von DGA. Embedded JSON in 'var locations'."""
    url = "https://www.dga-ag.de/immobilie-ersteigern/immobilie-suchen-und-finden.html"
    logger.info("DGA-AG: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("DGA-AG nicht erreichbar")
        return []

    m = re.search(r"var locations = (\[.*?\]);", r.text, re.DOTALL)
    if not m:
        logger.warning("DGA-AG: JSON 'var locations' nicht gefunden")
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
            f = entry.get("filter", {})
            limit = f.get("limit")
            status = str(f.get("status", "")).lower()

            if status not in allowed_statuses:
                continue
            if status != "nachverkauf" and limit is not None and int(limit) > MAX_PRICE:
                continue

            company_code = str(f.get("company", "D"))
            company_name = DGA_COMPANIES.get(company_code, "DGA")
            category_code = str(f.get("category", ""))
            category = DGA_CATEGORIES.get(category_code, category_code)
            auction_number = str(f.get("auctionNumber", ""))
            rented = str(f.get("rentedOrLeased", ""))
            monument = str(f.get("protectedAsAHistoricMonument", ""))
            region = str(f.get("region", ""))

            status_label = "Nachverkauf" if status == "nachverkauf" else "Auktion"
            quelle = f"{company_name} {status_label}"

            iw_soup = BeautifulSoup(entry.get("infoWindow", ""), "html.parser")
            title = iw_soup.find("h2")
            title = title.get_text(strip=True)[:120] if title else ""
            if not title:
                continue
            a_el = iw_soup.find("a", href=True)
            href = a_el["href"] if a_el else ""
            if href and not href.startswith("http"):
                href = "https://www.dga-ag.de" + href

            gmap_text = iw_soup.select_one(".gmap-text")
            ort = ""
            if gmap_text:
                paras = gmap_text.find_all("p")
                ort = " ".join(p.get_text(strip=True) for p in paras[:2])

            full_text = title + " " + ort
            flaeche = parse_area(full_text)
            price = int(limit) if limit is not None else None

            results.append({
                "kategorie": "Grundstück",
                "quelle": quelle,
                "titel": title,
                "ort": ort,
                "flaeche_m2": flaeche,
                "preis_eur": price,
                "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
                "nutzung": nutzungsidee(title, flaeche),
                "link": href or url,
                "company": company_code,
                "auction_number": auction_number,
                "category": category,
                "category_code": category_code,
                "status": status,
                "rented": rented,
                "monument": monument,
                "region": region,
            })
        except Exception as e:
            logger.warning("DGA-AG Parse-Fehler: %s", e)
            continue

    logger.info("-> %d DGA-Auktionen nach Filter", len(results))
    return results
