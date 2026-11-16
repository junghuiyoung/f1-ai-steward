"""Build data/manifest/events.yaml from a saved fia.com document listing.

Run once per season update:
    uv run python scripts/make_events_manifest.py scratch/season_2026.json 2026

The listing is a JSON file with every document title and link per event. It is not
in the repository; the manifest this script writes is.
Hashes already recorded in an existing manifest are kept.
"""

import json
import sys
from pathlib import Path

from f1aisteward import config, manifest


def main(listing_path: str, season: str) -> None:
    listing = json.loads(Path(listing_path).read_text(encoding="utf-8"))
    data = manifest.build_events(listing, int(season))

    if config.EVENTS_MANIFEST.exists():
        old = manifest.load()
        known = {(e["slug"], d["number"]): d["sha256"] for e in old["events"] for d in e["docs"]}
        for event in data["events"]:
            for doc in event["docs"]:
                doc["sha256"] = known.get((event["slug"], doc["number"]))

    manifest.save(data)
    total = sum(len(e["docs"]) for e in data["events"])
    print(f"{len(data['events'])} events, {total} decisions -> {config.EVENTS_MANIFEST.relative_to(config.ROOT)}")
    for event in data["events"]:
        print(f"  {event['round']:>2}  {event['date']}  {event['slug']:<22} {len(event['docs']):>3}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
