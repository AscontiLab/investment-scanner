#!/usr/bin/env python3
"""
KI-Scoring-Modul fuer den Investment Scanner.
Bewertet Immobilien-Objekte via Ollama (Gemma 4) mit Score 0-10.
"""

import json
import time
from datetime import datetime

import requests

from config import OLLAMA_URL, OLLAMA_MODEL, SCORING_BATCH_SIZE, OLLAMA_TIMEOUT, OLLAMA_PAUSE
from invest_db import _connect

MODEL = OLLAMA_MODEL
REQUEST_TIMEOUT = OLLAMA_TIMEOUT
PAUSE_BETWEEN_CALLS = OLLAMA_PAUSE

SYSTEM_PROMPT = """\
Du bist ein erfahrener Immobilien-Analyst und bewertest Grundstuecke und Investmentobjekte.

Bewerte das folgende Objekt auf einer Skala von 0 bis 10:
- 0-2: Unattraktiv (zu teuer, schlechte Lage, hohe Risiken)
- 3-4: Unterdurchschnittlich (einige Nachteile ueberwiegen)
- 5-6: Durchschnittlich (solide, aber kein Schnaeppchen)
- 7-8: Attraktiv (guter Preis, gute Lage, Potenzial)
- 9-10: Top-Deal (herausragendes Preis-Leistungs-Verhaeltnis)

Wichtige Kriterien:
- Preis pro m2 im Vergleich zur Region (Ostdeutschland: 5-30 EUR/m2 guenstig, 30-80 normal, >80 teuer)
- Lage und Infrastruktur (Naehe zu Staedten, Anbindung)
- Grundstuecksgroesse und Nutzbarkeit
- Risiken (Altlasten, Denkmalschutz, Zwangsversteigerung)
- Entwicklungspotenzial der Region

Antworte AUSSCHLIESSLICH als valides JSON ohne Markdown-Formatierung, ohne Code-Bloecke.
Das JSON muss exakt dieses Format haben:
{
  "score": 7.5,
  "headline": "Kurze praegnante Bewertung in einem Satz",
  "analysis": "2-3 Saetze detaillierte Analyse",
  "strengths": ["Staerke 1", "Staerke 2"],
  "weaknesses": ["Schwaeche 1", "Schwaeche 2"],
  "recommendation": "Kaufempfehlung oder Warnung in einem Satz",
  "risk": "niedrig"
}

Das Feld "risk" muss einen dieser Werte haben: "niedrig", "mittel", "hoch".
Der "score" muss eine Zahl zwischen 0 und 10 sein (Dezimalzahlen erlaubt).\
"""

SYSTEM_PROMPT_BETEILIGUNG = """\
Du bist ein erfahrener Finanzanalyst und bewertest Crowdfunding-Beteiligungen und Startup-Investments.

Bewerte das folgende Investment auf einer Skala von 0 bis 10:
- 0-2: Unattraktiv (hohes Risiko, schlechte Konditionen, fragwuerdiges Geschaeftsmodell)
- 3-4: Unterdurchschnittlich (einige Risiken ueberwiegen die Chancen)
- 5-6: Durchschnittlich (solide Konditionen, moderates Risiko)
- 7-8: Attraktiv (gute Rendite/Wachstum, starkes Team, ueberzeugender Markt)
- 9-10: Top-Investment (herausragendes Chance-Risiko-Verhaeltnis)

Wichtige Kriterien fuer Crowdfunding/Immobilien-Beteiligungen:
- Rendite p.a. im Vergleich zum Markt (5-7% solide, 8-10% gut, >10% kritisch pruefen)
- Laufzeit und Liquiditaet (kuerzere Laufzeit = weniger Risiko)
- Plattform-Reputation und Track Record
- Besicherung und Nachrangigkeit
- Projektqualitaet und Standort

Zusaetzliche Kriterien fuer Startup-Investments:
- Geschaeftsmodell und Skalierbarkeit
- Marktgroesse und Wettbewerb
- Team und Track Record
- Traction (Umsatz, Kunden, Patente)
- Bewertung und Funding-Fortschritt
- Exit-Perspektive

Antworte AUSSCHLIESSLICH als valides JSON ohne Markdown-Formatierung, ohne Code-Bloecke.
Das JSON muss exakt dieses Format haben:
{
  "score": 7.5,
  "headline": "Kurze praegnante Bewertung in einem Satz",
  "analysis": "2-3 Saetze detaillierte Analyse",
  "strengths": ["Staerke 1", "Staerke 2"],
  "weaknesses": ["Schwaeche 1", "Schwaeche 2"],
  "recommendation": "Investmentempfehlung oder Warnung in einem Satz",
  "risk": "niedrig"
}

Das Feld "risk" muss einen dieser Werte haben: "niedrig", "mittel", "hoch".
Der "score" muss eine Zahl zwischen 0 und 10 sein (Dezimalzahlen erlaubt).\
"""

# Quellen die als Beteiligung gelten
_BETEILIGUNG_SOURCES = {"bergfürst", "bergfuerst", "wiwin", "bettervest", "exporo", "companisto"}


def _is_beteiligung(prop: dict) -> bool:
    """Prueft ob ein Objekt eine Beteiligung ist (vs. Grundstueck)."""
    source = (prop.get("source") or "").lower()
    return any(s in source for s in _BETEILIGUNG_SOURCES)


def _build_user_prompt(prop: dict) -> str:
    """Erstellt den User-Prompt — unterscheidet Grundstuecke vs. Beteiligungen."""
    if _is_beteiligung(prop):
        return _build_beteiligung_prompt(prop)
    return _build_grundstueck_prompt(prop)


def _build_grundstueck_prompt(prop: dict) -> str:
    """Prompt fuer Grundstuecke/Immobilien."""
    parts = ["Bewerte dieses Immobilien-Objekt:\n"]

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
    if prop.get("company"):
        parts.append(f"Anbieter: {prop['company']}")
    if prop.get("status"):
        parts.append(f"Status: {prop['status']}")
    if prop.get("rented"):
        parts.append(f"Vermietet: {prop['rented']}")
    if prop.get("monument"):
        parts.append(f"Denkmalschutz: {prop['monument']}")
    if prop.get("auction_number"):
        parts.append(f"Aktenzeichen: {prop['auction_number']}")
    if prop.get("catalog_text"):
        text = prop["catalog_text"][:1500]
        parts.append(f"Objektbeschreibung:\n{text}")

    return "\n".join(parts)


def _build_beteiligung_prompt(prop: dict) -> str:
    """Prompt fuer Crowdfunding-Beteiligungen und Startup-Investments."""
    parts = ["Bewerte dieses Investment:\n"]

    if prop.get("title"):
        parts.append(f"Projekt: {prop['title']}")
    if prop.get("source"):
        parts.append(f"Plattform: {prop['source']}")
    if prop.get("location"):
        parts.append(f"Standort: {prop['location']}")
    if prop.get("category"):
        parts.append(f"Typ: {prop['category']}")

    # Beteiligungsfelder aus der DB (via upsert_property durchgereicht)
    for key, label in [
        ("rendite_pct", "Rendite p.a."),
        ("laufzeit", "Laufzeit"),
        ("min_anlage_eur", "Mindestanlage"),
        ("typ", "Investmenttyp"),
    ]:
        val = prop.get(key)
        if val:
            if key == "rendite_pct":
                parts.append(f"{label}: {val} %")
            elif key == "min_anlage_eur":
                parts.append(f"{label}: {val:,.0f} EUR".replace(",", "."))
            else:
                parts.append(f"{label}: {val}")

    if prop.get("status"):
        parts.append(f"Status: {prop['status']}")

    return "\n".join(parts)


def _call_ollama(user_prompt: str, retry: bool = True, system_prompt: str = None) -> dict | None:
    """Ruft Ollama Chat-API auf und parst die JSON-Antwort."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"num_predict": 300},
    }

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [KI] Ollama-Fehler: {e}")
        return None

    data = resp.json()
    content = data.get("message", {}).get("content", "").strip()

    # Markdown-Code-Bloecke entfernen falls vorhanden
    if content.startswith("```"):
        lines = content.split("\n")
        # Erste und letzte Zeile (``` bzw. ```json) entfernen
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines).strip()

    try:
        result = json.loads(content)
        return result
    except json.JSONDecodeError:
        if retry:
            print("  [KI] JSON-Parse-Fehler, Retry mit expliziter Anweisung...")
            # Retry mit deutlicherem Hinweis
            retry_prompt = (
                user_prompt
                + "\n\nWICHTIG: Antworte NUR als valides JSON. "
                "Kein Markdown, keine Code-Bloecke, kein zusaetzlicher Text."
            )
            time.sleep(1)
            return _call_ollama(retry_prompt, retry=False, system_prompt=system_prompt)
        print(f"  [KI] JSON-Parse-Fehler auch nach Retry. Antwort: {content[:200]}")
        return None


def _validate_result(result: dict) -> dict | None:
    """Validiert und normalisiert das KI-Ergebnis."""
    try:
        score = float(result.get("score", -1))
        if not 0 <= score <= 10:
            print(f"  [KI] Ungueltiger Score: {score}")
            return None
    except (ValueError, TypeError):
        print(f"  [KI] Score nicht parsebar: {result.get('score')}")
        return None

    risk = str(result.get("risk", "mittel")).lower().strip()
    if risk not in ("niedrig", "mittel", "hoch"):
        risk = "mittel"

    return {
        "score": score,
        "headline": str(result.get("headline", ""))[:500],
        "analysis": str(result.get("analysis", ""))[:2000],
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "recommendation": str(result.get("recommendation", ""))[:500],
        "risk": risk,
    }


def score_properties(limit: int = SCORING_BATCH_SIZE) -> int:
    """Bewertet unbewertete Properties via Ollama Gemma 4. Gibt Anzahl bewerteter zurueck."""
    # Unbewertete Properties laden
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM properties WHERE ki_score IS NULL ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
        properties = [dict(row) for row in rows]

    if not properties:
        print("[KI] Keine unbewerteten Objekte vorhanden.")
        return 0

    print(f"[KI] {len(properties)} Objekte zum Bewerten gefunden.")

    # Ollama-Erreichbarkeit pruefen
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[KI] Ollama nicht erreichbar ({e}). Scoring uebersprungen.")
        return 0

    scored_count = 0
    today = datetime.now().strftime("%Y-%m-%d")

    for i, prop in enumerate(properties, 1):
        title = prop.get("title") or "Unbekannt"
        short_title = title[:50]

        user_prompt = _build_user_prompt(prop)
        sys_prompt = SYSTEM_PROMPT_BETEILIGUNG if _is_beteiligung(prop) else SYSTEM_PROMPT
        result = _call_ollama(user_prompt, system_prompt=sys_prompt)

        if result is None:
            print(f"  [KI] {i}/{len(properties)} FEHLER: {short_title}")
            if i < len(properties):
                time.sleep(PAUSE_BETWEEN_CALLS)
            continue

        validated = _validate_result(result)
        if validated is None:
            print(f"  [KI] {i}/{len(properties)} VALIDIERUNG FEHLGESCHLAGEN: {short_title}")
            if i < len(properties):
                time.sleep(PAUSE_BETWEEN_CALLS)
            continue

        # In DB speichern
        with _connect() as conn:
            conn.execute(
                """UPDATE properties
                   SET ki_score = ?, ki_headline = ?, ki_analysis = ?,
                       ki_strengths = ?, ki_weaknesses = ?, ki_recommendation = ?,
                       ki_risk = ?, ki_scored_at = ?
                   WHERE id = ?""",
                (
                    validated["score"],
                    validated["headline"],
                    validated["analysis"],
                    json.dumps(validated["strengths"], ensure_ascii=False),
                    json.dumps(validated["weaknesses"], ensure_ascii=False),
                    validated["recommendation"],
                    validated["risk"],
                    today,
                    prop["id"],
                ),
            )
            conn.commit()

        scored_count += 1
        print(
            f"  [KI] {i}/{len(properties)} bewertet: "
            f"{short_title} -> {validated['score']:.1f} ({validated['risk']})"
        )

        # Pause zwischen Aufrufen (nicht nach dem letzten)
        if i < len(properties):
            time.sleep(PAUSE_BETWEEN_CALLS)

    print(f"[KI] Fertig: {scored_count}/{len(properties)} Objekte bewertet.")
    return scored_count


def rescore_all(limit: int = SCORING_BATCH_SIZE) -> int:
    """Setzt alle KI-Scores zurueck und bewertet neu."""
    with _connect() as conn:
        conn.execute(
            "UPDATE properties SET ki_score = NULL, ki_scored_at = NULL"
        )
        conn.commit()
    print("[KI] Alle Scores zurueckgesetzt.")
    return score_properties(limit=limit)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KI-Scoring fuer Investment Scanner")
    parser.add_argument(
        "--limit", type=int, default=SCORING_BATCH_SIZE,
        help=f"Max. Anzahl zu bewertender Objekte (Standard: {SCORING_BATCH_SIZE})",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Alle Objekte neu bewerten (Scores zuruecksetzen)",
    )
    args = parser.parse_args()

    if args.all:
        rescore_all(limit=args.limit)
    else:
        score_properties(limit=args.limit)
