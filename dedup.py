from __future__ import annotations

from difflib import SequenceMatcher
from models import Event, _normalize

SIMILARITY_THRESHOLD = 0.80


def _titles_match(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= SIMILARITY_THRESHOLD


def _merge_events(existing: Event, new: Event) -> Event:
    """Merge new into existing, keeping the richer data."""
    for url in new.source_urls:
        if url not in existing.source_urls:
            existing.source_urls.append(url)

    if not existing.time and new.time:
        existing.time = new.time
    if not existing.description and new.description:
        existing.description = new.description

    return existing


def deduplicate(events: list[Event]) -> list[Event]:
    """Remove duplicate events based on (date, venue, fuzzy title)."""
    unique: list[Event] = []

    for event in events:
        merged = False
        for i, existing in enumerate(unique):
            if event.date != existing.date:
                continue
            if _normalize(event.venue) != _normalize(existing.venue):
                continue
            if _titles_match(event.title, existing.title):
                unique[i] = _merge_events(existing, event)
                merged = True
                break
        if not merged:
            unique.append(event)

    return unique
