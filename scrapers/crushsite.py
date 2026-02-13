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
SOGGETTI_URL = f"{BASE_URL}/it/soggetti/danza-teatro/"

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
SLASH_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")


class CrushsiteScraper(BaseScraper):
    name = "crushsite.it"

    def scrape(self) -> list[Event]:
        # Step 1: collect company page URLs from the soggetti listing
        company_urls = self._get_company_urls()
        logger.info(f"[{self.name}] Found {len(company_urls)} companies")

        events: list[Event] = []
        seen_urls: set[str] = set()

        for company_url in company_urls:
            try:
                resp = self.fetch(company_url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {company_url}")
                continue

            for ev in self._parse_company_page(soup, company_url):
                if ev.source_url not in seen_urls:
                    seen_urls.add(ev.source_url)
                    events.append(ev)

        return events

    # ------------------------------------------------------------------
    # Level 1: collect company URLs from /it/soggetti/danza-teatro/
    # ------------------------------------------------------------------

    def _get_company_urls(self) -> list[str]:
        urls: list[str] = []
        try:
            resp = self.fetch(SOGGETTI_URL)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            logger.warning(f"[{self.name}] Could not fetch soggetti page")
            return urls

        # Each company card: .item-soggetto .titoli-eventi a
        for a in soup.select(".item-soggetto .titoli-eventi a"):
            href = a.get("href", "")
            if not href:
                continue
            if href.startswith("http"):
                urls.append(href)
            elif href.startswith("/"):
                urls.append(BASE_URL + href)

        return urls

    # ------------------------------------------------------------------
    # Level 2: parse events from a company page
    # ------------------------------------------------------------------

    def _parse_company_page(self, soup: BeautifulSoup, company_url: str) -> list[Event]:
        events: list[Event] = []

        # 1. JSON-LD
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Event", "TheaterEvent", "DanceEvent", "MusicEvent"):
                        ev = self._parse_jsonld(item)
                        if ev:
                            events.append(ev)
            except Exception:
                pass
        if events:
            return events

        # 2. Crushsite event rows: each date block inside .colonnas-1-301
        for row in soup.select(".colonnas-1-301"):
            ev = self._parse_crushsite_row(row, company_url)
            if ev:
                events.append(ev)
        if events:
            return events

        # 3. Generic: any element containing an Italian date
        venue = self._extract_venue(soup)
        location = self._extract_location(soup)
        title = self._extract_title(soup)

        text_blocks = soup.select("p, li, div.testo, div.contenuto, span.data")
        for block in text_blocks:
            text = block.get_text(" ", strip=True)
            event_date, time_str = self._parse_italian_date(text)
            if event_date:
                events.append(Event(
                    title=title or "Evento",
                    date=event_date,
                    time=time_str,
                    venue=venue or "",
                    location=location or "",
                    source_url=company_url,
                    source_name=self.name,
                    description=None,
                    image_url=None,
                ))

        return events

    def _parse_crushsite_row(self, row, fallback_url: str) -> Event | None:
        try:
            # Title from .titoli-eventi or heading
            title_el = (
                row.select_one(".titoli-eventi a")
                or row.select_one(".titoli-eventi")
                or row.select_one("h2, h3, h4")
            )
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            a_el = title_el if title_el.name == "a" else title_el.find("a")
            href = a_el.get("href", "") if a_el else ""
            source_url = (
                href if href.startswith("http")
                else (BASE_URL + href if href.startswith("/") else fallback_url)
            )

            text = row.get_text(" ", strip=True)
            event_date, time_str = self._parse_italian_date(text)
            if not event_date:
                return None

            venue_el = row.select_one(".luogo, .venue, .teatro, .testoprincipale-titolinotizie")
            venue = venue_el.get_text(strip=True) if venue_el else ""

            img_el = row.select_one("img")
            image_url = img_el.get("src") if img_el else None
            if image_url and not image_url.startswith("http"):
                image_url = (BASE_URL + image_url) if image_url.startswith("/") else None

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location="",
                source_url=source_url,
                source_name=self.name,
                description=None,
                image_url=image_url,
            )
        except Exception:
            return None

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

            loc = item.get("location", {})
            venue = loc.get("name", "") if isinstance(loc, dict) else ""
            city = ""
            if isinstance(loc, dict):
                addr = loc.get("address", {})
                city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""

            source_url = item.get("url", item.get("@id", ""))
            if source_url and not source_url.startswith("http"):
                source_url = BASE_URL + source_url

            img_data = item.get("image")
            if isinstance(img_data, dict):
                image_url = img_data.get("url") or img_data.get("@id") or None
            elif isinstance(img_data, str) and img_data.startswith("http"):
                image_url = img_data
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
                description=item.get("description") or None,
                image_url=image_url,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_italian_date(self, text: str) -> tuple[str | None, str | None]:
        # "18 marzo 2026" / "18 marzo 2026 ore 20.30"
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

        # "18/03/2026"
        m2 = SLASH_DATE_RE.search(text)
        if m2:
            try:
                event_date = date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1))).isoformat()
                t = TIME_RE.search(text[m2.end():])
                time_str = f"{int(t.group(1)):02d}:{t.group(2)}" if t else None
                return event_date, time_str
            except ValueError:
                pass

        return None, None

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str | None:
        el = soup.select_one("h1, .titoli-eventi, .titolo-soggetto")
        return el.get_text(strip=True) if el else None

    @staticmethod
    def _extract_venue(soup: BeautifulSoup) -> str | None:
        el = soup.select_one(".luogo, .venue, .teatro")
        return el.get_text(strip=True) if el else None

    @staticmethod
    def _extract_location(soup: BeautifulSoup) -> str | None:
        el = soup.select_one(".citta, .città, .city, .comune")
        return el.get_text(strip=True) if el else None
