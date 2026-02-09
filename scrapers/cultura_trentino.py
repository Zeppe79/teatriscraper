from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from models import Event
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cultura.trentino.it/calendar/search/node/(id)/298848"
TEATRO_CATEGORY = 30734

# Try these 'when' values to cover a wide range with fewer requests.
# The API seems to accept: "today", "week", "month", and possibly date strings.
# We try week-by-week using date strings as fallback if named ranges don't cover enough.
WEEKS_AHEAD = 9  # ~2 months of coverage


class CulturaTrentinoScraper(BaseScraper):
    name = "cultura.trentino.it"

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_ids: set[int] = set()

        # First try broad ranges: "month" may return the whole current month
        for when_value in ["today", "week", "month"]:
            self._fetch_events(when_value, events, seen_ids)

        # Then fill in future weeks by querying specific dates (one per week)
        start = date.today() + timedelta(days=7)
        for week in range(WEEKS_AHEAD):
            query_date = start + timedelta(weeks=week)
            day_str = query_date.strftime("%d/%m/%Y")
            self._fetch_events(day_str, events, seen_ids)

        return events

    def _fetch_events(
        self, when: str, events: list[Event], seen_ids: set[int]
    ) -> None:
        params = {"what": TEATRO_CATEGORY, "when": when}

        try:
            resp = self.fetch(BASE_URL, params=params)
            data = resp.json()
        except Exception:
            logger.warning(f"[{self.name}] Failed to fetch when={when}")
            return

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
