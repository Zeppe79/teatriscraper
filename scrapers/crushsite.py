from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

URL = "https://www.crushsite.it/it/soggetti/danza-teatro/"


class CrushsiteScraper(BaseScraper):
    name = "crushsite.it"

    def scrape(self) -> list[Event]:
        # TODO: implement after inspecting live HTML structure
        # May include dance-only events - need to filter or keep both
        logger.info(f"[{self.name}] Scraper not yet implemented")
        return []
