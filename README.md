# Investment Scanner

## Ueberblick

Taeglich laufender Scanner fuer Grundstuecke und Crowdfunding-Deals mit SQLite-Datenbank, DGA-Katalog-Extraktion und HTML/CSV-Reporting.

## Zweck

- Guenstige Grundstuecksangebote aggregieren
- Crowdfunding-Projekte nach Mindestrendite filtern
- Ergebnisse als HTML- und CSV-Report bereitstellen

## Bestandteile

- `investment_scanner.py`
  - Hauptlogik fuer Scan und Report
- `invest_db.py`
  - SQLite-Datenbankmodul (Deal-Tracking, Review-Queue)
- `dga_catalog.py`
  - DGA Katalog-Extraktor (Katalog-PDFs → Objektdetails)
- `send_report.py`
  - E-Mail-Versand
- `run_scanner.sh`
  - Wrapper fuer den periodischen Betrieb (nutzt portablen Pfad via `$(dirname)`)


## Voraussetzungen

- Python 3.10+
- `scanner-common` als pip-Paket (nicht mehr lokale Kopie)
- `requests`
- `beautifulsoup4`

## Sicherheit

- SQL Injection Fix: `_validate_identifier()` in `invest_db.py` validiert dynamische Tabellen-/Spaltennamen

## Einrichtung

```bash
cd /home/claude-agent/investment-scanner
pip install requests beautifulsoup4
```

## Konfiguration

- Scanner-Schwellenwerte liegen direkt in `investment_scanner.py`
- E-Mail-Zugangsdaten werden ueber `~/.stock_scanner_credentials` gelesen

## Nutzung

```bash
python3 investment_scanner.py
```

oder

```bash
bash run_scanner.sh
```

Review-Queue anzeigen:

```bash
python3 investment_scanner.py --list-review-queue
```

Deal markieren:

```bash
python3 investment_scanner.py \
  --review-link "https://example.com/deal" \
  --review-status interessant \
  --review-note "Nur bei belastbarer Vermietung weiter prüfen"
```

## Output

Das Repo erzeugt Report-Dateien unter `output/YYYY-MM-DD/`, sofern der Scanner erfolgreich durchlaeuft.

Der HTML-Report enthaelt zusaetzlich:

- Review-Zusammenfassung mit offenen / interessanten / nachzufassenden / ignorierten Deals
- offene Review-Queue fuer Operatoren
- Review-Status und Notiz direkt in den Deal-Tabellen

## Cron

```cron
# Taeglich 06:00 UTC
0 6 * * * cd /home/claude-agent/investment-scanner && /usr/bin/python3 investment_scanner.py >> logs/scanner.log 2>&1
```

## Unified Dashboard

Eingebunden unter `https://agents.umzwei.de/dashboard/invest/`.
