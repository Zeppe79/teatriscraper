from __future__ import annotations

import logging
from datetime import datetime

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.teatrodivillazzano.it"
ARCHIVE_URL = f"{BASE_URL}/archivio/"

VENUE = "Teatro di Villazzano"
LOCATION = "Trento"


class TeatroDiVillazzanoScraper(BaseScraper):
    name = "teatrodivillazzano.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        url: str | None = ARCHIVE_URL
        while url:
            try:
                resp = self.fetch(url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {url}")
                break

            for card in soup.select(".gt-event-style-3"):
                ev = self._parse_card(card)
                if ev and ev.source_url not in seen_urls:
                    seen_urls.add(ev.source_url)
                    events.append(ev)

            # Pagination: .gt-pagination a contains "Successivo"
            next_el = soup.select_one(".gt-pagination a")
            url = next_el.get("href") if next_el else None

            if len(events) > 200:
                break

        return events

    def _parse_card(self, card) -> Event | None:
        try:
            title_el = card.select_one(".gt-title a")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            source_url = title_el.get("href", "")

            date_el = card.select_one(".gt-date.gt-start-date span")
            if not date_el:
                return None
            date_text = date_el.get_text(strip=True)  # "18/04/2026"
            try:
                event_date = datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
            except ValueError:
                return None

            time_el = card.select_one(".gt-time.gt-start-time span")
            time_str = time_el.get_text(strip=True) if time_el else None  # "20:30"

            loc_el = card.select_one(".gt-location ul li a")
            venue = loc_el.get_text(strip=True) if loc_el else VENUE

            img_el = card.select_one(".gt-image img")
            image_url = img_el.get("src") if img_el else None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue or VENUE,
                location=LOCATION,
                source_url=source_url,
                source_name=self.name,
                description=None,
                image_url=image_url,
            )
        except Exception:
            logger.warning(f"[{self.name}] Failed to parse card")
            return None
