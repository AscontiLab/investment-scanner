"""Gemeinsame Hilfsfunktionen fuer alle Scraper."""

import re
import logging

import requests

from config import HEADERS, MAX_PRICE, REGION_RE

logger = logging.getLogger(__name__)

_AREA_RE = re.compile(r"(\d[\d.]*)\s*(?:m²|m2|qm)", re.IGNORECASE)


def make_session() -> requests.Session:
    """Erstellt eine requests.Session mit Browser-Headers."""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def safe_get(session: requests.Session, url: str) -> requests.Response | None:
    """GET mit Timeout und Exception-Handling. Gibt None bei Fehler zurueck."""
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return r
    except requests.HTTPError as e:
        logger.warning("HTTP %s: %s", e.response.status_code if e.response else "?", url)
        return None
    except Exception as e:
        logger.warning("GET %s: %s", url, e)
        return None


def in_region(text: str | None) -> bool:
    """Prueft ob ein Ortstext zu einer der Zielregionen gehoert."""
    return bool(REGION_RE.search(text or ""))


def parse_price(text: str | None) -> int | None:
    """Extrahiert integer Preis aus Text wie '45.000 EUR' oder '45000'."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str | None) -> int | None:
    """Extrahiert integer Flaeche aus Text. Unterstuetzt ha und m2/qm."""
    if not text:
        return None
    ha_match = re.search(r"(\d[\d.,]*)\s*ha\b", text, re.IGNORECASE)
    if ha_match:
        raw = ha_match.group(1)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.search(r"\.\d{3}$", raw):
            raw = raw.replace(".", "")
        return int(float(raw) * 10_000)
    m2_match = _AREA_RE.search(text)
    if m2_match:
        raw = m2_match.group(1)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.search(r"\.\d{3}$", raw):
            raw = raw.replace(".", "")
        return int(float(raw))
    return None


def nutzungsidee(titel: str, flaeche_m2: int | None) -> str:
    """Regelbasierte Nutzungsidee basierend auf Titel-Keywords und Flaeche."""
    if not titel:
        return "Stellplatz, Lagerplatz"
    t = titel.lower()
    f = flaeche_m2 or 0

    if any(k in t for k in ["wald", "forst", "holz"]):
        return "Holzertrag, Erholungswald"
    if any(k in t for k in ["bauland", "baugrundstück", "bauplatz", "wohnbauland"]):
        return "Tiny House, Ferienwohnung, Neubau"
    if any(k in t for k in ["gewerbe", "industrie", "lager"]):
        return "Stellplatz, Lagerplatz, Automatenstandort"
    if any(k in t for k in ["freizeit", "camping", "erholung", "gartenland"]):
        return "Freizeitgrundstück, Camping"
    if any(k in t for k in ["acker", "landwirtschaft", "wiese", "grünland"]):
        if f >= 2000:
            return "PV-Anlage (Pacht/Eigen), Landwirtschaft"
        return "Kleingarten, Freizeitgrundstück"
    if f >= 5000:
        return "PV-Anlage (Pacht/Eigen)"
    if f >= 500:
        return "Kleingarten, Gartennutzung"
    return "Stellplatz, Lagerplatz"


def parse_rendite(text: str | None) -> float | None:
    """Extrahiert Rendite-Prozentsatz aus Text wie '6,5 % p.a.'."""
    if not text:
        return None
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%\s*p\.?\s*a\.?", text, re.IGNORECASE)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    m = re.search(
        r"(?:Zins(?:en|satz)?|Rendite|Verzinsung)\s*[:\s]\s*(\d+[.,]\d+|\d+)\s*%",
        text, re.IGNORECASE,
    )
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    m = re.search(r"(\d+[.,]\d+|\d+)\s*%", text)
    if m:
        val = float(m.group(1).replace(",", "."))
        return val if val <= 30.0 else None
    return None
