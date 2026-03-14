# Investment Scanner

## Ueberblick

Kompakte Variante des Investment-Scanners fuer Grundstuecke und Crowdfunding-Deals. Das Repo konzentriert sich auf die Einzeldatei-Implementierung mit Report-Ausgabe und einfachem Wrapper-Skript.

## Zweck

- Guenstige Grundstuecksangebote aggregieren
- Crowdfunding-Projekte nach Mindestrendite filtern
- Ergebnisse als HTML- und CSV-Report bereitstellen

## Bestandteile

- `investment_scanner.py`
  - Hauptlogik fuer Scan und Report
- `run_scanner.sh`
  - Wrapper fuer den periodischen Betrieb
- `send_report.py`
  - E-Mail-Versand

## Voraussetzungen

- Python 3.10+
- `requests`
- `beautifulsoup4`

## Einrichtung

```bash
cd /home/claude-agent/investment_scanner
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

## Output

Das Repo erzeugt Report-Dateien unter `output/YYYY-MM-DD/`, sofern der Scanner erfolgreich durchlaeuft.

## Betriebshinweise

- Diese Variante ist die schlankere Einzelrepo-Ausfuehrung ohne weitergehende Dokuordner
- Fuer produktiven Betrieb sollte ein gemeinsamer, dokumentierter Credential- und Cron-Standard verwendet werden

## Status

Leichte Einzeldatei-Variante des Investment-Scanners.
