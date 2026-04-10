"""Zentrale Konfiguration — laedt config.yaml und stellt Werte bereit."""

import re
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

with open(_CONFIG_PATH, encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)

# Grundstuecke
MAX_PRICE: int = _cfg.get("max_price", 50_000)
REGIONS: list[str] = _cfg.get("regions", ["berlin", "brandenburg", "sachsen"])

# Crowdfunding
MIN_RENDITE: float = _cfg.get("min_rendite", 4.0)

# Scraping
PAUSE_S: float = _cfg.get("pause_seconds", 1.5)

# DGA
DGA_COMPANIES: dict[str, str] = _cfg.get("dga_companies", {})
DGA_CATEGORIES: dict[str, str] = _cfg.get("dga_categories", {})

# ZVG
ZVG_BUNDESLAENDER: dict[str, str] = _cfg.get("zvg_bundeslaender", {})

# KI-Scoring (Ollama)
_ollama = _cfg.get("ollama", {})
OLLAMA_URL: str = _ollama.get("url", "http://172.28.0.20:11434")
OLLAMA_MODEL: str = _ollama.get("model", "gemma4:e4b")
SCORING_BATCH_SIZE: int = _ollama.get("batch_size", 20)
OLLAMA_TIMEOUT: int = _ollama.get("timeout", 120)
OLLAMA_PAUSE: int = _ollama.get("pause", 2)

# Abgeleitete Regex aus Regionen-Liste
REGION_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(r) for r in REGIONS) + r")\b",
    re.IGNORECASE,
)

# HTTP-Headers
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
