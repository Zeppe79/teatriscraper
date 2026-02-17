from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.crushsite.it"
SOGGETTI_URL = f"{BASE_URL}/it/soggetti/danza-teatro/"

TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")
# "Rovereto (Tn)" → "Rovereto"
CITY_RE = re.compile(r",\s*([^,()]+?)(?:\s*\([^)]+\))?\s*$")

MAX_COMPANIES = 5
MAX_EVENTS_TOTAL = 20


class CrushsiteScraper(BaseScraper):
    name = "crushsite.it"

    def scrape(self) -> list[Event]:
        # Level 1: collect company page URLs from the soggetti listing
        company_urls = self._get_company_urls()[:MAX_COMPANIES]
        logger.info(f"[{self.name}] Found {len(company_urls)} companies")

        # Level 2: collect event page URLs from each company page
        event_urls: list[str] = []
        seen_event_urls: set[str] = set()

        for company_url in company_urls:
            try:
                resp = self.fetch(company_url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                logger.warning(f"[{self.name}] Could not fetch {company_url}")
                continue

            for a in soup.select(".colonnas-1-301 .titoli-eventi a"):
                href = a.get("href", "")
                if not href:
                    continue
                url = (
                    href if href.startswith("http")
                    else (BASE_URL + href if href.startswith("/") else None)
                )
                if url and url not in seen_event_urls:
                    seen_event_urls.add(url)
                    event_urls.append(url)

        event_urls = event_urls[:MAX_EVENTS_TOTAL]
        logger.info(f"[{self.name}] Visiting {len(event_urls)} event pages")

        # Level 3: visit each event page for full structured data
        events: list[Event] = []
        for url in event_urls:
            ev = self._scrape_event_page(url)
            if ev:
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
    # Level 3: parse a single event detail page
    # ------------------------------------------------------------------

    def _scrape_event_page(self, url: str) -> Event | None:
        try:
            resp = self.fetch(url)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            logger.warning(f"[{self.name}] Could not fetch {url}")
            return None

        # Title
        title_el = soup.select_one("h1.testo-titolipagina")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        # ISO date from microdata: <span itemprop="startDate" content="2026-02-17">
        date_el = soup.select_one("span[itemprop='startDate']")
        if not date_el or not date_el.get("content"):
            return None
        event_date = date_el["content"]  # already "YYYY-MM-DD"

        venue = ""
        time_str = None
        description = None

        detail_box = soup.select_one(".colonnas-1-301ds")
        if detail_box:
            # Venue from microdata
            venue_el = detail_box.select_one("span[itemprop='streetAddress']")
            if venue_el:
                venue = venue_el.get_text(strip=True)

            # Label-value pairs: "Orario:" → time, "Note:" → description
            for label in detail_box.find_all("span", class_="testo-boxgrigio-grassetto"):
                label_text = label.get_text(strip=True)
                value_el = label.find_next_sibling("span", class_="testo-boxgrigio")
                if not value_el:
                    continue
                value_text = value_el.get_text(" ", strip=True)

                if "Orario" in label_text and time_str is None:
                    m = TIME_RE.search(value_text)
                    if m:
                        time_str = f"{int(m.group(1)):02d}:{m.group(2)}"
                elif "Note" in label_text and description is None:
                    description = value_text[:500]

        # Fallback description from event body text
        if not description:
            desc_el = soup.select_one(".colonna-1-5007-testoevi .testoprincipale")
            if desc_el:
                description = desc_el.get_text(" ", strip=True)[:500]

        # Image: prefer large version from content attribute
        image_url = None
        img_el = soup.select_one(".colonna-1-5007-foto img")
        if img_el:
            image_url = img_el.get("content") or img_el.get("src")
            if image_url and image_url.startswith("/"):
                image_url = BASE_URL + image_url

        # Extract city from venue address: "…, Rovereto (Tn)" → "Rovereto"
        location = ""
        if venue:
            m = CITY_RE.search(venue)
            if m:
                location = m.group(1).strip()

        return Event(
            title=title,
            date=event_date,
            time=time_str,
            venue=venue,
            location=location,
            source_url=url,
            source_name=self.name,
            description=description,
            image_url=image_url,
        )
