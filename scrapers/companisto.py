"""Scraper: Companisto — Startup-Crowdinvesting."""

import re
import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from .base import safe_get

logger = logging.getLogger(__name__)


def scrape_companisto(session: requests.Session) -> list[dict]:
    """Scrapet aktive Startup-Investments von Companisto."""
    url = "https://www.companisto.com/de/investments"
    logger.info("Companisto: %s", url)
    r = safe_get(session, url)
    if r is None:
        logger.warning("Companisto nicht erreichbar")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/investment/" not in href or href in seen:
            continue
        seen.add(href)

        parent = a.find_parent(["div", "article", "section"])
        if not parent:
            continue

        text = parent.get_text(" ", strip=True)
        if len(text) < 30:
            continue

        # Titel: h3 oder title-wrap (ohne Ort)
        title_el = parent.select_one("h3, h4")
        if not title_el:
            title_el = parent.select_one("[class*=title]")
        titel = title_el.get_text(strip=True) if title_el else ""
        if not titel or len(titel) < 3:
            continue

        # Ort aus dediziertem Element
        loc_el = parent.select_one(".st-location, [class*=location]")
        ort = loc_el.get_text(strip=True) if loc_el else ""

        # Ort aus Titel entfernen falls angeklebt
        if ort and titel.endswith(ort):
            titel = titel[:-len(ort)].strip()

        # Funding-Status
        funding_match = re.search(r"([\d.,]+)\s*€\s*([\d.,]+)\s*€", text)
        funded = None
        target = None
        if funding_match:
            funded_raw = funding_match.group(1).replace(".", "").replace(",", ".")
            target_raw = funding_match.group(2).replace(".", "").replace(",", ".")
            try:
                funded = int(float(funded_raw))
                target = int(float(target_raw))
            except ValueError:
                pass

        # Zugesagt-Betrag (abgeschlossene)
        zugesagt_match = re.search(r"Zugesagt:\s*([\d.,]+)\s*€", text)
        if zugesagt_match and funded is None:
            raw = zugesagt_match.group(1).replace(".", "").replace(",", ".")
            try:
                funded = int(float(raw))
            except ValueError:
                pass

        # Status bestimmen
        if funded and target and funded >= target:
            status = "funded"
        elif "Zugesagt" in text:
            status = "abgeschlossen"
        elif "Fundingziel" in text:
            status = "aktiv"
        else:
            status = "aktiv"

        # Typ
        typ = "Startup"
        low = text.lower()
        if any(k in low for k in ["medtech", "diagnostik", "therapie", "diga"]):
            typ = "MedTech"
        elif any(k in low for k in ["greentech", "energie", "solar", "wasserstoff", "h2"]):
            typ = "GreenTech/Energie"
        elif any(k in low for k in ["food", "muesli", "lebensmittel"]):
            typ = "FoodTech"
        elif any(k in low for k in ["roboter", "autonom", "logistik", "drohne"]):
            typ = "Robotik/Logistik"
        elif any(k in low for k in ["luxusuhren", "handel", "plattform"]):
            typ = "E-Commerce"

        link = href if href.startswith("http") else "https://www.companisto.com" + href

        results.append({
            "kategorie": "Beteiligung",
            "plattform": "Companisto",
            "titel": titel,
            "typ": typ,
            "rendite_pct": None,  # Startup-Investments haben keine feste Rendite
            "laufzeit": "",
            "min_anlage_eur": 250,  # Companisto Minimum
            "status": status,
            "link": link,
            "ort": ort,
        })

    # Nur aktive zurueckgeben
    aktive = [r for r in results if r["status"] == "aktiv"]
    logger.info("-> %d Companisto-Investments (%d aktiv)", len(results), len(aktive))
    return aktive
