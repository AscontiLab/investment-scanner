#!/usr/bin/env python3
"""
Investment Opportunity Scanner
───────────────────────────────
Scrapet Grundstuecke und Crowdfunding-Beteiligungen fuer Ostdeutschland.

Quellen Grundstuecke:  Kleinanzeigen.de, DGA, Zwangsversteigerungstermine.de
Quellen Crowdfunding: Bettervest, Bergfuerst, Wiwin, Exporo
"""

import argparse
import csv
import logging
import time
from datetime import datetime
from html import escape
from pathlib import Path

from config import MAX_PRICE, MIN_RENDITE, PAUSE_S

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "scanner.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    filename=str(LOG_FILE),
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"

REVIEW_LABELS = {
    "interessant": ("review-good", "Interessant"),
    "nachfassen": ("review-follow", "Nachfassen"),
    "ignorieren": ("review-skip", "Ignorieren"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# HTML REPORT
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background:#f4f7fb; margin:0; padding:20px; color:#1a1a2e; }
h1   { color:#1a3a6e; border-bottom:2px solid #c8d8f0; padding-bottom:10px; }
h2   { color:#1a56a0; margin-top:28px; }
.summary { display:flex; gap:14px; flex-wrap:wrap; margin:18px 0; }
.card { background:#f0f5ff; border:1px solid #c8d8f0; border-radius:8px;
        padding:14px 22px; min-width:130px; }
.card .val { font-size:1.9em; font-weight:700; color:#1a56a0; }
.card .lbl { color:#555577; font-size:0.8em; margin-top:2px; }
table { width:100%; border-collapse:collapse; background:#ffffff;
        border:1px solid #dde3ed; border-radius:8px; overflow:hidden; margin:14px 0; }
th  { background:#eef2fa; padding:9px 12px; text-align:left;
      color:#444466; font-size:0.82em; border-bottom:1px solid #dde3ed; }
td  { padding:8px 12px; border-bottom:1px solid #eef2fa; font-size:0.88em; color:#1a1a2e; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#f5f8ff; }
.tag  { background:#1a56a0; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.tag2 { background:#1a7a30; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.tag3 { background:#e07000; color:#fff; border-radius:4px;
        padding:2px 7px; font-size:0.75em; }
.warn { background:#fff8e8; border-left:3px solid #e09000; padding:10px 14px;
        color:#664400; font-size:0.82em; border-radius:0 6px 6px 0; margin:8px 0; }
.review-card { background:#ffffff; border:1px solid #dde3ed; border-radius:8px; padding:14px 16px; margin:18px 0; }
.review-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; }
.review-item { border:1px solid #e5ebf5; border-radius:8px; padding:10px 12px; background:#f9fbff; }
.review-note { color:#555577; font-size:0.8em; margin-top:6px; line-height:1.4; }
.review-tag { display:inline-block; border-radius:999px; padding:3px 9px; font-size:0.75em; font-weight:600; }
.review-open { background:#eef2fa; color:#445; }
.review-good { background:#e8f6eb; color:#1a7a30; }
.review-follow { background:#fff4e5; color:#b36200; }
.review-skip { background:#fdecec; color:#b02525; }
.empty { color:#777799; padding:18px; text-align:center;
         background:#f7f9ff; border:1px solid #dde3ed; border-radius:8px; }
a    { color:#1a56a0; text-decoration:none; }
a:hover { text-decoration:underline; }
.footer { color:#777799; font-size:0.78em; margin-top:30px;
          border-top:1px solid #dde3ed; padding-top:14px; }
"""


def _safe_href(url: str) -> str:
    return url if url.startswith(("https://", "http://")) else "#"


def _quelle_tag(quelle: str) -> str:
    tags = {
        "Kleinanzeigen": "tag",
        "DGA Auktion": "tag2",
        "Zwangsversteigerung": "tag3",
    }
    css = tags.get(quelle, "tag")
    return f'<span class="{css}">{escape(quelle)}</span>'


def _plattform_tag(plattform: str) -> str:
    return f'<span class="tag">{escape(plattform)}</span>'


def _review_badge(status: str | None) -> str:
    if not status:
        return '<span class="review-tag review-open">Offen</span>'
    css, label = REVIEW_LABELS.get(status, ("review-open", status))
    return f'<span class="review-tag {css}">{escape(label)}</span>'


def _review_summary(items: list[dict]) -> str:
    counts = {"offen": 0, "interessant": 0, "nachfassen": 0, "ignorieren": 0}
    for item in items:
        counts[item.get("operator_status") or "offen"] = counts.get(item.get("operator_status") or "offen", 0) + 1
    return (
        f'<div class="card"><div class="val">{counts["offen"]}</div><div class="lbl">Offen</div></div>'
        f'<div class="card"><div class="val">{counts["interessant"]}</div><div class="lbl">Interessant</div></div>'
        f'<div class="card"><div class="val">{counts["nachfassen"]}</div><div class="lbl">Nachfassen</div></div>'
        f'<div class="card"><div class="val">{counts["ignorieren"]}</div><div class="lbl">Ignorieren</div></div>'
    )


def _build_review_queue(items: list[dict]) -> str:
    queue = [item for item in items if not item.get("operator_status")]
    queue.sort(key=lambda item: (item.get("ki_score") is None, -(item.get("ki_score") or 0), item.get("price") or item.get("preis_eur") or 10**12))
    queue = queue[:6]
    if not queue:
        return '<div class="empty">Keine offenen Review-Kandidaten im aktuellen Bestand.</div>'

    parts = []
    for item in queue:
        title = escape((item.get("title") or item.get("titel") or "?")[:90])
        location = escape(item.get("location") or item.get("ort") or "–")
        price = item.get("price") or item.get("preis_eur")
        price_html = f"{price:,} €".replace(",", ".") if price else "–"
        score = item.get("ki_score")
        score_html = f"KI-Score {score:.1f}" if isinstance(score, (int, float)) else "Noch kein KI-Score"
        link = _safe_href(item.get("link") or "")
        parts.append(
            f"""<div class="review-item">
<div><strong>{title}</strong></div>
<div class="review-note">{location} · {price_html} · {score_html}</div>
<div class="review-note">CLI: <code>python3 investment_scanner.py --review-link "{escape(item.get('link') or '')}" --review-status interessant</code></div>
<div class="review-note"><a href="{link}" target="_blank" rel="noopener noreferrer">→ Deal öffnen</a></div>
</div>"""
        )
    return f'<div class="review-grid">{"".join(parts)}</div>'


def _score_badge(ki_score, deep_score) -> str:
    """Erzeugt KI-Score + Deep-Score Badge."""
    parts = []
    if isinstance(ki_score, (int, float)):
        color = "#1a7a30" if ki_score >= 7 else "#1a56a0" if ki_score >= 5 else "#b02525"
        parts.append(f'<span style="color:{color};font-weight:700">KI {ki_score:.1f}</span>')
    if isinstance(deep_score, (int, float)):
        color = "#1a7a30" if deep_score >= 7 else "#1a56a0" if deep_score >= 5 else "#b02525"
        parts.append(f'<span class="tag2" style="font-size:0.7em">Deep {deep_score:.1f}</span>')
    return " ".join(parts) if parts else "–"


def build_grundstuecke_table(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Keine Grundstücke gefunden.</div>'
    headers = ["Quelle", "Titel", "Ort", "Fläche", "Preis", "€/m²", "Score", "Review", "Link"]
    row_parts = []
    for b in sorted(items, key=lambda x: x.get("preis_eur") or 999_999):
        flaeche = f"{b['flaeche_m2']:,} m²".replace(",", ".") if b.get("flaeche_m2") else "–"
        preis = f"{b['preis_eur']:,} €".replace(",", ".") if b.get("preis_eur") else "–"
        epm2 = f"{b['eur_pro_m2']:.1f}".replace(".", ",") if b.get("eur_pro_m2") else "–"
        href = _safe_href(b['link'])
        review_note = escape(b.get("operator_note") or "")
        score_html = _score_badge(b.get("ki_score"), b.get("deep_score"))
        deep_hint = ""
        if b.get("deep_headline"):
            deep_hint = f'<div class="review-note">{escape(b["deep_headline"][:100])}</div>'
        row_parts.append(f"""<tr>
          <td>{_quelle_tag(b['quelle'])}</td>
          <td><strong>{escape(b['titel'][:80])}</strong></td>
          <td>{escape(b.get('ort', '–'))}</td>
          <td>{flaeche}</td>
          <td>{preis}</td>
          <td>{epm2}</td>
          <td>{score_html}{deep_hint}</td>
          <td>{_review_badge(b.get('operator_status'))}{f'<div class="review-note">{review_note}</div>' if review_note else ''}</td>
          <td><a href="{href}" target="_blank" rel="noopener noreferrer">→ Inserat</a></td>
        </tr>""")
    rows = "".join(row_parts)
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def build_beteiligungen_table(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Keine Beteiligungen gefunden.</div>'
    headers = ["Plattform", "Projekt", "Typ", "Rendite p.a.", "Laufzeit", "Mind. Anlage", "Status", "Review", "Link"]
    row_parts = []
    for b in sorted(items, key=lambda x: -(x.get("rendite_pct") or 0)):
        rendite = f"{b['rendite_pct']:.1f} %" if b.get("rendite_pct") else "–"
        min_anlage = f"{b['min_anlage_eur']:,} €".replace(",", ".") if b.get("min_anlage_eur") else "–"
        href = _safe_href(b['link'])
        review_note = escape(b.get("operator_note") or "")
        row_parts.append(f"""<tr>
          <td>{_plattform_tag(b['plattform'])}</td>
          <td><strong>{escape(b['titel'][:80])}</strong></td>
          <td>{escape(b.get('typ', '–'))}</td>
          <td style="color:#1a7a30;font-weight:700">{rendite}</td>
          <td>{escape(b.get('laufzeit', '–'))}</td>
          <td>{min_anlage}</td>
          <td>{escape(b.get('status', '–'))}</td>
          <td>{_review_badge(b.get('operator_status'))}{f'<div class="review-note">{review_note}</div>' if review_note else ''}</td>
          <td><a href="{href}" target="_blank" rel="noopener noreferrer">→ Projekt</a></td>
        </tr>""")
    rows = "".join(row_parts)
    ths = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{ths}</tr>{rows}</table>"


def generate_html(grundstuecke: list[dict], beteiligungen: list[dict],
                  warnings: list[str]) -> str:
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")
    timestamp = now.strftime("%d.%m.%Y %H:%M")

    preise_m2 = [b["eur_pro_m2"] for b in grundstuecke if b.get("eur_pro_m2")]
    avg_epm2 = f"{sum(preise_m2)/len(preise_m2):.0f} €/m²" if preise_m2 else "–"

    renditen = [b["rendite_pct"] for b in beteiligungen if b.get("rendite_pct")]
    best_rend = f"{max(renditen):.1f} %" if renditen else "–"

    warn_html = "".join(f'<div class="warn">&#9888;&#65039; {escape(w)}</div>' for w in warnings)

    max_price_fmt = f"{MAX_PRICE:,}".replace(",", ".")
    min_rendite_fmt = f"{MIN_RENDITE:.1f}".replace(".", ",")
    review_items = grundstuecke + beteiligungen
    review_summary = _review_summary(review_items)
    review_queue = _build_review_queue(review_items)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Investment Scanner {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<h1>&#128188; Investment Scanner — {date_str}</h1>

<div class="summary">
  <div class="card"><div class="val">{len(grundstuecke)}</div><div class="lbl">&#127968; Grundstücke</div></div>
  <div class="card"><div class="val">{len(beteiligungen)}</div><div class="lbl">&#128176; Beteiligungen</div></div>
  <div class="card"><div class="val">{avg_epm2}</div><div class="lbl">Ø €/m²</div></div>
  <div class="card"><div class="val">{best_rend}</div><div class="lbl">Beste Rendite</div></div>
</div>

<h2>&#128221; Review-Status</h2>
<div class="summary">{review_summary}</div>
<div class="review-card">
  <strong>Offene Review-Queue</strong>
  <div class="review-note" style="margin:8px 0 12px;">Die offenen Deals lassen sich direkt per CLI markieren: <code>python3 investment_scanner.py --review-link "..." --review-status interessant --review-note "..."</code></div>
  {review_queue}
</div>

{warn_html}

<h2>&#127968; Grundstücke (max. {max_price_fmt} €)</h2>
{build_grundstuecke_table(grundstuecke)}

<h2>&#128176; Beteiligungen & Crowdfunding (min. {min_rendite_fmt} % p.a.)</h2>
{build_beteiligungen_table(beteiligungen)}

<div class="footer">
  Generiert: {timestamp} &nbsp;|&nbsp;
  Quellen: Kleinanzeigen.de · DGA · ZVG-Portal · Bergfürst · Wiwin · Bettervest · Exporo<br>
  &#9888;&#65039; Diese Übersicht dient ausschließlich zu Informationszwecken. Keine Anlageberatung.
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investment Scanner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Keine externen API-Calls; erzeugt leeren Report.")
    parser.add_argument("--review-link", help="Link des Deals fuer Operator-Review")
    parser.add_argument("--review-status", choices=["interessant", "nachfassen", "ignorieren"],
                        help="Operator-Status fuer --review-link")
    parser.add_argument("--review-note", default="", help="Optionale Operator-Notiz")
    parser.add_argument("--list-review-queue", action="store_true",
                        help="Offene Review-Kandidaten ausgeben")
    parser.add_argument("--score", action="store_true",
                        help="Nur KI-Scoring ausfuehren (kein Scan)")
    parser.add_argument("--score-all", action="store_true",
                        help="Alle Properties neu bewerten")
    parser.add_argument("--deep-score", action="store_true",
                        help="Deep-Scoring: Dokumente laden + neu bewerten (Score >= 7)")
    parser.add_argument("--deep-score-link", type=str, default=None,
                        help="Deep-Scoring fuer ein bestimmtes Objekt (URL)")
    return parser.parse_args()


def _dedupe(items: list[dict]) -> list[dict]:
    """Entfernt Duplikate anhand von Link oder (Titel+Ort+Preis)."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        link = (it.get("link") or "").strip().lower()
        if link:
            key = f"link:{link}"
        else:
            title = (it.get("titel") or "").strip().lower()
            ort = (it.get("ort") or "").strip().lower()
            preis = str(it.get("preis_eur") or "")
            key = f"t:{title}|o:{ort}|p:{preis}"
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main() -> int:
    args = parse_args()

    # ── Deep-Scoring-Modus ───────────────────────────────────────────────
    if args.deep_score or args.deep_score_link:
        try:
            from deep_scorer import deep_score_auto, deep_score_by_link
            if args.deep_score_link:
                count = deep_score_by_link(args.deep_score_link)
            else:
                count = deep_score_auto()
            print(f"[Deep-KI] {count} Properties deep-scored")
        except Exception as e:
            print(f"[Deep-KI] Fehler: {e}")
        return 0

    # ── KI-Scoring-Only-Modus ──────────────────────────────────────────────
    if args.score or args.score_all:
        try:
            from ki_scorer import rescore_all, score_properties
            if args.score_all:
                scored = rescore_all(limit=100)
            else:
                scored = score_properties()
            print(f"[KI] {scored} Properties bewertet")
        except Exception as e:
            print(f"[KI] Fehler beim Scoring: {e}")
        return 0

    # ── Operator-Review-Modus ──────────────────────────────────────────────
    if args.review_link or args.list_review_queue:
        from invest_db import get_review_queue, init_db, save_operator_review

        init_db()
        if args.list_review_queue:
            queue = get_review_queue()
            if not queue:
                print("Keine offenen Review-Kandidaten.")
                return 0
            print("Offene Review-Kandidaten:")
            for item in queue:
                title = item.get("title") or "?"
                score = item.get("ki_score")
                score_label = f"KI {score:.1f}" if isinstance(score, (int, float)) else "KI –"
                print(f"- {title} | {item.get('location') or '–'} | {score_label}")
                print(f"  {item.get('link')}")
            return 0
        if not args.review_status:
            raise SystemExit("--review-status ist erforderlich, wenn --review-link gesetzt ist")
        if not save_operator_review(args.review_link, args.review_status, args.review_note):
            raise SystemExit("Kein Deal zu diesem Link gefunden")
        print(f"Review gespeichert: {args.review_status}")
        return 0

    # ── Scanner-Hauptlauf ──────────────────────────────────────────────────
    now = datetime.now()
    print("=" * 60)
    print(f"  Investment Scanner — {now.strftime('%d.%m.%Y %H:%M')}")
    print("=" * 60)

    date_str = now.strftime("%Y-%m-%d")
    out_dir = OUTPUT_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    warnings = []
    grundstuecke: list[dict] = []
    beteiligungen: list[dict] = []

    if args.dry_run:
        print("[DRY-RUN] Keine externen API-Calls. Erzeuge leeren Report …")
    else:
        from scrapers import (
            scrape_kleinanzeigen, scrape_dga, scrape_zvg,
            scrape_bergfuerst, scrape_wiwin, scrape_bettervest, scrape_exporo,
            scrape_companisto,
        )
        from scrapers.base import make_session

        with make_session() as session:
            # ── GRUNDSTUECKE ───────────────────────────────────────────────
            logger.info("=== Grundstuecke ===")

            r = scrape_kleinanzeigen(session)
            grundstuecke.extend(r)
            if not r:
                warnings.append("Kleinanzeigen: keine Ergebnisse (Selektoren pruefen)")
            time.sleep(PAUSE_S)

            r = scrape_dga(session)
            grundstuecke.extend(r)
            if not r:
                warnings.append("DGA: keine Ergebnisse")
            time.sleep(PAUSE_S)

            r = scrape_zvg(session)
            grundstuecke.extend(r)
            if not r:
                warnings.append("ZVG-Portal: keine Ergebnisse")

            # ── BETEILIGUNGEN ──────────────────────────────────────────────
            logger.info("=== Beteiligungen ===")

            for fn, name in [
                (scrape_bettervest, "Bettervest"),
                (scrape_bergfuerst, "Bergfürst"),
                (scrape_wiwin, "Wiwin"),
                (scrape_exporo, "Exporo"),
                (scrape_companisto, "Companisto"),
            ]:
                time.sleep(PAUSE_S)
                r = fn(session)
                beteiligungen.extend(r)
                real_results = [x for x in r if x.get("status") != "prüfen"]
                if not real_results:
                    warnings.append(f"{name}: keine echten Projekte (manuelle Prüfung empfohlen)")

    # ── REPORT ─────────────────────────────────────────────────────────────
    grundstuecke = _dedupe(grundstuecke)
    beteiligungen = _dedupe(beteiligungen)
    logger.info("Grundstuecke: %d | Beteiligungen: %d", len(grundstuecke), len(beteiligungen))

    # ── Katalog-Anreicherung (DGA) ─────────────────────────────────────────
    try:
        from dga_catalog import enrich_dga_properties
        grundstuecke = enrich_dga_properties(grundstuecke)
        logger.info("Katalog-Anreicherung abgeschlossen")
    except ImportError:
        logger.info("dga_catalog nicht verfuegbar — uebersprungen")
    except Exception as e:
        logger.warning("Katalog-Anreicherung Fehler: %s", e)

    # ── DB-Integration ─────────────────────────────────────────────────────
    try:
        from invest_db import get_review_map, init_db, log_scan_run, upsert_property
        init_db()
        all_items = grundstuecke + beteiligungen
        new_count = 0
        for item in all_items:
            db_record = {
                "link": item.get("link", ""),
                "source": item.get("quelle", item.get("plattform", "")),
                "title": item.get("titel", ""),
                "location": item.get("ort", ""),
                "price": item.get("preis_eur"),
                "area_m2": item.get("flaeche_m2"),
            }
            for key in ("company", "auction_number", "category", "category_code",
                        "status", "rented", "monument", "region", "catalog_text"):
                if key in item:
                    db_record[key] = item[key]
            for key in ("rendite_pct", "laufzeit", "min_anlage_eur", "typ"):
                if key in item:
                    db_record[key] = item[key]
            if upsert_property(db_record):
                new_count += 1
        log_scan_run(len(all_items), new_count)
        logger.info("DB: %d Eintraege, davon %d neu", len(all_items), new_count)
        review_map = get_review_map([item.get("link", "") for item in all_items])
        for item in all_items:
            review = review_map.get(item.get("link", ""))
            if review:
                item.update(review)
    except ImportError:
        logger.warning("invest_db nicht verfuegbar — DB-Integration uebersprungen")
    except Exception as e:
        logger.warning("DB-Integration Fehler: %s", e)

    # ── KI-Scoring (automatisch nach Scan) ─────────────────────────────────
    try:
        from ki_scorer import score_properties as ki_score_properties
        scored = ki_score_properties(limit=20)
        print(f"[KI] {scored} Properties bewertet")
    except Exception as e:
        logger.warning("KI-Scoring Fehler: %s", e)
        print(f"[KI] Scoring uebersprungen: {e}")

    # ── Deep Scoring (automatisch fuer top-bewertete Objekte) ──────────────
    try:
        from deep_scorer import deep_score_auto
        deep_count = deep_score_auto()
        print(f"[Deep-KI] {deep_count} Properties deep-scored")
    except Exception as e:
        logger.warning("Deep-Scoring Fehler: %s", e)
        print(f"[Deep-KI] Deep-Scoring uebersprungen: {e}")

    html = generate_html(grundstuecke, beteiligungen, warnings)
    html_path = out_dir / "investments.html"
    try:
        html_path.write_text(html, encoding="utf-8")
        logger.info("HTML: %s", html_path)
    except OSError as e:
        logger.warning("HTML schreiben fehlgeschlagen: %s", e)

    # ── CSV ─────────────────────────────────────────────────────────────────
    rows = []
    for b in grundstuecke:
        rows.append({
            "Kategorie": "Grundstück",
            "Quelle": b.get("quelle", ""),
            "Titel": b.get("titel", ""),
            "Ort": b.get("ort", ""),
            "Fläche m²": b.get("flaeche_m2", ""),
            "Preis €": b.get("preis_eur", ""),
            "€/m²": b.get("eur_pro_m2", ""),
            "Nutzung": b.get("nutzung", ""),
            "Link": b.get("link", ""),
        })
    for b in beteiligungen:
        rows.append({
            "Kategorie": "Beteiligung",
            "Quelle": b.get("plattform", ""),
            "Titel": b.get("titel", ""),
            "Typ": b.get("typ", ""),
            "Rendite %": b.get("rendite_pct", ""),
            "Laufzeit": b.get("laufzeit", ""),
            "Mind. €": b.get("min_anlage_eur", ""),
            "Status": b.get("status", ""),
            "Link": b.get("link", ""),
        })

    if rows:
        all_keys = {k for r in rows for k in r}
        fieldnames = ["Kategorie"] + sorted(all_keys - {"Kategorie"})
        csv_path = out_dir / "investments.csv"
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            logger.info("CSV:  %s", csv_path)
        except OSError as e:
            logger.warning("CSV schreiben fehlgeschlagen: %s", e)

    print("\n✓ Fertig!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
