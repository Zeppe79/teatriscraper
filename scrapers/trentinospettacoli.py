from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.trentinospettacoli.it"
TAG_URL = f"{BASE_URL}/tag_eventi/teatro/"
# WP REST API endpoints to try
WP_API_EVENTI = f"{BASE_URL}/wp-json/wp/v2/eventi"
WP_API_POSTS = f"{BASE_URL}/wp-json/wp/v2/posts"

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Date patterns commonly found in Italian event descriptions
DATE_RE = re.compile(
    r"(\d{1,2})\s+([a-zA-Zàèéìòùáí]+)\s+(\d{4})"
    r"(?:.*?ore\s+(\d{1,2})[.:](\d{2}))?",
    re.IGNORECASE,
)


class TrentinoSpettacoliScraper(BaseScraper):
    name = "trentinospettacoli.it"

    def scrape(self) -> list[Event]:
        # Try WP REST API for custom post type first
        events = self._scrape_api()
        if events:
            return events

        # Fall back to HTML scraping of tag archive
        return self._scrape_html()

    # ------------------------------------------------------------------
    # WP REST API
    # ------------------------------------------------------------------

    def _scrape_api(self) -> list[Event]:
        """Try WP REST API for 'eventi' custom post type."""
        today_str = date.today().isoformat()
        for endpoint in [WP_API_EVENTI, WP_API_POSTS]:
            events = self._fetch_api_endpoint(endpoint, today_str)
            if events:
                return events
        return []

    def _fetch_api_endpoint(self, endpoint: str, today_str: str) -> list[Event]:
        events: list[Event] = []
        page = 1
        while True:
            try:
                resp = self.fetch(
                    endpoint,
                    params={
                        "per_page": 100,
                        "page": page,
                        "after": today_str,
                        "_fields": "id,title,date,link,excerpt,acf,meta,_embedded",
                        "_embed": "wp:featuredmedia",
                    },
                )
                items = resp.json()
                if not isinstance(items, list) or not items:
                    break
            except Exception:
                return []

            for item in items:
                ev = self._parse_api_item(item)
                if ev:
                    events.append(ev)

            # Check if there are more pages
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1

        return events

    def _parse_api_item(self, item: dict) -> Event | None:
        try:
            raw_title = item.get("title", {})
            title = (raw_title.get("rendered", "") if isinstance(raw_title, dict) else str(raw_title)).strip()
            title = re.sub(r"<[^>]+>", "", title)
            if not title:
                return None

            source_url = item.get("link", "")

            # Date: try ACF fields first, then post date
            acf = item.get("acf", {}) or {}
            event_date_str = (
                acf.get("data_evento")
                or acf.get("start_date")
                or acf.get("date")
                or item.get("date", "")
            )
            time_raw = acf.get("ora_inizio") or acf.get("time") or ""

            if not event_date_str:
                return None

            try:
                dt = datetime.fromisoformat(event_date_str.replace("Z", "+00:00"))
                event_date = dt.date().isoformat()
                time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
            except ValueError:
                return None

            if time_raw and not time_str:
                m = re.search(r"(\d{1,2})[.:](\d{2})", str(time_raw))
                if m:
                    time_str = f"{int(m.group(1)):02d}:{m.group(2)}"

            venue = acf.get("luogo") or acf.get("venue") or acf.get("teatro") or ""
            location = acf.get("comune") or acf.get("city") or acf.get("location") or ""

            excerpt = item.get("excerpt", {})
            description = (excerpt.get("rendered", "") if isinstance(excerpt, dict) else "") or None
            if description:
                description = re.sub(r"<[^>]+>", "", description).strip() or None

            # Featured image from _embedded
            image_url = None
            embedded = item.get("_embedded", {}) or {}
            featured = embedded.get("wp:featuredmedia", [{}])
            if featured and isinstance(featured[0], dict):
                image_url = featured[0].get("source_url") or None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location=location,
                source_url=source_url,
                source_name=self.name,
                description=description,
                image_url=image_url,
            )
        except Exception:
            logger.warning(f"[{self.name}] Failed to parse API item")
            return None

    # ------------------------------------------------------------------
    # HTML scraping
    # ------------------------------------------------------------------

    def _scrape_html(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        url: str | None = TAG_URL
        while url:
            try:
                resp = self.fetch(url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {url}")
                break

            # Try JSON-LD structured data
            page_had_jsonld = False
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
                                page_had_jsonld = True
                except Exception:
                    pass

            if not page_had_jsonld:
                new_events = self._parse_event_cards(soup, seen_urls)
                if not new_events:
                    new_events = self._parse_wp_posts(soup, seen_urls)
                events.extend(new_events)

            url = self._next_page_url(soup)
            if len(events) > 300:
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
            venue = ""
            city = ""
            if isinstance(location_data, dict):
                venue = location_data.get("name", "")
                addr = location_data.get("address", {})
                if isinstance(addr, dict):
                    city = addr.get("addressLocality", "")

            source_url = item.get("url", item.get("@id", ""))
            description = item.get("description") or None

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
                venue=venue,
                location=city,
                source_url=source_url,
                source_name=self.name,
                description=description,
                image_url=image_url,
            )
        except Exception:
            return None

    def _parse_event_cards(self, soup: BeautifulSoup, seen_urls: set) -> list[Event]:
        """Try selectors specific to trentinospettacoli.it event cards."""
        events = []
        # Try common event card selectors
        for card in soup.select(".evento, .event-item, .event-card, article.event, .spettacolo"):
            ev = self._parse_card(card)
            if ev and ev.source_url not in seen_urls:
                seen_urls.add(ev.source_url)
                events.append(ev)
        return events

    def _parse_card(self, card) -> Event | None:
        try:
            title_el = card.select_one("h2 a, h3 a, .event-title a, .title a, a")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            source_url = href if href.startswith("http") else BASE_URL + href

            # Date from time element or content
            time_el = card.select_one("time[datetime]")
            if time_el:
                dt_str = time_el.get("datetime", "")
                try:
                    dt = datetime.fromisoformat(dt_str)
                    event_date = dt.date().isoformat()
                    time_str = f"{dt.hour:02d}:{dt.minute:02d}" if (dt.hour or dt.minute) else None
                except ValueError:
                    return None
            else:
                # Try to find date in text content
                text = card.get_text(" ", strip=True)
                event_date, time_str = self._extract_date_from_text(text)
                if not event_date:
                    return None

            venue_el = card.select_one(".venue, .luogo, .teatro")
            venue = venue_el.get_text(strip=True) if venue_el else ""

            location_el = card.select_one(".location, .comune, .city")
            location = location_el.get_text(strip=True) if location_el else ""

            img_el = card.select_one("img")
            image_url = img_el.get("src") if img_el else None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location=location,
                source_url=source_url,
                source_name=self.name,
                description=None,
                image_url=image_url,
            )
        except Exception:
            return None

    def _parse_wp_posts(self, soup: BeautifulSoup, seen_urls: set) -> list[Event]:
        """Generic WordPress post listing fallback."""
        events = []
        for art in soup.select("article"):
            title_el = art.select_one(".entry-title a, h2 a, h3 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            source_url = href if href.startswith("http") else BASE_URL + href

            time_el = art.select_one("time[datetime]")
            if not time_el:
                continue
            dt_str = time_el.get("datetime", "")
            try:
                dt = datetime.fromisoformat(dt_str)
                event_date = dt.date().isoformat()
                time_str = None
            except ValueError:
                continue

            # Try to extract date from content (might be actual event date)
            content_el = art.select_one(".entry-content, .entry-summary")
            if content_el:
                content_text = content_el.get_text(" ", strip=True)
                extracted_date, extracted_time = self._extract_date_from_text(content_text)
                if extracted_date:
                    event_date = extracted_date
                    time_str = extracted_time

            venue_el = art.select_one(".tribe-venue, .venue")
            venue = venue_el.get_text(strip=True) if venue_el else ""

            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

            img_el = art.select_one("img")
            image_url = img_el.get("src") if img_el else None

            events.append(Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location="",
                source_url=source_url,
                source_name=self.name,
                description=None,
                image_url=image_url,
            ))
        return events

    @staticmethod
    def _next_page_url(soup: BeautifulSoup) -> str | None:
        el = soup.select_one("a.next.page-numbers, a[rel='next'], .nav-next a")
        if el:
            href = el.get("href", "")
            return href if href.startswith("http") else None
        return None

    def _extract_date_from_text(self, text: str) -> tuple[str | None, str | None]:
        """Try to extract an Italian date + time from text."""
        m = DATE_RE.search(text)
        if not m:
            return None, None
        day_s, month_name, year_s = m.group(1), m.group(2), m.group(3)
        hour_s, min_s = m.group(4), m.group(5)
        month = ITALIAN_MONTHS.get(month_name.lower())
        if not month:
            return None, None
        try:
            event_date = date(int(year_s), month, int(day_s)).isoformat()
        except ValueError:
            return None, None
        time_str = f"{int(hour_s):02d}:{min_s}" if hour_s and min_s else None
        return event_date, time_str
