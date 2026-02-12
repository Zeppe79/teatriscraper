from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.teatrodivillazzano.it"
ARCHIVE_URL = f"{BASE_URL}/archivio/"
# The Events Calendar REST API endpoint
TEC_API_URL = f"{BASE_URL}/wp-json/tribe/events/v1/events"

VENUE = "Teatro di Villazzano"
LOCATION = "Trento"


class TeatroDiVillazzanoScraper(BaseScraper):
    name = "teatrodivillazzano.it"

    def scrape(self) -> list[Event]:
        # Try The Events Calendar REST API first (most structured)
        events = self._scrape_api()
        if events:
            return events

        # Fall back to HTML parsing
        return self._scrape_html()

    # ------------------------------------------------------------------
    # REST API approach (The Events Calendar plugin)
    # ------------------------------------------------------------------

    def _scrape_api(self) -> list[Event]:
        events: list[Event] = []
        today_str = date.today().isoformat()
        page = 1
        while True:
            try:
                resp = self.fetch(
                    TEC_API_URL,
                    params={
                        "start_date": today_str,
                        "per_page": 50,
                        "page": page,
                    },
                )
                data = resp.json()
            except Exception:
                # API not available or returned non-JSON
                return []

            for ev in data.get("events", []):
                parsed = self._parse_api_event(ev)
                if parsed:
                    events.append(parsed)

            next_url = data.get("next", "")
            if not next_url or not data.get("events"):
                break
            page += 1

        return events

    def _parse_api_event(self, ev: dict) -> Event | None:
        try:
            title = ev.get("title", "").strip()
            if not title:
                return None

            start_dt = ev.get("start_date", "")  # "2026-03-15 20:30:00"
            if not start_dt:
                return None

            dt = datetime.fromisoformat(start_dt)
            event_date = dt.date().isoformat()
            time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None

            # Venue from API
            venue_data = ev.get("venue", {})
            venue = venue_data.get("venue", VENUE) if venue_data else VENUE
            location = venue_data.get("city", LOCATION) if venue_data else LOCATION

            source_url = ev.get("url", "")
            description = ev.get("excerpt", {}).get("rendered", "") or None

            # Image from API response
            img_data = ev.get("image", {})
            image_url = img_data.get("url", "") if isinstance(img_data, dict) else ""

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue or VENUE,
                location=location or LOCATION,
                source_url=source_url,
                source_name=self.name,
                description=self._strip_html(description) if description else None,
                image_url=image_url or None,
            )
        except Exception:
            logger.warning(f"[{self.name}] Failed to parse API event")
            return None

    # ------------------------------------------------------------------
    # HTML fallback (archive page with paginated posts)
    # ------------------------------------------------------------------

    def _scrape_html(self) -> list[Event]:
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

            # Try JSON-LD structured data first
            for script in soup.find_all("script", {"type": "application/ld+json"}):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") == "Event":
                            ev = self._parse_jsonld(item)
                            if ev and ev.source_url not in seen_urls:
                                seen_urls.add(ev.source_url)
                                events.append(ev)
                except Exception:
                    pass

            # If JSON-LD produced events, no need to parse HTML cards
            if events:
                break

            # Try The Events Calendar HTML selectors
            new_events = self._parse_tec_html(soup, seen_urls)
            if not new_events:
                # Try generic WordPress post list
                new_events = self._parse_wp_posts(soup, seen_urls)

            events.extend(new_events)

            # Pagination: look for "next page" link
            url = self._next_page_url(soup)
            if len(events) > 200:  # safety cap
                break

        return events

    def _parse_jsonld(self, item: dict) -> Event | None:
        try:
            title = item.get("name", "").strip()
            if not title:
                return None

            start = item.get("startDate", "")
            if not start:
                return None

            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            event_date = dt.date().isoformat()
            time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None

            location_data = item.get("location", {})
            venue = location_data.get("name", VENUE) if isinstance(location_data, dict) else VENUE
            city = ""
            if isinstance(location_data, dict):
                addr = location_data.get("address", {})
                city = addr.get("addressLocality", LOCATION) if isinstance(addr, dict) else LOCATION

            source_url = item.get("url", item.get("@id", ""))
            description = item.get("description", None)

            img_data = item.get("image", None)
            if isinstance(img_data, dict):
                image_url = img_data.get("url", img_data.get("@id", "")) or None
            elif isinstance(img_data, str):
                image_url = img_data or None
            else:
                image_url = None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue or VENUE,
                location=city or LOCATION,
                source_url=source_url,
                source_name=self.name,
                description=description,
                image_url=image_url,
            )
        except Exception:
            return None

    def _parse_tec_html(self, soup: BeautifulSoup, seen_urls: set) -> list[Event]:
        """Parse The Events Calendar HTML structure."""
        events = []
        # TEC article elements
        articles = soup.select("article.type-tribe_events, article.tribe_events")
        for art in articles:
            ev = self._parse_tec_article(art)
            if ev and ev.source_url not in seen_urls:
                seen_urls.add(ev.source_url)
                events.append(ev)
        return events

    def _parse_tec_article(self, art) -> Event | None:
        try:
            # Title
            title_el = (
                art.select_one(".tribe-events-list-event-title a")
                or art.select_one(".tribe-event-title a")
                or art.select_one("h2 a, h3 a")
            )
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            source_url = title_el.get("href", "")
            if source_url.startswith("/"):
                source_url = BASE_URL + source_url

            # Date/time
            time_el = (
                art.select_one("abbr.tribe-events-abbr")
                or art.select_one("time[datetime]")
                or art.select_one(".tribe-event-date-start")
            )
            event_date, time_str = self._parse_tec_datetime(time_el)
            if not event_date:
                return None

            # Venue
            venue_el = art.select_one(".tribe-venue")
            venue = venue_el.get_text(strip=True) if venue_el else VENUE

            img_el = art.select_one(".tribe-events-event-image img, .tribe-event-featured-image img, img")
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
            return None

    def _parse_tec_datetime(self, el) -> tuple[str | None, str | None]:
        if not el:
            return None, None
        # Try datetime attribute (ISO)
        dt_attr = el.get("datetime", "") or el.get("title", "")
        if dt_attr:
            try:
                dt = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                event_date = dt.date().isoformat()
                time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
                return event_date, time_str
            except ValueError:
                pass
        # Try text content
        text = el.get_text(strip=True)
        return self._parse_date_from_text(text)

    def _parse_wp_posts(self, soup: BeautifulSoup, seen_urls: set) -> list[Event]:
        """Parse generic WordPress post listing."""
        events = []
        for art in soup.select("article.post, article.type-post, .post"):
            title_el = art.select_one("h2 a, h1 a, .entry-title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            source_url = href if href.startswith("http") else BASE_URL + href

            time_el = art.select_one("time[datetime]")
            if time_el:
                dt_str = time_el.get("datetime", "")
                try:
                    event_date = datetime.fromisoformat(dt_str).date().isoformat()
                except Exception:
                    continue
            else:
                continue

            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

            img_el = art.select_one("img")
            image_url = img_el.get("src") if img_el else None

            events.append(Event(
                title=title,
                date=event_date,
                time=None,
                venue=VENUE,
                location=LOCATION,
                source_url=source_url,
                source_name=self.name,
                description=None,
                image_url=image_url,
            ))
        return events

    @staticmethod
    def _next_page_url(soup: BeautifulSoup) -> str | None:
        """Find the URL of the next page."""
        el = soup.select_one("a.next.page-numbers, .tribe-events-nav-next a, a[rel='next']")
        if el:
            href = el.get("href", "")
            return href if href.startswith("http") else None
        return None

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text).strip()

    @staticmethod
    def _parse_date_from_text(text: str) -> tuple[str | None, str | None]:
        """Try to extract ISO date and HH:MM from arbitrary text."""
        # ISO date pattern
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if m:
            event_date = m.group(1)
            t = re.search(r"(\d{1,2}):(\d{2})", text)
            time_str = f"{int(t.group(1)):02d}:{t.group(2)}" if t else None
            return event_date, time_str
        return None, None
