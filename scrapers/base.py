from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from models import Event

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 30


class BaseScraper(ABC):
    """Base class for all theater event scrapers."""

    name: str = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response

    @abstractmethod
    def scrape(self) -> list[Event]:
        """Scrape events from the source. Must be implemented by subclasses."""

    def run(self) -> list[Event]:
        """Run the scraper with error handling."""
        try:
            events = self.scrape()
            logger.info(f"[{self.name}] Scraped {len(events)} events")
            return events
        except Exception:
            logger.exception(f"[{self.name}] Scraping failed")
            return []
