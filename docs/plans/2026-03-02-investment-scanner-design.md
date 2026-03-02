# Design: Investment Opportunity Scanner

**Datum:** 2026-03-02

---

## Ziel

Ein manuell ausführbares Python-Script das Grundstücke und Crowdfunding-Beteiligungen
aus mehreren Quellen aggregiert und als HTML-Report darstellt.

---

## Rahmenbedingungen

- **Budget:** max. 50.000 €
- **Regionen:** Berlin, Brandenburg, Mecklenburg-Vorpommern, Sachsen, Sachsen-Anhalt
- **Split:** ~50% physische Assets (Grundstücke), ~50% Finanzbeteiligungen
- **Betrieb:** manuell (`python3 investment_scanner.py`), kein Cron

---

## Datenquellen

### Grundstücke (physisch)

| Quelle | URL | Was |
|--------|-----|-----|
| Kleinanzeigen.de | kleinanzeigen.de/s-grundstuecke | Acker, Wald, Bauland, Freizeitgrundstücke |
| Deutsche Grundstücksauktionen | dga.de | Auktionen, oft unter Marktwert |
| Zwangsversteigerungstermine.de | zwangsversteigerungstermine.de | Zwangsversteigerungen |

### Beteiligungen & Crowdfunding

| Plattform | URL | Fokus |
|-----------|-----|-------|
| Bettervest | bettervest.com | PV, Energie |
| Bergfürst | bergfuerst.com | Immobilien |
| Wiwin | wiwin.de | Nachhaltig, PV |
| Exporo | exporo.de | Immobilien |

---

## Konfiguration

```python
MAX_PRICE   = 50_000   # € Maximalpreis Grundstücke
REGIONS     = ["Berlin", "Brandenburg", "Mecklenburg", "Sachsen", "Sachsen-Anhalt"]
MIN_RENDITE = 4.0      # % p.a. Mindestrendite Crowdfunding
```

---

## Nutzungsideen (regelbasiert)

| Kriterium | Nutzungsidee |
|-----------|-------------|
| Ackerland/Wiese > 2.000 m² | PV-Anlage (Pacht/Eigen) |
| Ackerland/Wiese ≤ 2.000 m² | Kleingarten, Freizeitgrundstück |
| Wald | Holzertrag, Erholungswald |
| Bauland | Tiny House, Ferienwohnung |
| Sonstige, günstig | Stellplatz, Lagerplatz, Automatenstandort |

---

## Scraping-Strategie

- `requests` + `BeautifulSoup4` — kein Selenium
- Browser User-Agent Header
- 1–2 Sekunden Pause zwischen Requests
- Timeout 15s pro Request
- Fehler pro Quelle: überspringen + Warnung im Report

---

## Output

### Projektstruktur

```
investment_scanner/
├── investment_scanner.py
├── run_scanner.sh
├── output/YYYY-MM-DD/
│   ├── investments.html
│   └── investments.csv
└── logs/
```

### HTML-Report

**Summary-Cards:** Grundstücke gesamt | Ø €/m² | Beteiligungen gesamt | Beste Rendite

**Sektion 1 — 🏡 Grundstücke**
Spalten: Quelle | Titel | Ort | Größe | Preis | €/m² | Nutzungsidee | Link

**Sektion 2 — 💰 Beteiligungen & Crowdfunding**
Spalten: Plattform | Projekt | Typ | Rendite p.a. | Laufzeit | Mindestanlage | Status | Link

### CSV-Export

Alle Einträge in einer Datei, Spalte `Kategorie` unterscheidet `Grundstück` / `Beteiligung`.
