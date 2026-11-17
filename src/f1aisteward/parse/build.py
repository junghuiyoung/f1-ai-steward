"""Run the decision parser over every document in the manifest and write the results.

Two files come out, and the difference between them matters:

    .cache/text/decisions.jsonl   every field, including the stewards' text. Stays local.
    data/labels/decisions.jsonl   ids, article ids, penalty, kind. No FIA text. Goes in git.

JSONL means "one JSON object per line". It can be read a line at a time, and a change
to one decision changes one line in a diff.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import config, fetch
from . import decisions, labels


@dataclass
class BuildReport:
    total: int = 0
    not_downloaded: list[str] = field(default_factory=list)
    left_out: Counter = field(default_factory=Counter)  # documents that are not about an incident
    failed: list[str] = field(default_factory=list)  # "<id>: why"
    records: list[dict] = field(default_factory=list)  # with FIA text
    labels: list[dict] = field(default_factory=list)  # without


def decision_id(season: int, event_slug: str, number: int) -> str:
    return f"{season}-{event_slug}-{number:03d}"


def build_decisions(
    manifest_data: dict,
    pdf_dir: Path = config.PDF_DIR,
    extract_text: Callable[[Path], str] = decisions.extract_text,
) -> BuildReport:
    """Parse every decision that is on disk. Nothing is written here; see `write`."""
    report = BuildReport()
    for event in manifest_data["events"]:
        for doc in event["docs"]:
            report.total += 1
            doc_id = decision_id(manifest_data["season"], event["slug"], doc["number"])
            path = fetch.pdf_path(event["slug"], doc["number"], pdf_dir)
            if not path.exists():
                report.not_downloaded.append(doc_id)
                continue

            try:
                text = extract_text(path)
            except Exception as error:  # a damaged PDF must not stop the other 358
                report.failed.append(f"{doc_id}: cannot read the PDF ({type(error).__name__})")
                continue

            parsed = decisions.parse(text)
            if parsed.other_document == "unknown":
                report.failed.append(f"{doc_id}: no fields found, and not a kind of document we know")
                continue
            if parsed.other_document:
                report.left_out[parsed.other_document] += 1
                continue
            if parsed.missing:
                report.failed.append(f"{doc_id}: missing {', '.join(parsed.missing)}")
                continue

            articles = labels.normalise_articles(parsed.infringement)
            penalty = labels.parse_penalty(parsed.decision)
            kind = labels.classify_kind(parsed.fact, articles)

            report.records.append(
                {
                    "id": doc_id,
                    "event": event["slug"],
                    "round": event["round"],
                    "date": event["date"],
                    "number": doc["number"],
                    "url": doc["url"],
                    "layout": parsed.layout,
                    "cars": parsed.cars,
                    "driver": parsed.driver,
                    "competitor": parsed.competitor,
                    "time": parsed.time,
                    "session": parsed.session,
                    "fact": parsed.fact,
                    "infringement": parsed.infringement,
                    "decision": parsed.decision,
                    "reason": parsed.reason,
                    "articles": articles,
                    "penalty": penalty,
                    "kind": kind,
                    "notes": parsed.notes,
                }
            )
            report.labels.append(
                {
                    "id": doc_id,
                    "event": event["slug"],
                    "number": doc["number"],
                    "url": doc["url"],
                    "sha256": doc["sha256"],
                    "articles": articles,
                    "penalty": penalty,
                    "kind": kind,
                    "split": labels.split_for(event["date"]),  # "dev", "test" or None
                }
            )
    return report


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write(
    report: BuildReport,
    parsed_path: Path = config.PARSED_DECISIONS,
    labels_path: Path = config.DECISION_LABELS,
) -> None:
    write_jsonl(parsed_path, report.records)
    write_jsonl(labels_path, report.labels)


def summary(report: BuildReport) -> str:
    """The text `build --decisions` prints."""
    layouts = Counter(record["layout"] for record in report.records)
    kinds = Counter(record["kind"] for record in report.records)
    penalties = Counter(record["penalty"]["type"] for record in report.records)
    no_article = [record["id"] for record in report.records if not record["articles"]]
    other_penalty = [record["id"] for record in report.records if record["penalty"]["type"] == "other"]
    noted = [record["id"] for record in report.records if record["notes"]]

    def row(name: str, count: int, extra: str = "") -> str:
        return f"  {name:<28}{count:>4}  {extra}".rstrip()

    def breakdown(counter: Counter) -> str:
        return ", ".join(f"{name} {count}" for name, count in counter.most_common())

    lines = [
        f"{'Decisions in the manifest':<30}{report.total:>4}",
        row("not downloaded", len(report.not_downloaded), "run `f1aisteward fetch`" if report.not_downloaded else ""),
        row("parsed", len(report.records), breakdown(layouts)),
        row("left out, not an incident", sum(report.left_out.values()), breakdown(report.left_out)),
        row("failed", len(report.failed)),
        "",
        "By kind",
        *[row(name, kinds[name]) for name in labels.KINDS],
        "",
        "By penalty",
        *[row(name, penalties[name]) for name in labels.PENALTY_TYPES if penalties[name]],
        "",
        "Labels to look at",
        row("no article recognised", len(no_article), " ".join(no_article)),
        row("penalty type 'other'", len(other_penalty), " ".join(other_penalty)),
        row("parsed with a workaround", len(noted), " ".join(noted)),
    ]
    if report.failed:
        lines += ["", "Failed", *[f"  {item}" for item in report.failed]]
    return "\n".join(lines)
