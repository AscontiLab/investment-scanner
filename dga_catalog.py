"""DGA Katalog-Extraktor: Laedt Katalog-PDFs und extrahiert Objektdetails."""

import re
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text

logger = logging.getLogger(__name__)

DGA_LOGIN_URL = "https://www.dga-ag.de/login.html"
DGA_USER = "stephan@umzwei.de"
DGA_PASS = "#Stiefel8"

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _get_session() -> requests.Session:
    """Login bei DGA und Session zurueckgeben."""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        lp = session.get(DGA_LOGIN_URL, timeout=15)
        soup = BeautifulSoup(lp.text, "html.parser")
        token_el = soup.find("input", {"name": "__RequestToken"})
        pid_el = soup.find("input", {"name": "pid"})
        if not token_el:
            logger.warning("DGA Login: Kein CSRF-Token gefunden")
            return session
        session.post(DGA_LOGIN_URL, data={
            "user": DGA_USER, "pass": DGA_PASS, "submit": "Anmelden",
            "__RequestToken": token_el["value"],
            "pid": pid_el["value"] if pid_el else "",
            "logintype": "login",
        }, timeout=15)
    except Exception as e:
        logger.warning("DGA Login fehlgeschlagen: %s", e)
    return session


def _download_catalog(session: requests.Session, catalog_url: str) -> Path | None:
    """Katalog-PDF herunterladen und cachen."""
    filename = catalog_url.split("/")[-1].split("#")[0].split("?")[0]
    cache_path = CACHE_DIR / filename
    if cache_path.exists() and cache_path.stat().st_size > 10000:
        return cache_path
    try:
        resp = session.get(catalog_url.split("#")[0], timeout=30)
        if resp.status_code == 200 and len(resp.content) > 10000:
            cache_path.write_bytes(resp.content)
            logger.info("Katalog heruntergeladen: %s (%d bytes)", filename, len(resp.content))
            return cache_path
    except Exception as e:
        logger.warning("Katalog-Download fehlgeschlagen: %s", e)
    return None


def _extract_full_text(pdf_path: Path) -> str:
    """Gesamten Text aus PDF extrahieren."""
    try:
        return extract_text(str(pdf_path))
    except Exception as e:
        logger.warning("PDF-Extraktion fehlgeschlagen: %s", e)
        return ""


def _find_object_text(full_text: str, title: str, auction_number: str = "") -> str:
    """Findet den Textabschnitt fuer ein bestimmtes Objekt im Katalog.

    Strategie: Suche nach Schluesselwoertern aus dem Titel die spezifisch genug sind
    (Ortsname, Strassenname, Nr.-Angabe). Dann extrahiere den Block bis zum naechsten
    Mindestgebot-Eintrag.
    """
    # Spezifische Keywords extrahieren (Ortsnamen, Strassennamen, Nummern)
    stop_words = {"mit", "und", "der", "die", "das", "ein", "eine", "von", "als",
                  "zur", "zum", "dem", "den", "des", "auf", "bei", "nach", "vor",
                  "ohne", "ueber", "unter", "zwischen", "vermietet", "vermietete",
                  "verm", "etw", "mfh", "efh", "grundstueck", "einfamilienhaus",
                  "mehrfamilienhaus", "eigentumswohnung", "wohnhaus", "objekt"}
    keywords = [w for w in title.split() if len(w) > 3 and w.lower() not in stop_words]

    # Suche spezifischste Keywords zuerst (laengere Woerter = spezifischer)
    keywords.sort(key=len, reverse=True)

    best_pos = -1
    for kw in keywords[:5]:
        pos = full_text.find(kw)
        if pos >= 0:
            best_pos = pos
            break

    if best_pos < 0:
        return ""

    # Block extrahieren: ab 50 Zeichen vor Treffer, bis zum naechsten "Mindestgebot"
    start = max(0, best_pos - 50)
    # Suche naechstes "Mindestgebot" nach dem Treffer
    end_marker = full_text.find("Mindestgebot", best_pos + 10)
    if end_marker > 0:
        # Bis zum Ende der Mindestgebot-Zeile
        line_end = full_text.find("\n", end_marker + 10)
        end = line_end if line_end > 0 else end_marker + 100
    else:
        end = min(len(full_text), best_pos + 800)

    return full_text[start:end].strip()


def enrich_dga_properties(properties: list[dict]) -> list[dict]:
    """Reichert DGA-Objekte mit Katalog-Daten an.

    Fuer jedes DGA-Objekt:
    1. Detail-Seite laden (mit Login)
    2. Katalog-URL + Seitenzahl extrahieren
    3. Katalog-PDF herunterladen (gecacht)
    4. Relevanten Textabschnitt finden
    5. Als 'catalog_text' im Dict speichern
    """
    dga_props = [p for p in properties if "dga" in p.get("link", "").lower()]
    if not dga_props:
        return properties

    logger.info("Reichere %d DGA-Objekte mit Katalogdaten an...", len(dga_props))
    session = _get_session()

    # Kataloge cachen (pro Katalog nur 1x laden)
    catalog_texts = {}  # catalog_filename -> full_text

    for prop in dga_props:
        link = prop.get("link", "")
        if not link:
            continue

        try:
            detail = session.get(link, timeout=15)
            soup = BeautifulSoup(detail.text, "html.parser")

            # Katalog-Link finden
            catalog_url = None
            catalog_page = None
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "katalog" in href.lower() and ".pdf" in href.lower():
                    if href.startswith("/"):
                        href = "https://www.dga-ag.de" + href
                    catalog_url = href
                    page_match = re.search(r"#page=(\d+)", href)
                    if page_match:
                        catalog_page = int(page_match.group(1))
                    break

            if not catalog_url:
                continue

            # Katalog-Text laden/cachen
            filename = catalog_url.split("/")[-1].split("#")[0].split("?")[0]
            if filename not in catalog_texts:
                pdf_path = _download_catalog(session, catalog_url)
                if pdf_path:
                    catalog_texts[filename] = _extract_full_text(pdf_path)
                else:
                    catalog_texts[filename] = ""

            full_text = catalog_texts.get(filename, "")
            if not full_text:
                continue

            # Objekttext finden (Titel + Location fuer bessere Suche)
            search_text = prop.get("title", "") + " " + prop.get("ort", "") + " " + prop.get("location", "")
            snippet = _find_object_text(full_text, search_text)
            if snippet:
                prop["catalog_text"] = snippet
                logger.info("  Katalogtext fuer '%s': %d Zeichen", prop.get("title", "")[:30], len(snippet))

        except Exception as e:
            logger.warning("  Fehler bei '%s': %s", prop.get("title", "")[:30], e)

    return properties
