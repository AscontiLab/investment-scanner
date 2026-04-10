#!/usr/bin/env python3
"""
Deep Scoring — Stufe 2 der KI-Bewertung.
Laedt Objektunterlagen (Expose, Gutachten, Detail-Seiten) und bewertet neu.
Modell-Strategie: Gemma (Standard) oder Claude (bei grossen/komplexen Objekten).
"""

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text

from config import (
    DEEP_BATCH_SIZE,
    DEEP_CLAUDE_CATEGORIES,
    DEEP_CLAUDE_MODEL,
    DEEP_MAX_TEXT_CLAUDE,
    DEEP_MAX_TEXT_GEMMA,
    DEEP_MIN_KI_SCORE,
    DEEP_MODEL_STRATEGY,
    DEEP_NUM_PREDICT_GEMMA,
    OLLAMA_PAUSE,
    OLLAMA_TIMEOUT,
    OLLAMA_URL,
    OLLAMA_MODEL,
    PAUSE_S,
)
from invest_db import (
    get_deep_score_candidates,
    get_property_by_link,
    save_deep_score,
)
from scanner_common import load_credentials

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache" / "deep"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_PDF_SIZE = 20 * 1024 * 1024  # 20 MB

DEEP_SYSTEM_PROMPT = """\
Du bist ein erfahrener Immobilien-Analyst und fuehrst eine DETAILLIERTE Bewertung durch.
Dir liegen die Objektunterlagen vor (Expose, Gutachten, Bekanntmachung).

Bewerte das Objekt auf einer Skala von 0 bis 10:
- 0-2: Unattraktiv (zu teuer, schlechte Lage, hohe Risiken)
- 3-4: Unterdurchschnittlich (einige Nachteile ueberwiegen)
- 5-6: Durchschnittlich (solide, aber kein Schnaeppchen)
- 7-8: Attraktiv (guter Preis, gute Lage, Potenzial)
- 9-10: Top-Deal (herausragendes Preis-Leistungs-Verhaeltnis)

Achte besonders auf:
- Preis pro m2 im Vergleich zur Region
- Zustand und Sanierungsbedarf (aus Gutachten/Expose)
- Rechtliche Belastungen (Grundbuch, Dienstbarkeiten, Wegerechte)
- Altlasten, Umweltrisiken, Denkmalschutz
- Mietverhaeltnisse und Leerstand
- Erschliessung und Infrastruktur
- Entwicklungspotenzial der Region

Antworte AUSSCHLIESSLICH als valides JSON ohne Markdown-Formatierung:
{
  "score": 7.5,
  "headline": "Kurze praegnante Bewertung in einem Satz",
  "analysis": "3-5 Saetze detaillierte Analyse mit Bezug auf die Dokumente",
  "strengths": ["Staerke 1", "Staerke 2"],
  "weaknesses": ["Schwaeche 1", "Schwaeche 2"],
  "risks_from_documents": ["Konkretes Risiko aus den Unterlagen"],
  "recommendation": "Handlungsempfehlung in 1-2 Saetzen",
  "risk": "niedrig",
  "document_quality": "gut"
}

"risk": "niedrig" | "mittel" | "hoch"
"document_quality": "gut" (ausfuehrlich) | "mittel" (grundlegend) | "schlecht" (kaum Info)
"score": Zahl 0-10 (Dezimalzahlen erlaubt)\
"""


# ═══════════════════════════════════════════════════════════════════════════════
# PDF-DOWNLOAD + TEXT-EXTRAKTION
# ═══════════════════════════════════════════════════════════════════════════════

def _download_pdf(session: requests.Session, url: str, prefix: str = "") -> Path | None:
    """PDF herunterladen und cachen."""
    filename = re.sub(r"[^\w.\-]", "_", url.split("/")[-1].split("#")[0].split("?")[0])
    if prefix:
        filename = f"{prefix}_{filename}"
    cache_path = CACHE_DIR / filename
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        return cache_path
    try:
        resp = session.get(url.split("#")[0], timeout=30, stream=True)
        if resp.status_code != 200:
            return None
        size = int(resp.headers.get("content-length", 0))
        if size > MAX_PDF_SIZE:
            logger.warning("PDF zu gross (%d MB): %s", size // (1024*1024), url)
            return None
        content = resp.content
        if len(content) < 1000:
            return None
        cache_path.write_bytes(content)
        logger.info("PDF heruntergeladen: %s (%d KB)", filename, len(content) // 1024)
        return cache_path
    except Exception as e:
        logger.warning("PDF-Download fehlgeschlagen: %s — %s", url, e)
        return None


def _extract_pdf_text(pdf_path: Path) -> str:
    """Text aus PDF extrahieren."""
    try:
        return extract_text(str(pdf_path))
    except Exception as e:
        logger.warning("PDF-Extraktion fehlgeschlagen (%s): %s", pdf_path.name, e)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# DETAIL-FETCHER PRO QUELLE
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_dga_detail(prop: dict, session: requests.Session) -> str:
    """DGA: Detail-Seite + Expose/Gutachten-PDFs laden."""
    link = prop.get("link", "")
    if not link:
        return ""

    # Authentifizierte Session fuer DGA
    from dga_catalog import _get_session
    dga_session = _get_session()

    parts = []

    try:
        detail = dga_session.get(link, timeout=15)
        soup = BeautifulSoup(detail.text, "html.parser")

        # HTML-Beschreibungstext extrahieren
        desc_sections = soup.select(".ce-bodytext, .csc-default, .tx-dga-detail")
        for sec in desc_sections:
            text = sec.get_text(" ", strip=True)
            if len(text) > 50:
                parts.append(text)

        # Alle PDF-Links sammeln (Expose, Gutachten, Katalog)
        pdf_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            link_text = a.get_text(strip=True).lower()
            if ".pdf" in href.lower():
                if href.startswith("/"):
                    href = "https://www.dga-ag.de" + href
                label = "expose" if "expos" in link_text else \
                        "gutachten" if "gutacht" in link_text else \
                        "katalog" if "katalog" in link_text else "doc"
                pdf_links.append((href, label))

        # PDFs herunterladen und Text extrahieren
        for pdf_url, label in pdf_links:
            pdf_path = _download_pdf(dga_session, pdf_url, prefix=f"dga_{label}")
            if pdf_path:
                pdf_text = _extract_pdf_text(pdf_path)
                if len(pdf_text) > 100:
                    parts.append(f"--- {label.upper()} ---\n{pdf_text}")

    except Exception as e:
        logger.warning("DGA Detail-Fehler (%s): %s", link[:60], e)

    return "\n\n".join(parts)


def _fetch_zvg_detail(prop: dict, session: requests.Session) -> str:
    """ZVG: Bekanntmachungstext + ggf. Gutachten-PDF."""
    link = prop.get("link", "")
    if not link:
        return ""

    parts = []

    try:
        resp = session.get(link, timeout=20)
        content = resp.content.decode("latin-1")
        soup = BeautifulSoup(content, "html.parser")

        # Bekanntmachungstext extrahieren (Haupttabelle)
        tables = soup.find_all("table")
        for table in tables:
            text = table.get_text(" ", strip=True)
            if len(text) > 200 and any(kw in text for kw in
                    ["Verkehrswert", "Grundbuch", "Objekt", "Versteigerung"]):
                parts.append(text)
                break

        # PDF-Links suchen (Bekanntmachung, Gutachten)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower():
                if not href.startswith("http"):
                    href = "https://www.zvg-portal.de/" + href.lstrip("/")
                pdf_path = _download_pdf(session, href, prefix="zvg")
                if pdf_path:
                    pdf_text = _extract_pdf_text(pdf_path)
                    if len(pdf_text) > 100:
                        parts.append(f"--- BEKANNTMACHUNG/GUTACHTEN ---\n{pdf_text}")

    except Exception as e:
        logger.warning("ZVG Detail-Fehler (%s): %s", link[:60], e)

    return "\n\n".join(parts)


def _fetch_kleinanzeigen_detail(prop: dict, session: requests.Session) -> str:
    """Kleinanzeigen: Volle Beschreibung von der Detail-Seite."""
    link = prop.get("link", "")
    if not link:
        return ""

    try:
        resp = session.get(link, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")

        parts = []

        # Beschreibungstext
        desc = soup.select_one("#viewad-description-text")
        if desc:
            parts.append(desc.get_text("\n", strip=True))

        # Attribute (Grundstuecksflaeche, Wohnflaeche etc.)
        attrs = soup.select("#viewad-details .addetailslist--detail")
        for attr in attrs:
            parts.append(attr.get_text(" ", strip=True))

        return "\n".join(parts)

    except Exception as e:
        logger.warning("Kleinanzeigen Detail-Fehler (%s): %s", link[:60], e)
        return ""


def fetch_detail_text(prop: dict, session: requests.Session) -> str:
    """Dispatcht zum richtigen Fetcher basierend auf der Quelle."""
    source = (prop.get("source") or "").lower()
    link = (prop.get("link") or "").lower()

    if "dga" in source or "dga" in link:
        return _fetch_dga_detail(prop, session)
    elif "zwangsversteigerung" in source or "zvg" in link:
        return _fetch_zvg_detail(prop, session)
    elif "kleinanzeigen" in source or "kleinanzeigen" in link:
        return _fetch_kleinanzeigen_detail(prop, session)
    else:
        logger.info("Kein Detail-Fetcher fuer Quelle '%s'", source)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# MODELL-AUSWAHL + SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def _should_use_claude(prop: dict, text_length: int) -> bool:
    """Entscheidet ob Claude statt Gemma verwendet werden soll."""
    if DEEP_MODEL_STRATEGY == "gemma":
        return False
    if DEEP_MODEL_STRATEGY == "claude":
        return True

    # auto: Claude bei grossen Dokumenten oder komplexen Kategorien
    if text_length > DEEP_MAX_TEXT_GEMMA:
        return True
    category = prop.get("category") or ""
    if category in DEEP_CLAUDE_CATEGORIES:
        return True
    return False


def _call_gemma(user_prompt: str) -> dict | None:
    """Scoring via Ollama/Gemma."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": DEEP_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"num_predict": DEEP_NUM_PREDICT_GEMMA},
    }

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Deep] Ollama-Fehler: {e}")
        return None

    content = resp.json().get("message", {}).get("content", "").strip()
    return _parse_json_response(content)


def _call_claude(user_prompt: str) -> dict | None:
    """Scoring via Claude API."""
    creds = load_credentials()
    api_key = creds.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [Deep] Kein ANTHROPIC_API_KEY — Fallback auf Gemma")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=DEEP_CLAUDE_MODEL,
            max_tokens=1024,
            system=DEEP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        return _parse_json_response(content)
    except Exception as e:
        print(f"  [Deep] Claude-Fehler: {e}")
        return None


def _parse_json_response(content: str) -> dict | None:
    """JSON aus Modell-Antwort parsen (mit Markdown-Cleanup)."""
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Deep Score JSON-Parse-Fehler: %s", content[:200])
        return None


def _build_deep_prompt(prop: dict, detail_text: str) -> str:
    """Erstellt den Deep-Scoring-Prompt mit allen verfuegbaren Daten."""
    parts = ["Fuehre eine detaillierte Bewertung dieses Immobilien-Objekts durch:\n"]

    if prop.get("title"):
        parts.append(f"Titel: {prop['title']}")
    if prop.get("location"):
        parts.append(f"Standort: {prop['location']}")
    if prop.get("region"):
        parts.append(f"Region: {prop['region']}")
    if prop.get("price"):
        parts.append(f"Preis: {prop['price']:,.0f} EUR".replace(",", "."))
    if prop.get("area_m2"):
        parts.append(f"Flaeche: {prop['area_m2']} m2")
    if prop.get("price_per_m2"):
        parts.append(f"Preis pro m2: {prop['price_per_m2']:.2f} EUR")
    if prop.get("source"):
        parts.append(f"Quelle: {prop['source']}")
    if prop.get("category"):
        parts.append(f"Kategorie: {prop['category']}")
    if prop.get("status"):
        parts.append(f"Status: {prop['status']}")
    if prop.get("rented"):
        parts.append(f"Vermietet: {prop['rented']}")
    if prop.get("monument"):
        parts.append(f"Denkmalschutz: {prop['monument']}")

    # Erste KI-Bewertung als Kontext
    if prop.get("ki_score") is not None:
        parts.append(f"\nErste KI-Bewertung: {prop['ki_score']:.1f}/10")
    if prop.get("ki_headline"):
        parts.append(f"Erste Einschaetzung: {prop['ki_headline']}")

    # Detail-Text (das Herzstück)
    if detail_text:
        parts.append(f"\n{'='*40}")
        parts.append("OBJEKTUNTERLAGEN (Expose/Gutachten/Bekanntmachung):")
        parts.append(f"{'='*40}")
        parts.append(detail_text)

    return "\n".join(parts)


def _validate_deep_result(result: dict) -> dict | None:
    """Validiert und normalisiert das Deep-Score-Ergebnis."""
    try:
        score = float(result.get("score", -1))
        if not 0 <= score <= 10:
            return None
    except (ValueError, TypeError):
        return None

    risk = str(result.get("risk", "mittel")).lower().strip()
    if risk not in ("niedrig", "mittel", "hoch"):
        risk = "mittel"

    return {
        "score": score,
        "headline": str(result.get("headline", ""))[:500],
        "analysis": str(result.get("analysis", ""))[:3000],
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "risks_from_documents": result.get("risks_from_documents", []),
        "recommendation": str(result.get("recommendation", ""))[:500],
        "risk": risk,
        "document_quality": str(result.get("document_quality", "mittel")),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HAUPT-FUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def deep_score_property(prop: dict, session: requests.Session) -> dict | None:
    """Deep-Scoring fuer ein einzelnes Objekt. Gibt validiertes Ergebnis zurueck."""
    title = (prop.get("title") or "Unbekannt")[:50]
    link = prop.get("link", "")

    # Detail-Text laden
    detail_text = fetch_detail_text(prop, session)
    if len(detail_text) < 100:
        print(f"  [Deep] Zu wenig Dokumenten-Text ({len(detail_text)} Zeichen): {title}")
        return None

    # Modell waehlen
    use_claude = _should_use_claude(prop, len(detail_text))
    model_name = "Claude" if use_claude else "Gemma"

    # Text kuerzen je nach Modell
    max_text = DEEP_MAX_TEXT_CLAUDE if use_claude else DEEP_MAX_TEXT_GEMMA
    if len(detail_text) > max_text:
        detail_text = detail_text[:max_text] + "\n\n[... Text gekuerzt ...]"

    # Prompt bauen
    user_prompt = _build_deep_prompt(prop, detail_text)

    # Scoring
    print(f"  [Deep] {model_name}: {title} ({len(detail_text)} Zeichen)...")
    if use_claude:
        result = _call_claude(user_prompt)
        if result is None:
            # Fallback auf Gemma bei Claude-Fehler
            print(f"  [Deep] Claude-Fallback auf Gemma")
            detail_text_short = detail_text[:DEEP_MAX_TEXT_GEMMA]
            user_prompt = _build_deep_prompt(prop, detail_text_short)
            result = _call_gemma(user_prompt)
    else:
        result = _call_gemma(user_prompt)

    if result is None:
        return None

    validated = _validate_deep_result(result)
    if validated is None:
        print(f"  [Deep] Validierung fehlgeschlagen: {title}")
        return None

    # Dokument-Text zum Speichern anfuegen (gekuerzt)
    validated["document_text"] = detail_text[:5000]

    return validated


def deep_score_auto(min_ki_score: float = None, limit: int = None) -> int:
    """Automatisches Deep-Scoring fuer top-bewertete Objekte."""
    if min_ki_score is None:
        min_ki_score = DEEP_MIN_KI_SCORE
    if limit is None:
        limit = DEEP_BATCH_SIZE

    candidates = get_deep_score_candidates(min_ki_score=min_ki_score, limit=limit)
    if not candidates:
        print("[Deep] Keine Kandidaten fuer Deep-Scoring.")
        return 0

    print(f"[Deep] {len(candidates)} Kandidaten (ki_score >= {min_ki_score})")

    # Ollama-Erreichbarkeit pruefen (nur wenn Gemma moeglich)
    if DEEP_MODEL_STRATEGY != "claude":
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
        except requests.RequestException:
            print("[Deep] Ollama nicht erreichbar — nur Claude verfuegbar")

    from scrapers.base import make_session
    scored = 0

    with make_session() as session:
        for i, prop in enumerate(candidates, 1):
            result = deep_score_property(prop, session)
            if result:
                save_deep_score(prop["link"], result)
                scored += 1
                print(
                    f"  [Deep] {i}/{len(candidates)}: "
                    f"{(prop.get('title') or '?')[:50]} -> {result['score']:.1f} ({result['risk']})"
                )
            else:
                print(f"  [Deep] {i}/{len(candidates)}: uebersprungen")

            if i < len(candidates):
                time.sleep(PAUSE_S)

    print(f"[Deep] Fertig: {scored}/{len(candidates)} deep-scored.")
    return scored


def deep_score_by_link(link: str) -> int:
    """Deep-Scoring fuer ein bestimmtes Objekt (manuell, ueberschreibt vorhandenes)."""
    prop = get_property_by_link(link)
    if not prop:
        print(f"[Deep] Kein Objekt gefunden: {link}")
        return 0

    print(f"[Deep] Manuelles Deep-Scoring: {(prop.get('title') or '?')[:60]}")

    from scrapers.base import make_session
    with make_session() as session:
        result = deep_score_property(prop, session)

    if result:
        save_deep_score(link, result)
        print(f"[Deep] Score: {result['score']:.1f} ({result['risk']})")
        print(f"[Deep] {result.get('headline', '')}")
        return 1
    else:
        print("[Deep] Deep-Scoring fehlgeschlagen (keine Dokumente oder Modell-Fehler)")
        return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deep Scoring fuer Investment Scanner")
    parser.add_argument("--link", help="Deep-Score fuer ein bestimmtes Objekt")
    parser.add_argument("--min-score", type=float, default=DEEP_MIN_KI_SCORE,
                        help=f"Mindest-KI-Score (Standard: {DEEP_MIN_KI_SCORE})")
    parser.add_argument("--limit", type=int, default=DEEP_BATCH_SIZE,
                        help=f"Max. Objekte (Standard: {DEEP_BATCH_SIZE})")
    args = parser.parse_args()

    if args.link:
        deep_score_by_link(args.link)
    else:
        deep_score_auto(min_ki_score=args.min_score, limit=args.limit)
