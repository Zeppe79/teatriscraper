from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cultura.trentino.it/calendar/search/node/(id)/298848"
TEATRO_CATEGORY = 30734
DAYS_AHEAD = 90  # ~3 months of coverage


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
            resp = self.fetch(BASE_URL, params=params)
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
