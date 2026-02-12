from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.centrosantachiara.it"
URL = f"{BASE_URL}/spettacoli/calendariospettacoli"

ITALIAN_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

KNOWN_CITIES = {
    "trento", "rovereto", "bolzano", "vipiteno", "vezzano", "pergine",
    "riva", "arco", "mezzocorona", "cles", "tione", "levico", "lavis",
    "mori", "ala", "canazei", "cavalese", "mezzolombardo", "moena",
    "predazzo", "malè", "storo", "borgo", "merano", "bressanone",
}


class CentroSantaChiaraScraper(BaseScraper):
    name = "centrosantachiara.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        try:
            resp = self.fetch(URL)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            logger.exception(f"[{self.name}] Failed to fetch page")
            return events

        for card in soup.select(".single_next_event"):
            parsed = self._parse_card(card)
            if parsed:
                events.append(parsed)

        return events

    def _parse_card(self, card) -> Event | None:
        try:
            date_div = card.select_one(".sne_date")
            if not date_div:
                return None

            ps = date_div.find_all("p")
            if len(ps) < 2:
                return None

            day = ps[0].get_text(strip=True)
            month_year = ps[1].get_text(strip=True)
            time_raw = ps[2].get_text(strip=True) if len(ps) > 2 else ""

            event_date = self._parse_date(day, month_year)
            if not event_date:
                return None

            parsed_time = self._extract_time(time_raw)

            title_el = card.select_one(".sne_title")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            location_el = card.select_one(".sne_location")
            location_text = location_el.get_text(strip=True) if location_el else ""
            venue, location = self._parse_location(location_text)

            # Prefer internal detail link; fall back to any link in the button area
            source_url = ""
            for a in card.select(".sne_btn a.btn_std"):
                href = a.get("href", "")
                if href.startswith("/spettacoli/"):
                    source_url = BASE_URL + href
                    break
            if not source_url:
                a_any = card.select_one(".sne_btn a.btn_std")
                if a_any:
                    source_url = a_any.get("href", "")

            desc_el = card.select_one(".she_adv")
            description = desc_el.get_text(strip=True) if desc_el else None

            img_el = card.select_one(".sne_img img")
            image_url = img_el.get("src") if img_el else None

            return Event(
                title=title,
                date=event_date,
                time=parsed_time,
                venue=venue,
                location=location,
                source_url=source_url,
                source_name=self.name,
                description=description or None,
                image_url=image_url,
            )
        except Exception:
            logger.warning(f"[{self.name}] Failed to parse card")
            return None

    def _parse_date(self, day: str, month_year: str) -> str | None:
        """Parse '09' + 'Febbraio, 2026' → '2026-02-09'."""
        try:
            month_year = month_year.replace(",", "").strip()
            parts = month_year.split()
            if len(parts) != 2:
                return None
            month_name = parts[0].lower()
            year = int(parts[1])
            month = ITALIAN_MONTHS.get(month_name)
            if not month:
                return None
            return date(year, month, int(day)).isoformat()
        except Exception:
            return None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        """Extract HH:MM from strings like '20.30', 'ore 9.30 e ore 11.00', 'open door 21.00'."""
        if not text:
            return None
        match = re.search(r"(\d{1,2})[.:](\d{2})", text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
        return None

    @staticmethod
    def _parse_location(text: str) -> tuple[str, str]:
        """Parse combined venue+city string into (venue, city).

        Handles formats:
          - 'City - Venue'  (e.g. 'Vipiteno - Teatro Comunale')
          - 'Venue City'    (e.g. 'Teatro Sociale Trento')
          - 'City VENUE'    (e.g. 'Trento CASTELLO DEL BUONCONSIGLIO')
        """
        text = text.strip()
        if not text:
            return ("", "")

        if " - " in text:
            parts = text.split(" - ", 1)
            return (parts[1].strip(), parts[0].strip())

        words = text.split()
        if words and words[-1].lower() in KNOWN_CITIES:
            return (" ".join(words[:-1]), words[-1])

        if words and words[0].lower() in KNOWN_CITIES:
            return (" ".join(words[1:]), words[0])

        return (text, "")
