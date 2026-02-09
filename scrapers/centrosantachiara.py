from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

URL = "https://www.centrosantachiara.it/spettacoli/calendariospettacoli"


class CentroSantaChiaraScraper(BaseScraper):
    name = "centrosantachiara.it"

    def scrape(self) -> list[Event]:
        # TODO: implement after inspecting live HTML structure
        # Expected approach:
        # 1. Fetch URL
        # 2. Parse event cards with BeautifulSoup
        # 3. Extract title, date, time, venue from each card
        logger.info(f"[{self.name}] Scraper not yet implemented")
        return []
