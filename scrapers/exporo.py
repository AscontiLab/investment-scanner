"""Scraper: Exporo — Immobilien-Crowdinvestments (Flutter/GraphQL)."""

import logging

import requests
from bs4 import BeautifulSoup

from config import MIN_RENDITE
from scanner_common import load_credentials

logger = logging.getLogger(__name__)


def _scrape_via_playwright() -> list[dict]:
    """Login per Playwright, Projekte via GraphQL abfangen."""
    creds = load_credentials()
    user = creds.get("EXPORO_USER", "")
    pw = creds.get("EXPORO_PASS", "")
    if not user or not pw:
        logger.warning("Exporo: EXPORO_USER/EXPORO_PASS nicht konfiguriert")
        return []

    from playwright.sync_api import sync_playwright

    projects = []

    def on_response(response):
        if "graphql" not in response.url:
            return
        try:
            data = response.json().get("data", {})
            items = data.get("getPublicPDPList", [])
            if items:
                projects.extend(items)
        except Exception:
            pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.on("response", on_response)

            # Login
            page.goto("https://app.exporo.de/login", timeout=20000)
            page.wait_for_timeout(4000)

            page.mouse.click(640, 280)
            page.wait_for_timeout(300)
            page.keyboard.type(user, delay=20)
            page.mouse.click(640, 390)
            page.wait_for_timeout(300)
            page.keyboard.type(pw, delay=20)
            page.mouse.click(640, 585)
            page.wait_for_timeout(6000)

            if "login" in page.url:
                logger.warning("Exporo: Login fehlgeschlagen")
                browser.close()
                return []

            logger.info("Exporo: Login erfolgreich")

            # INVESTIEREN klicken (Nav links, y=430)
            page.mouse.click(60, 430)
            page.wait_for_timeout(5000)

            browser.close()
    except Exception as e:
        logger.warning("Exporo Playwright-Fehler: %s", e)
        return []

    return projects


def scrape_exporo(session: requests.Session) -> list[dict]:
    """Scrapet Crowdinvestments von Exporo via Playwright + GraphQL."""
    app_url = "https://app.exporo.de"
    logger.info("Exporo: Playwright-Login + GraphQL")

    raw_projects = _scrape_via_playwright()

    if not raw_projects:
        logger.warning("Exporo: Keine Projekte gefunden. Fallback-Eintrag.")
        return [{
            "kategorie": "Beteiligung",
            "plattform": "Exporo",
            "titel": "Manuelle Prüfung empfohlen (Login/Rendering)",
            "typ": "Immobilien",
            "rendite_pct": None,
            "laufzeit": "",
            "min_anlage_eur": None,
            "status": "prüfen",
            "link": app_url,
        }]

    results = []
    for proj in raw_projects:
        try:
            rendite = proj.get("interestRate")
            if rendite is not None:
                rendite = float(rendite)
            if rendite is None or rendite < MIN_RENDITE:
                continue

            titel = proj.get("title") or proj.get("name") or "Exporo Projekt"
            location = proj.get("location") or ""
            duration = proj.get("durationInMonths")
            laufzeit = f"{duration} Monate" if duration else ""
            min_invest = proj.get("minInvestmentAmount")
            funded_pct = proj.get("fundedPercentage")
            fp_id = proj.get("financialProductId") or ""
            link = f"{app_url}/project/{fp_id}" if fp_id else app_url

            typ = proj.get("classOrUsage") or "Immobilien"

            status = "aktiv"
            if funded_pct is not None and funded_pct >= 100:
                status = "voll"

            results.append({
                "kategorie": "Beteiligung",
                "plattform": "Exporo",
                "titel": titel,
                "typ": typ,
                "rendite_pct": rendite,
                "laufzeit": laufzeit,
                "min_anlage_eur": int(min_invest) if min_invest else None,
                "status": status,
                "link": link,
                "ort": location,
            })
        except Exception as e:
            logger.warning("Exporo Parse-Fehler: %s", e)
            continue

    logger.info("-> %d Exporo-Angebote nach Filter", len(results))
    return results
