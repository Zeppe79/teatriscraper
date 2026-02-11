from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.crushsite.it"
LISTING_URL = f"{BASE_URL}/it/soggetti/danza-teatro/"

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

DATE_RE = re.compile(
    r"(\d{1,2})\s+([a-zA-Zàèéìòùáí]+)\s+(\d{4})"
    r"(?:.*?ore\s+(\d{1,2})[.:](\d{2}))?",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")


class CrushsiteScraper(BaseScraper):
    name = "crushsite.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        url: str | None = LISTING_URL
        while url:
            try:
                resp = self.fetch(url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {url}")
                break

            page_events = self._parse_page(soup, seen_urls)
            events.extend(page_events)

            url = self._next_page_url(soup)
            if len(events) > 300:
                break

        return events

    def _parse_page(self, soup: BeautifulSoup, seen_urls: set) -> list[Event]:
        events = []

        # 1. Try JSON-LD structured data (most reliable)
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    t = item.get("@type", "")
                    if t in ("Event", "TheaterEvent", "DanceEvent", "MusicEvent"):
                        ev = self._parse_jsonld(item)
                        if ev and ev.source_url not in seen_urls:
                            seen_urls.add(ev.source_url)
                            events.append(ev)
            except Exception:
                pass

        if events:
            return events

        # 2. Try event card selectors (custom CMS patterns)
        for selector in [
            ".evento", ".card-evento", ".event-item", ".show-item",
            ".spettacolo", ".event", "article.event", ".listing-item",
            ".box-evento", ".item-evento",
        ]:
            cards = soup.select(selector)
            for card in cards:
                ev = self._parse_card(card)
                if ev and ev.source_url not in seen_urls:
                    seen_urls.add(ev.source_url)
                    events.append(ev)
            if events:
                return events

        # 3. Generic article/list item fallback
        for art in soup.select("article, .post, li.event-item"):
            ev = self._parse_generic(art)
            if ev and ev.source_url not in seen_urls:
                seen_urls.add(ev.source_url)
                events.append(ev)

        return events

    def _parse_jsonld(self, item: dict) -> Event | None:
        try:
            title = item.get("name", "").strip()
            if not title:
                return None

            start = item.get("startDate", "")
            if not start:
                return None

            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                event_date = dt.date().isoformat()
                time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
            except ValueError:
                return None

            location_data = item.get("location", {})
            venue, city = "", ""
            if isinstance(location_data, dict):
                venue = location_data.get("name", "")
                addr = location_data.get("address", {})
                if isinstance(addr, dict):
                    city = addr.get("addressLocality", "")
            elif isinstance(location_data, str):
                venue = location_data

            source_url = item.get("url", item.get("@id", ""))
            if source_url and not source_url.startswith("http"):
                source_url = BASE_URL + source_url

            description = item.get("description") or None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location=city,
                source_url=source_url,
                source_name=self.name,
                description=description,
            )
        except Exception:
            return None

    def _parse_card(self, card) -> Event | None:
        try:
            # Title and link
            title_el = card.select_one(
                "h2 a, h3 a, h4 a, .title a, .titolo a, "
                ".event-title a, .nome a, a.event-link"
            )
            if not title_el:
                title_el = card.select_one("h2, h3, h4, .title, .titolo")
            if not title_el:
                return None

            title = title_el.get_text(strip=True)
            if not title:
                return None

            a_el = card.find("a")
            href = a_el.get("href", "") if a_el else ""
            source_url = href if href.startswith("http") else (BASE_URL + href if href else "")

            # Date
            event_date, time_str = self._extract_date_and_time(card)
            if not event_date:
                return None

            # Venue and location
            venue_el = card.select_one(".venue, .luogo, .teatro, .sala, .location-name")
            venue = venue_el.get_text(strip=True) if venue_el else ""

            location_el = card.select_one(".city, .comune, .citta, .città, .location-city")
            location = location_el.get_text(strip=True) if location_el else ""

            # Description
            desc_el = card.select_one(".description, .descrizione, .excerpt, p")
            description = desc_el.get_text(strip=True) if desc_el else None
            if description == title:
                description = None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location=location,
                source_url=source_url,
                source_name=self.name,
                description=description,
            )
        except Exception:
            return None

    def _parse_generic(self, el) -> Event | None:
        try:
            title_el = el.select_one("h2 a, h3 a, .entry-title a")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            source_url = href if href.startswith("http") else BASE_URL + href

            # Try time[datetime] first
            time_el = el.select_one("time[datetime]")
            if time_el:
                dt_str = time_el.get("datetime", "")
                try:
                    dt = datetime.fromisoformat(dt_str)
                    event_date = dt.date().isoformat()
                    time_str = None
                    return Event(
                        title=title,
                        date=event_date,
                        time=time_str,
                        venue="",
                        location="",
                        source_url=source_url,
                        source_name=self.name,
                        description=None,
                    )
                except ValueError:
                    pass

            event_date, time_str = self._extract_date_and_time(el)
            if not event_date:
                return None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue="",
                location="",
                source_url=source_url,
                source_name=self.name,
                description=None,
            )
        except Exception:
            return None

    def _extract_date_and_time(self, el) -> tuple[str | None, str | None]:
        """Try multiple strategies to extract date and time from an element."""
        # 1. time[datetime] attribute
        time_tag = el.select_one("time[datetime]")
        if time_tag:
            dt_str = time_tag.get("datetime", "")
            try:
                dt = datetime.fromisoformat(dt_str)
                event_date = dt.date().isoformat()
                time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
                return event_date, time_str
            except ValueError:
                # Maybe just a date
                try:
                    d = date.fromisoformat(dt_str[:10])
                    return d.isoformat(), None
                except ValueError:
                    pass

        # 2. meta itemprop date
        meta_date = el.select_one("meta[itemprop='startDate'], meta[itemprop='datePublished']")
        if meta_date:
            content = meta_date.get("content", "")
            try:
                dt = datetime.fromisoformat(content.replace("Z", "+00:00"))
                event_date = dt.date().isoformat()
                time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
                return event_date, time_str
            except ValueError:
                pass

        # 3. Italian date in text
        text = el.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if m:
            day_s, month_name, year_s = m.group(1), m.group(2), m.group(3)
            hour_s, min_s = m.group(4), m.group(5)
            month = ITALIAN_MONTHS.get(month_name.lower())
            if month:
                try:
                    event_date = date(int(year_s), month, int(day_s)).isoformat()
                    time_str = f"{int(hour_s):02d}:{min_s}" if hour_s and min_s else None
                    return event_date, time_str
                except ValueError:
                    pass

        # 4. ISO date in text or data attributes
        iso_m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if iso_m:
            event_date = iso_m.group(1)
            t = TIME_RE.search(text[iso_m.end():])
            time_str = f"{int(t.group(1)):02d}:{t.group(2)}" if t else None
            return event_date, time_str

        return None, None

    @staticmethod
    def _next_page_url(soup: BeautifulSoup) -> str | None:
        el = soup.select_one(
            "a.next, a.next-page, a[rel='next'], "
            ".pagination a.next, .pager-next a, "
            "a.page-next, li.next a"
        )
        if el:
            href = el.get("href", "")
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                return BASE_URL + href
        return None
