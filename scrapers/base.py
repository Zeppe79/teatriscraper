from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

import requests

from models import Event

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

REQUEST_TIMEOUT = 10
RETRY_DELAYS = (5, 15)  # seconds between attempts 1→2, 2→3


class BaseScraper(ABC):
    """Base class for all theater event scrapers."""

    name: str = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0] + list(RETRY_DELAYS), start=1):
            if delay:
                logger.debug(f"[{self.name}] Retry {attempt} for {url} (wait {delay}s)")
                time.sleep(delay)
            try:
                response = self.session.get(url, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as exc:
                # 4xx errors won't improve with retries
                if exc.response is not None and exc.response.status_code < 500:
                    raise
                last_exc = exc
            except requests.exceptions.Timeout:
                # Connect or read timeout — retrying won't help if site blocks CI IPs
                raise
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    @abstractmethod
    def scrape(self) -> list[Event]:
        """Scrape events from the source. Must be implemented by subclasses."""

    def run(self) -> list[Event]:
        """Run the scraper with error handling."""
        logger.info(f"[{self.name}] Starting...")
        try:
            events = self.scrape()
            logger.info(f"[{self.name}] Scraped {len(events)} events")
            return events
        except Exception:
            logger.exception(f"[{self.name}] Scraping failed")
            return []
