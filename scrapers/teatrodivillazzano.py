from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

URL = "https://www.teatrodivillazzano.it/archivio/"


class TeatroDiVillazzanoScraper(BaseScraper):
    name = "teatrodivillazzano.it"

    def scrape(self) -> list[Event]:
        # TODO: implement after inspecting live HTML structure
        # WordPress archive, likely paginated (/archivio/page/2/)
        # Expected: post listing with date and title per entry
        logger.info(f"[{self.name}] Scraper not yet implemented")
        return []
