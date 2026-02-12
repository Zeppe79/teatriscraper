from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text)


def _make_id(event_date: str, venue: str, title: str) -> str:
    """Deterministic hash from (date, venue, title) for dedup."""
    key = f"{event_date}|{_normalize(venue)}|{_normalize(title)}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


@dataclass
class Event:
    title: str
    date: str              # ISO 8601: "2026-02-09"
    time: str | None        # "20:30" or None
    venue: str              # "Teatro Cuminetti"
    location: str           # "Trento"
    source_url: str
    source_name: str        # "cultura.trentino.it"
    description: str | None = None
    image_url: str | None = None
    source_urls: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.source_url and not self.source_urls:
            self.source_urls = [self.source_url]

    @property
    def id(self) -> str:
        return _make_id(self.date, self.venue, self.title)

    @property
    def is_past(self) -> bool:
        try:
            return date.fromisoformat(self.date) < date.today()
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "time": self.time,
            "venue": self.venue,
            "location": self.location,
            "description": self.description,
            "image_url": self.image_url,
            "source_url": self.source_urls[0] if self.source_urls else self.source_url,
            "source_urls": self.source_urls,
            "source_name": self.source_name,
            "is_past": self.is_past,
        }
