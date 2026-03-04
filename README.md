# Investment Scanner

Aggregiert Grundstücke und Crowdfunding-Beteiligungen aus mehreren Quellen und erstellt einen HTML-Report.

## Was es macht

- Scrapet Grundstücke bis max. 50.000 € in Berlin, Brandenburg, Mecklenburg-Vorpommern, Sachsen und Sachsen-Anhalt
- Aggregiert Crowdfunding-Projekte mit mind. 4 % Rendite p.a.
- Erstellt einen HTML-Report mit Summary-Cards, Tabellen und Nutzungsideen

## Quellen

| Kategorie | Quelle |
|-----------|--------|
| Grundstücke | Kleinanzeigen.de, DGA (Deutsche Grundstücksauktionen), ZVG (Zwangsversteigerungen) |
| Crowdfunding | Bergfürst, Wiwin, Bettervest, Exporo |

## Nutzungsideen (regelbasiert)

| Grundstück | Idee |
|-----------|------|
| Wiese/Acker > 2.000 m² | PV-Anlage (Pacht/Eigen) |
| Wiese/Acker ≤ 2.000 m² | Kleingarten, Freizeitgrundstück |
| Wald | Holzertrag, Erholungswald |
| Bauland | Tiny House, Ferienwohnung |
| Günstig, sonstig | Stellplatz, Lagerplatz |

## Installation

```bash
pip install requests beautifulsoup4
```

## Ausführung

```bash
python3 investment_scanner.py
```

Oder mit Log-Datei:

```bash
bash run_scanner.sh
```

## Output

```
output/YYYY-MM-DD/
├── investments.html   # HTML-Report mit Summary und Tabellen
└── investments.csv    # Alle Einträge als CSV
```

## Report per E-Mail

Credentials in `~/.stock_scanner_credentials`:

```
GMAIL_USER=...
GMAIL_APP_PASSWORD=...
GMAIL_RECIPIENT=...
```

```bash
python3 send_report.py
```

## Konfiguration

In `investment_scanner.py`:

```python
MAX_PRICE   = 50_000   # € Maximalpreis Grundstücke
MIN_RENDITE = 4.0      # % p.a. Mindestrendite Crowdfunding
```
