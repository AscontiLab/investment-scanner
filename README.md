# Investment Scanner

## Ueberblick

Taeglich laufender Scanner fuer Grundstuecke und Crowdfunding-Deals mit SQLite-Datenbank, DGA-Katalog-Extraktion, zweistufigem KI-Scoring (KI Score + Deep Score) und HTML/CSV-Reporting.

## Zweck

- Guenstige Grundstuecksangebote aggregieren (Kleinanzeigen, DGA, ZVG)
- Crowdfunding-Projekte nach Mindestrendite filtern (Bergfuerst, Wiwin, Bettervest, Exporo, Companisto)
- Ergebnisse als HTML- und CSV-Report bereitstellen
- KI-Scoring via Ollama (Gemma 4)
- Deep Scoring: Dokumenten-basierte Zweitbewertung (Gemma oder Claude)
- Telegram-Alerts bei Deep Score >= 7

## Projektstruktur

```
investment_scanner.py      # Orchestrator: CLI, Report-Erzeugung, DB-Integration
config.py                  # Laedt config.yaml, stellt Konstanten bereit
config.yaml                # Zentrale Konfiguration (nicht im Repo, siehe .example)
config.yaml.example        # Vorlage fuer config.yaml

scrapers/                  # Ein Modul pro Datenquelle (8 Quellen)
  __init__.py              # Re-Export aller Scraper
  base.py                  # Gemeinsame Hilfsfunktionen (Session, Parser, Regex)
  kleinanzeigen.py         # Kleinanzeigen.de
  dga.py                   # Deutsche Grundstuecksauktionen AG
  zvg.py                   # ZVG-Portal (Zwangsversteigerungen)
  bergfuerst.py            # Bergfuerst Crowdinvesting
  wiwin.py                 # Wiwin Crowdinvesting
  bettervest.py            # Bettervest (PV/Energie)
  exporo.py                # Exporo (Playwright Login + GraphQL)
  companisto.py            # Companisto (Startup-Investments)

invest_db.py               # SQLite-Datenbankmodul (Deal-Tracking, Review-Queue)
dga_catalog.py             # DGA Katalog-Extraktor (PDFs → Objektdetails)
ki_scorer.py               # KI-Scoring via Ollama (Gemma 4)
deep_scorer.py             # Deep Scoring — Stufe 2 (Dokumente + Gemma/Claude)
send_report.py             # E-Mail-Versand
run_scanner.sh             # Wrapper fuer Cron
```

## Voraussetzungen

- Python 3.10+
- `scanner-common` als pip-Paket
- `requests`, `beautifulsoup4`, `pdfminer.six`, `pyyaml`

## Einrichtung

```bash
cd /home/claude-agent/investment-scanner
cp config.yaml.example config.yaml
# config.yaml anpassen (Ollama-URL, Regionen, Preislimits etc.)
```

## Konfiguration

Alle Schwellenwerte und Einstellungen liegen in `config.yaml`:

| Parameter | Beschreibung | Default |
|-----------|-------------|---------|
| `max_price` | Maximalpreis Grundstuecke (EUR) | 50.000 |
| `min_rendite` | Mindestrendite Crowdfunding (% p.a.) | 4.0 |
| `regions` | Zielregionen fuer Grundstuecke | Berlin, Brandenburg, Sachsen, ... |
| `pause_seconds` | Pause zwischen HTTP-Requests | 1.5 |
| `ollama.url` | Ollama-API-Adresse | http://172.28.0.20:11434 |
| `ollama.model` | LLM-Modell fuer KI-Scoring | gemma4:e4b |
| `ollama.batch_size` | Max. Bewertungen pro Lauf | 20 |

Zugangsdaten (DGA Login, Gmail, Telegram) liegen in `~/.stock_scanner_credentials`.

## Nutzung

```bash
python3 investment_scanner.py              # Vollstaendiger Scan + Report
python3 investment_scanner.py --dry-run    # Ohne Scraping, leerer Report
python3 investment_scanner.py --score      # Nur KI-Scoring (kein Scan)
python3 investment_scanner.py --score-all  # Alle Objekte neu bewerten
bash run_scanner.sh                        # Wrapper fuer Cron
```

Review-Queue:

```bash
python3 investment_scanner.py --list-review-queue
python3 investment_scanner.py \
  --review-link "https://example.com/deal" \
  --review-status interessant \
  --review-note "Nur bei belastbarer Vermietung weiter pruefen"
```

## Output

Report-Dateien unter `output/YYYY-MM-DD/`:
- `investments.html` — Interaktiver HTML-Report mit Review-Queue
- `investments.csv` — CSV-Export

## Sicherheit

- SQL Injection Fix: `_validate_identifier()` validiert dynamische SQL-Identifier
- Credentials nicht im Code — alles ueber `~/.stock_scanner_credentials`
- `config.yaml` in `.gitignore` (nur `.example` im Repo)

## Cron

```cron
0 6 * * * cd /home/claude-agent/investment-scanner && /usr/bin/python3 investment_scanner.py >> logs/scanner.log 2>&1
```

## Deep Scoring Fixes (2026-04-14)

- **ZVG**: Referer-Header hinzugefuegt (Portal erfordert ihn)
- **Exporo**: Synthetischer Detail-Text aus DB-Feldern (Flutter SPA hat kein HTML)
- **Wiwin**: Dedizierter HTML-Fetcher mit PDF-Download
- **Companisto**: Synthetischer Fallback wie Exporo
- **Gemma4 Fallback**: Bei leerem Gemma-Output automatisch Claude als Fallback
- **Auto-Hide**: `deep_score < 5` setzt automatisch `operator_status='hidden'`
- **Dashboard**: Deep-Score-Button repariert (Auth-Pfad, Subprocess, base_path in JS)

## Unified Dashboard

Eingebunden unter `https://agents.umzwei.de/dashboard/invest/`.
