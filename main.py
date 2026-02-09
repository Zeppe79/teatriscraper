#!/usr/bin/env python3
"""TeatriScraper - Trentino theater event aggregator."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dedup import deduplicate
from scrapers import ALL_SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "docs"
OUTPUT_FILE = OUTPUT_DIR / "events.json"


def main() -> None:
    all_events = []

    for scraper_class in ALL_SCRAPERS:
        scraper = scraper_class()
        events = scraper.run()
        all_events.extend(events)

    logger.info(f"Total events before dedup: {len(all_events)}")
    unique_events = deduplicate(all_events)
    logger.info(f"Total events after dedup: {len(unique_events)}")

    # Sort by date, then time
    unique_events.sort(key=lambda e: (e.date, e.time or ""))

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "count": len(unique_events),
        "events": [e.to_dict() for e in unique_events],
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    logger.info(f"Written {len(unique_events)} events to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
