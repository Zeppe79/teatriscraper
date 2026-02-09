from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Joomla blog_calendar component
CALENDAR_URL = "https://www.teatrodipergine.it/component/blog_calendar/{year}/{month:02d}/{day:02d}?Itemid="
SEASON_URL = "https://www.teatrodipergine.it/stagione-2013-2014-3"


class TeatroDiPergineScraper(BaseScraper):
    name = "teatrodipergine.it"

    def scrape(self) -> list[Event]:
        # TODO: implement after inspecting live HTML structure
        # Two possible approaches:
        # 1. Parse the season page for all listed events
        # 2. Iterate blog_calendar by month to find event dates
        logger.info(f"[{self.name}] Scraper not yet implemented")
        return []
