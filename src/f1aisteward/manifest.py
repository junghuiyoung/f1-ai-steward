"""The events manifest: which stewards' decisions exist, and where to download them.

The manifest (data/manifest/events.yaml) is the list the rest of the project works from.
It holds links and hashes, never document text.
"""

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

from . import config

# A document title on fia.com looks like "Doc 79 - Infringement - Car 16 - Causing a collision".
# The spacing around the dashes is typed by hand and is not always there ("Infringement- Car 55").
_TITLE = re.compile(r"^Doc (\d+)\s*-\s*(Infringement|Decision|Offence)\s*-\s*(.+)$")
# Lists of deleted lap times use the same title prefix but are not decisions about an incident.
_LAP_LIST = re.compile(r"deleted lap times", re.IGNORECASE)


def parse_title(title: str) -> dict | None:
    """Return the document number, kind and subject of a stewards' decision, or None.

    None means "not something we use": a classification, a notice, a lap-time deletion list.
    """
    match = _TITLE.match(title.strip())
    if match is None or _LAP_LIST.search(title):
        return None
    return {"number": int(match.group(1)), "kind": match.group(2), "subject": match.group(3)}


def slugify(event_name: str) -> str:
    """'São Paulo Grand Prix' -> 'sao-paulo'. Used in commands and folder names."""
    name = event_name.removesuffix(" Grand Prix")
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def _published(text: str) -> datetime:
    """fia.com shows publication times as '08.11.26 22:50' (day.month.year)."""
    return datetime.strptime(text, "%d.%m.%y %H:%M")


def _race_day(docs: list[dict]) -> datetime:
    """The day the final race classification was published, in fia.com's own clock.

    Some decisions are published days after the race, so "the latest document" is the wrong
    answer. fia.com shows Central European time, which makes races in the Americas land on
    the next calendar day. That is fine here: the date is used to put events in order.
    """
    for doc in docs:
        if "Final Race Classification" in doc["title"]:
            return _published(doc["published"])
    return max(_published(doc["published"]) for doc in docs)


def build_events(listing: list[dict], season: int) -> dict:
    """Turn a saved fia.com document listing into the manifest structure.

    `listing` is a list of events, each {"name": ..., "docs": [{"href", "title", "published"}]}.
    Events come out oldest first and numbered, because later steps need to know
    which race weekends came before a given one.
    """
    events = []
    for event in listing:
        docs = []
        for doc in event["docs"]:
            parsed = parse_title(doc["title"])
            if parsed is None:
                continue
            docs.append(
                {
                    "number": parsed["number"],
                    "kind": parsed["kind"],
                    "subject": parsed["subject"],
                    "url": config.FIA_BASE_URL + doc["href"],
                    "published": _published(doc["published"]).strftime("%Y-%m-%d %H:%M"),
                    "sha256": None,  # filled in by `fetch` the first time the file is downloaded
                }
            )
        docs.sort(key=lambda d: d["number"])
        events.append(
            {
                "slug": slugify(event["name"]),
                "name": event["name"],
                "date": _race_day(event["docs"]).strftime("%Y-%m-%d"),
                "docs": docs,
            }
        )
    events.sort(key=lambda e: e["date"])
    for round_number, event in enumerate(events, start=1):
        # Put `round` right after `name` so the file reads naturally.
        reordered = {"slug": event["slug"], "name": event["name"], "round": round_number}
        reordered.update({k: v for k, v in event.items() if k not in reordered})
        event.clear()
        event.update(reordered)
    return {"season": season, "events": events}


def load(path: Path = config.EVENTS_MANIFEST) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save(manifest: dict, path: Path = config.EVENTS_MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=1000)
    path.write_text(text, encoding="utf-8")
