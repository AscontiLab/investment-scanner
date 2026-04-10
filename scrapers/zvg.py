"""Scraper: Zwangsversteigerungstermine (zvg-portal.de)."""

import re
import time
import logging

import requests
from bs4 import BeautifulSoup

from config import MAX_PRICE, PAUSE_S, ZVG_BUNDESLAENDER
from .base import parse_area, nutzungsidee

logger = logging.getLogger(__name__)


def scrape_zvg(session: requests.Session) -> list[dict]:
    """Scrapet Zwangsversteigerungstermine vom amtlichen ZVG-Portal."""

    def _flush(cur: dict, land_name: str) -> dict | None:
        price = cur.get("price")
        title = cur.get("title", f"ZVG {land_name}")
        ort = cur.get("ort", land_name)
        href = cur.get("href", "")
        text = title + " " + ort

        if price is not None and int(price) > MAX_PRICE:
            return None

        flaeche = parse_area(text)

        return {
            "kategorie": "Grundstück",
            "quelle": "Zwangsversteigerung",
            "titel": title[:120],
            "ort": ort,
            "flaeche_m2": flaeche,
            "preis_eur": price,
            "eur_pro_m2": round(price / flaeche, 2) if price and flaeche else None,
            "nutzung": nutzungsidee(title, flaeche),
            "link": href,
        }

    zvg_url = "https://www.zvg-portal.de/index.php?button=Suchen"
    results = []

    for land, code in ZVG_BUNDESLAENDER.items():
        logger.info("ZVG %s: POST land_abk=%s", land, code)
        try:
            resp = session.post(
                zvg_url,
                data={
                    "land_abk": code,
                    "ger_name": "",
                    "ger_id": "0",
                    "order_by": "2",
                    "obj_liste": "",
                    "obj_arr": "",
                },
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning("ZVG %s nicht erreichbar: %s", land, e)
            time.sleep(PAUSE_S)
            continue

        content = resp.content.decode("latin-1")
        soup = BeautifulSoup(content, "html.parser")

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
        current: dict = {}

        for row in rows:
            try:
                row_text = row.get_text(" ", strip=True)

                if not row_text or (row.find("hr") and len(row.find_all("td")) == 1):
                    if current.get("price") is not None:
                        rec = _flush(current, land)
                        if rec is not None:
                            results.append(rec)
                            land_count += 1
                    current = {}
                    continue

                if "Aktenzeichen" in row_text:
                    a_el = row.find("a", href=True)
                    if a_el:
                        href = a_el["href"]
                        if href and not href.startswith("http"):
                            href = "https://www.zvg-portal.de/" + href.lstrip("/")
                        current["href"] = href
                    continue

                if "Objekt/Lage" in row_text:
                    tds = row.find_all("td")
                    if len(tds) >= 2:
                        raw = tds[1].get_text(" ", strip=True)
                        if ":" in raw:
                            obj_type, _, addr = raw.partition(":")
                            current["title"] = obj_type.strip()
                            current["ort"] = addr.strip()
                        else:
                            current["title"] = raw[:120]
                    continue

                if "Verkehrswert" in row_text:
                    price_match = re.search(r"(\d[\d.]*,\d{2})", row_text)
                    if price_match:
                        raw_price = price_match.group(1)
                        if "," in raw_price:
                            raw_price = raw_price.replace(".", "").replace(",", ".")
                        elif re.search(r"\.\d{3}$", raw_price):
                            raw_price = raw_price.replace(".", "")
                        price = int(float(raw_price))
                        if price < 100:
                            price = None
                        current["price"] = price
                    continue

            except Exception as e:
                logger.warning("ZVG %s Parse-Fehler: %s", land, e)
                continue

        if current.get("price") is not None:
            rec = _flush(current, land)
            if rec is not None:
                results.append(rec)
                land_count += 1

        logger.info("ZVG %s: %d Eintraege nach Filter", land, land_count)
        time.sleep(PAUSE_S)

    logger.info("-> %d ZVG-Eintraege gesamt nach Filter", len(results))
    return results
