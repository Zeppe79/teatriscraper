from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

URL = "https://www.trentinospettacoli.it/tag_eventi/teatro/"


class TrentinoSpettacoliScraper(BaseScraper):
    name = "trentinospettacoli.it"

    def scrape(self) -> list[Event]:
        # TODO: implement after inspecting live HTML structure
        # WordPress tag archive, likely paginated (/tag_eventi/teatro/page/2/)
        logger.info(f"[{self.name}] Scraper not yet implemented")
        return []
