from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.teatrodipergine.it"
CALENDAR_URL = f"{BASE_URL}/component/blog_calendar/{{year}}/{{month:02d}}?Itemid="

VENUE = "Teatro Lux"
LOCATION = "Pergine Valsugana"

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Matches "DD Month YYYY" optionally followed by "- ore HH.MM"
DATE_TIME_RE = re.compile(
    r"(\d{1,2})\s+([a-zA-Zàèéìòùáí]+)\s+(\d{4})"
    r"(?:\s*[-–]\s*ore\s+(\d{1,2})[.:](\d{2}))?",
    re.IGNORECASE,
)


class TeatroDiPergineScraper(BaseScraper):
    name = "teatrodipergine.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_keys: set[tuple[str, str]] = set()

        today = date.today()
        cutoff = today + timedelta(days=120)  # ~4 months ahead

        # Monthly blog_calendar for current + next 3 months
        for offset in range(4):
            month = today.month + offset
            year = today.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            url = CALENDAR_URL.format(year=year, month=month)
            events.extend(self._scrape_month(url, seen_keys, cutoff))

        return events

    def _scrape_month(self, start_url: str, seen_keys: set,
                      cutoff: date) -> list[Event]:
        """Scrape up to 2 pages for a calendar month.

        The Joomla pagination links strip the year/month from the URL,
        so following them indefinitely fetches the entire archive. Cap
        at 2 pages (~20 events) to stay within budget and filter to the
        scrape window.
        """
        events: list[Event] = []
        page_url: str | None = start_url
        pages_fetched = 0

        while page_url and pages_fetched < 2:
            page_events, next_url = self._scrape_page(page_url, seen_keys)
            pages_fetched += 1
            for ev in page_events:
                if date.fromisoformat(ev.date) <= cutoff:
                    events.append(ev)
            page_url = next_url

        return events

    def _scrape_page(self, url: str, seen_keys: set) -> tuple[list[Event], str | None]:
        """Scrape a single page. Returns (events, next_page_url|None)."""
        try:
            resp = self.fetch(url)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            logger.warning(f"[{self.name}] Could not fetch {url}")
            return [], None

        blog = soup.find("div", class_="blog")
        if not blog:
            logger.debug(f"[{self.name}] No .blog div found at {url}")
            return [], None

        events: list[Event] = []
        current_h3_date: str | None = None

        for child in blog.children:
            if not hasattr(child, "name") or child.name is None:
                continue

            if child.name == "h3":
                current_h3_date = self._parse_h3_date(child.get_text(strip=True))
                continue

            if child.name != "div" or "items-row" not in child.get("class", []):
                continue

            # Event block
            h2 = child.find("h2")
            if not h2:
                continue

            a_el = h2.find("a")
            title = h2.get_text(strip=True)
            if not title:
                continue

            source_url = ""
            if a_el and a_el.get("href"):
                href = a_el["href"]
                if href.startswith("/"):
                    source_url = BASE_URL + href
                elif href.startswith("http"):
                    source_url = href

            # Collect date+time from all <strong> elements
            date_times: list[tuple[str, str | None]] = []
            for strong in child.find_all("strong"):
                date_times.extend(self._extract_date_times(strong))

            # Fallback to h3 date context
            if not date_times and current_h3_date:
                date_times = [(current_h3_date, None)]

            # Description: first coloured <p> that has meaningful text
            description: str | None = None
            for p in child.find_all("p"):
                text = p.get_text(strip=True)
                if text and text not in title and len(text) > 4:
                    description = text
                    break

            # Image: first <img> in the item that is not a small logo
            image_url = None
            for img in child.find_all("img"):
                src = img.get("src", "")
                try:
                    if int(img.get("width", "0")) > 80:
                        image_url = (BASE_URL + src) if src.startswith("/") else src
                        break
                except (ValueError, TypeError):
                    pass

            for event_date, time_str in date_times:
                key = (title, event_date)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                events.append(Event(
                    title=title,
                    date=event_date,
                    time=time_str,
                    venue=VENUE,
                    location=LOCATION,
                    source_url=source_url,
                    source_name=self.name,
                    description=description,
                    image_url=image_url,
                ))

        # Follow pagination: .pagination a.next
        next_url: str | None = None
        next_a = soup.select_one(".pagination a.next")
        if next_a:
            href = next_a.get("href", "")
            if href.startswith("/"):
                next_url = BASE_URL + href
            elif href.startswith("http"):
                next_url = href

        return events, next_url

    def _extract_date_times(self, strong_el) -> list[tuple[str, str | None]]:
        """Extract all (ISO date, time|None) pairs from a <strong> element."""
        # Use \n as separator so <br> tags produce newlines
        text = strong_el.get_text(separator="\n")
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = DATE_TIME_RE.search(line)
            if not m:
                continue
            day_s, month_name, year_s = m.group(1), m.group(2), m.group(3)
            hour_s, min_s = m.group(4), m.group(5)
            month = ITALIAN_MONTHS.get(month_name.lower())
            if not month:
                continue
            try:
                event_date = date(int(year_s), month, int(day_s)).isoformat()
            except ValueError:
                continue
            time_str = f"{int(hour_s):02d}:{min_s}" if hour_s and min_s else None
            results.append((event_date, time_str))
        return results

    def _parse_h3_date(self, text: str) -> str | None:
        """Parse '01 Febbraio 2026' → '2026-02-01'."""
        parts = text.strip().split()
        if len(parts) != 3:
            return None
        month = ITALIAN_MONTHS.get(parts[1].lower())
        if not month:
            return None
        try:
            return date(int(parts[2]), month, int(parts[0])).isoformat()
        except ValueError:
            return None
