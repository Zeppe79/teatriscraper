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

            for card in soup.select(".contenitorearchivioeventievento"):
                ev = self._parse_card(card)
                if ev and ev.source_url not in seen_urls:
                    seen_urls.add(ev.source_url)
                    events.append(ev)

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

    def _parse_card(self, card) -> Event | None:
        try:
            # Title: first text node of .h3archivioevento a (avoids spurious child tags)
            title_el = card.select_one(".h3archivioevento a")
            if not title_el:
                return None
            title = next((c for c in title_el.children if isinstance(c, str)), "").strip()
            if not title:
                title = title_el.get_text(strip=True)
            if not title:
                return None

            href = title_el.get("href", "")
            source_url = href if href.startswith("http") else BASE_URL + href

            # Date + time: first .h4archivioevento
            # e.g. "sabato 14 Febbraio 2026,\n\t\t16.30"
            h4s = card.select(".h4archivioevento")
            if not h4s:
                return None
            date_raw = h4s[0].get_text(" ", strip=True)
            event_date, time_str = self._extract_date_from_text(date_raw)
            if not event_date:
                return None

            # Venue + location: second .h4archivioevento
            # e.g. "Borgo Valsugana – Teatro parrocchiale di Olle"
            venue, location = "", ""
            if len(h4s) > 1:
                venue_raw = h4s[1].get_text(strip=True)
                if " – " in venue_raw:
                    loc_part, ven_part = venue_raw.split(" – ", 1)
                    location = loc_part.strip()
                    venue = ven_part.strip()
                else:
                    venue = venue_raw

            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

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

    @staticmethod
    def _next_page_url(soup: BeautifulSoup) -> str | None:
        el = soup.select_one("a.next.page-numbers, a[rel='next'], .nav-next a")
        if el:
            href = el.get("href", "")
            return href if href.startswith("http") else None
        return None

    def _extract_date_from_text(self, text: str) -> tuple[str | None, str | None]:
        """Extract Italian date + optional time from text.

        Handles both:
          - "14 Febbraio 2026, 16.30"  (trentinospettacoli format, no 'ore')
          - "14 febbraio 2026 ore 20.30" (other sites)
        """
        m = DATE_RE.search(text)
        if not m:
            return None, None
        day_s, month_name, year_s = m.group(1), m.group(2), m.group(3)
        month = ITALIAN_MONTHS.get(month_name.lower())
        if not month:
            return None, None
        try:
            event_date = date(int(year_s), month, int(day_s)).isoformat()
        except ValueError:
            return None, None

        # Look for time anywhere after the date match
        time_str = None
        t = re.search(r"(\d{1,2})[.:](\d{2})", text[m.end():])
        if t:
            time_str = f"{int(t.group(1)):02d}:{t.group(2)}"
        return event_date, time_str
