"""Scraper-Module fuer den Investment Scanner."""

from .kleinanzeigen import scrape_kleinanzeigen
from .dga import scrape_dga
from .zvg import scrape_zvg
from .bergfuerst import scrape_bergfuerst
from .wiwin import scrape_wiwin
from .bettervest import scrape_bettervest
from .exporo import scrape_exporo

__all__ = [
    "scrape_kleinanzeigen",
    "scrape_dga",
    "scrape_zvg",
    "scrape_bergfuerst",
    "scrape_wiwin",
    "scrape_bettervest",
    "scrape_exporo",
]
