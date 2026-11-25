"""Answer evaluation: ask every question of a split three ways and record each answer.

    none                  the question alone; the model answers from memory (the baseline)
    rules                 the 8 articles rule search finds
    rules_and_decisions   the 8 articles, the 5 past decisions, and the articles those
                          decisions cite (what the product does)

Only the search results in the prompt differ. The instructions, the Answer format, the
model and the calling code are the same: `answer.messages` and `client.ask`. With search
switched off every configuration sends exactly the no-search prompt (a test checks it).

Each answer is one line of runs/<run>/results.jsonl, written as soon as it arrives. A run
that stops part-way is started again with the same name and continues where it stopped;
only calls that hit a rate limit or a connection error are asked again. A line holds ids,
labels, the answer's structured fields, tokens and cost, and no FIA text. The prompt and
the model's reason, which can quote the documents, go to runs/<run>/transcripts/, which
stays on this machine (.gitignore).
"""

import json
import random
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import answer as answering
from .. import config
from ..llm import client
from ..search import DecisionSearch, RuleSearch
from .retrieval import Question, build_questions

CONFIGS = ("none", "rules", "rules_and_decisions")
RUNS_DIR = config.ROOT / "runs"

# Statuses worth asking again when a run is resumed: they say nothing about the model.
RETRY = ("rate_limited", "error")

# A penalty written in the question would give the answer away. Over the 2026 season no
# Fact names one (checked 2026-11-24); a number of seconds alone is not a penalty here
# ("after the 15 second signal" is a start procedure), so only penalty phrases count.
PENALTY_IN_TEXT = re.compile(
    r"\d+\s*(?:-\s*)?seconds?\s+(?:time\s+)?penalty|time\s+penalty|€\s*\d|\bfined\b|grid\s+(?:place|position)s?\s+penalty"
    r"|\breprimand|drive[\s-]*through|stop[\s-]*(?:and|&)[\s-]*go|disqualif|no\s+further\s+action",
    re.I,
)


@dataclass
class Prepared:
    """One question with what each configuration shows the model."""

    question: Question
    kind: str
    shown: dict[str, tuple[list[dict], list[dict]]]  # configuration -> (articles, decisions)


def questions_for(records: list[dict], split: str, sample: int | None = None) -> tuple[list[Question], Counter]:
    """The split's questions in the stewards' words, and what was left out and why.

    `sample` draws that many at random with a fixed seed, for a cheap first look.
    """
    questions, left_out = build_questions(records, split)
    kept = []
    for question in questions:
        if PENALTY_IN_TEXT.search(question.text):
            left_out["the question names a penalty"] += 1
        else:
            kept.append(question)
    if sample is not None and sample < len(kept):
        kept = sorted(random.Random(20261124).sample(kept, sample), key=lambda q: (q.round, q.ids[0]))
    return kept, left_out


def prepare(
    questions: list[Question],
    records_by_id: dict[str, dict],
    decision_search: DecisionSearch,
    rule_search: RuleSearch,
    configs: tuple[str, ...] = CONFIGS,
) -> list[Prepared]:
    """Run every search before any model call. Searching is fast and runs one at a time;
    the model calls that follow run several at once."""
    prepared = []
    for question in questions:
        decisions = decision_search.search(question.text, before_round=question.round)
        # The rule of search.py, checked on every real question and not only in a unit test.
        late = [d["id"] for d in decisions if d["round"] >= question.round]
        if late:
            raise AssertionError(f"Decision search for a {question.event} question returned {late}")
        shown: dict[str, tuple[list[dict], list[dict]]] = {}
        if "none" in configs:
            shown["none"] = ([], [])
        if "rules" in configs:
            shown["rules"] = (rule_search.search(question.text, date=question.date), [])
        if "rules_and_decisions" in configs:
            articles = rule_search.search(question.text, date=question.date, decisions=decisions)
            shown["rules_and_decisions"] = (articles, decisions)
        kind = records_by_id[question.ids[0]]["kind"]
        prepared.append(Prepared(question, kind, shown))
    return prepared


def row_for(item: Prepared, configuration: str, reply: client.Reply, effort: str) -> dict:
    """The line results.jsonl gets for one answer. Ids and labels only, no FIA text."""
    articles, decisions = item.shown[configuration]
    row = {
        "question": item.question.ids[0],
        "ids": item.question.ids,
        "event": item.question.event,
        "kind": item.kind,
        "config": configuration,
        "model": reply.model,
        "reasoning_effort": effort,
        "status": reply.status,
        "answer": None,
        "check": None,
        "shown": {"articles": [a["key"] for a in articles], "decisions": [d["id"] for d in decisions]},
        "usage": vars(reply.usage),
        "seconds": round(reply.seconds, 2),
        "cost": reply.cost,
    }
    if reply.status == "ok":
        a = reply.parsed
        checked = answering.check(a, articles, decisions)
        row["answer"] = {
            "articles": a.articles,
            "penalty": {"type": a.penalty_type, "value": a.penalty_value, "unit": a.penalty_unit},
            "precedents_used": a.precedents_used,
        }
        row["check"] = {
            "passed": checked.passed,
            "unknown_articles": checked.unknown_articles,
            "unknown_decisions": checked.unknown_decisions,
        }
    return row


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest_rows(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(question, configuration) -> its last recorded line. A resumed run appends, never rewrites."""
    return {(row["question"], row["config"]): row for row in rows}


def run(
    prepared: list[Prepared],
    run_dir: Path,
    model: str,
    effort: str = config.REASONING_EFFORT,
    configs: tuple[str, ...] = CONFIGS,
    workers: int = 4,
    ask: Callable = client.ask,
    progress: Callable[[str], None] = lambda line: None,
) -> list[dict]:
    """Ask every (question, configuration) not yet answered in `run_dir`, several at a time.

    `ask` is `client.ask` unless a test hands in a stand-in. Returns the lines written now.
    """
    (run_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    results = run_dir / "results.jsonl"
    done = {key for key, row in latest_rows(read_rows(results)).items() if row["status"] not in RETRY}
    todo = [(item, c) for item in prepared for c in configs if (item.question.ids[0], c) not in done]
    progress(f"{len(todo)} calls to make, {len(prepared) * len(configs) - len(todo)} already recorded")

    lock = threading.Lock()
    written: list[dict] = []

    def one(item: Prepared, configuration: str) -> dict:
        articles, decisions = item.shown[configuration]
        messages = answering.messages(item.question.text, articles, decisions)
        reply = ask(messages, answering.Answer, model=model, effort=effort)
        row = row_for(item, configuration, reply, effort)
        transcript = {
            "question": item.question.text,
            "config": configuration,
            "messages": [{"role": m.type, "content": m.content} for m in messages],
            "status": reply.status,
            "answer": reply.parsed.model_dump() if reply.parsed is not None else None,
            "error": reply.error,
        }
        name = f"{item.question.ids[0]}__{configuration}.json"
        (run_dir / "transcripts" / name).write_text(json.dumps(transcript, indent=1, ensure_ascii=False), "utf-8")
        with lock:  # one thread at a time appends a whole line
            with results.open("a", encoding="utf-8") as out:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            written.append(row)
            if len(written) % 25 == 0 or len(written) == len(todo):
                cost = sum(r["cost"] for r in written)
                progress(f"  {len(written)} of {len(todo)} answered, ${cost:.3f} so far")
        return row

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(one, item, c) for item, c in todo]
        for future in as_completed(futures):
            future.result()  # a bug in this code should stop the run, not hide in a thread
    finally:
        # On an error, the calls not yet started are dropped instead of paid for.
        pool.shutdown(wait=True, cancel_futures=True)
    return written


def write_meta(run_dir: Path, **fields) -> None:
    """runs/<run>/run.json: what this run was. Kept from the first start of the run.

    Resuming with another prompt, model, question set or search would mix two experiments
    in one file, so it stops. More configurations on the same questions is allowed: the
    list of configurations becomes the union.
    """
    path = run_dir / "run.json"
    meta = json.loads(path.read_text("utf-8")) if path.exists() else {}
    for key in ("model", "reasoning_effort", "prompt", "split", "sample", "questions", "search"):
        if key in meta and key in fields and meta[key] != fields[key]:
            raise ValueError(f"{run_dir.name} was started with {key} {meta[key]!r}, not {fields[key]!r}. Use a new --run name.")
    if "configs" in meta and "configs" in fields:
        fields["configs"] = list(dict.fromkeys(meta["configs"] + fields["configs"]))
        meta["configs"] = fields["configs"]
    meta = {**fields, **meta, "last_resumed": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    meta.setdefault("started", meta["last_resumed"])
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", "utf-8")
