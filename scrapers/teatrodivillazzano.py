from __future__ import annotations

import logging
from datetime import datetime

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.teatrodivillazzano.it"
# Blank-search endpoint returns all posts (shows) sorted newest-first.
# Pagination: /page/N/?s=
SEARCH_URL = f"{BASE_URL}/page/{{page}}/?s="

VENUE = "Teatro di Villazzano"
LOCATION = "Trento"
MAX_PAGES = 5


class TeatroDiVillazzanoScraper(BaseScraper):
    name = "teatrodivillazzano.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            url = SEARCH_URL.format(page=page)
            try:
                resp = self.fetch(url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {url}")
                break

            cards = soup.select(".gt-post-style-1")
            if not cards:
                break  # no more pages

            for card in cards:
                ev = self._parse_card(card)
                if ev and ev.source_url not in seen_urls:
                    seen_urls.add(ev.source_url)
                    events.append(ev)

        return events

    def _parse_card(self, card) -> Event | None:
        try:
            title_el = card.select_one(".gt-title a")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            source_url = title_el.get("href", "")

            # Post publication date — "09/12/2025" (DD/MM/YYYY)
            date_el = card.select_one("li.gt-date")
            if not date_el:
                return None
            date_text = date_el.get_text(strip=True)
            try:
                event_date = datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
            except ValueError:
                return None

            img_el = card.select_one(".gt-image img")
            image_url = img_el.get("src") if img_el else None

            excerpt_el = card.select_one(".gt-excerpt")
            description = excerpt_el.get_text(strip=True) if excerpt_el else None

            return Event(
                title=title,
                date=event_date,
                time=None,
                venue=VENUE,
                location=LOCATION,
                source_url=source_url,
                source_name=self.name,
                description=description,
                image_url=image_url,
            )
        except Exception:
            logger.warning(f"[{self.name}] Failed to parse card")
            return None
