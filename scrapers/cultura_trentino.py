from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SITE_BASE = "https://www.cultura.trentino.it"
API_URL = f"{SITE_BASE}/calendar/search/node/(id)/298848"
TEATRO_CATEGORY = 30734
DAYS_AHEAD = 90  # ~3 months of coverage
MAX_ENRICH = 20  # individual event page visits for image + description


class CulturaTrentinoScraper(BaseScraper):
    name = "cultura.trentino.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_ids: set[int] = set()

        today = date.today()
        end = today + timedelta(days=DAYS_AHEAD)

        # Single request using dateRange parameter
        params = {
            "what": TEATRO_CATEGORY,
            "when": "range",
            "dateRange[]": [today.strftime("%Y%m%d"), end.strftime("%Y%m%d")],
        }

        try:
            resp = self.fetch(API_URL, params=params)
            data = resp.json()
        except Exception:
            logger.exception(f"[{self.name}] Failed to fetch date range")
            return events

        for day_block in data.get("result", {}).get("events", []):
            for tipo in day_block.get("tipo_evento", []):
                for ev in tipo.get("events", []):
                    event_id = ev.get("id")
                    if event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)

                    parsed = self._parse_event(ev)
                    if parsed:
                        events.append(parsed)

        # Enrich the first MAX_ENRICH events that have a source_url but
        # are missing image or description, by visiting their detail page.
        enriched = 0
        for ev in events:
            if enriched >= MAX_ENRICH:
                break
            if ev.image_url and ev.description:
                continue
            url = ev.source_url
            if not url:
                continue
            if not url.startswith("http"):
                url = SITE_BASE + url
            try:
                resp = self.fetch(url)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                continue
            enriched += 1

            if ev.image_url is None:
                og = soup.find("meta", property="og:image")
                if og and og.get("content"):
                    ev.image_url = og["content"]

            if ev.description is None:
                desc_el = soup.select_one(".descrizione")
                if desc_el:
                    ev.description = desc_el.get_text(" ", strip=True)[:500]

        return events

    def _parse_event(self, ev: dict) -> Event | None:
        try:
            title = ev.get("name", "").strip()
            if not title:
                return None

            # Date from identifier "2026-2-9"
            identifier = ev.get("identifier", "")
            parts = identifier.split("-")
            if len(parts) == 3:
                event_date = date(
                    int(parts[0]), int(parts[1]), int(parts[2])
                ).isoformat()
            else:
                return None

            # Time from orario_svolgimento "ore 10.00 ..."
            time_str = self._extract_time(ev.get("orario_svolgimento", ""))

            # Venue
            venue = ""
            luoghi = ev.get("luogo_della_cultura", [])
            if luoghi:
                venue = luoghi[0].get("name", "")

            # Location (comune)
            location = ""
            comuni = ev.get("comune", [])
            if comuni:
                location = comuni[0].get("name", "")

            # URL
            source_url = ev.get("href", "")

            # Description: iniziativa + orario details
            desc_parts = []
            for iniz in ev.get("iniziativa", []):
                name = iniz.get("name", "")
                if name:
                    desc_parts.append(name)
            orario = ev.get("orario_svolgimento", "").strip()
            if orario:
                desc_parts.append(orario)
            description = " | ".join(desc_parts) if desc_parts else None

            # Image: try common field names in the API response
            image_url = None
            for img_field in ["immagine_principale", "immagine", "foto", "image"]:
                img_data = ev.get(img_field)
                if isinstance(img_data, dict):
                    image_url = img_data.get("src") or img_data.get("uri") or img_data.get("href")
                elif isinstance(img_data, list) and img_data:
                    first = img_data[0]
                    image_url = (first.get("src") or first.get("uri") or first.get("href")) if isinstance(first, dict) else None
                elif isinstance(img_data, str) and img_data.startswith("http"):
                    image_url = img_data
                if image_url:
                    break

            return Event(
                title=title,
                date=event_date,
                time=time_str,
                venue=venue,
                location=location,
                source_url=source_url,
                source_name=self.name,
                description=description,
                image_url=image_url or None,
            )
        except Exception:
            logger.warning(
                f"[{self.name}] Failed to parse event: {ev.get('name', '?')}"
            )
            return None

    @staticmethod
    def _extract_time(text: str) -> str | None:
        """Extract time like '20.30' or '20:30' from orario text."""
        if not text:
            return None
        match = re.search(r"(\d{1,2})[.:](\d{2})", text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
        return None
