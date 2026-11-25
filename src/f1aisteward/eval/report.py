"""Turn the recorded answers into results/summary.json and the README's tables.

Everything here is computed from files in the repository: runs/<run>/results.jsonl (the
answers), data/labels/decisions.jsonl (the stewards' articles and penalties) and the two
manifests (event dates, rule issues). No FIA text and no model call is needed, so anyone
can recompute every number from the records.

Besides the three configurations, two answers that need no model are scored as baselines:

    most common      the article and the penalty seen most often in decisions of earlier
                     events. What you get by always guessing the usual thing
    majority of 5    the article and the penalty seen most often among the 5 past decisions
                     search found for the question. What retrieval alone gives, without a
                     model reading anything

And the evaluation is checked against itself (system design, section 4.6).
"""

import json
from collections import Counter
from pathlib import Path

from .. import config, manifest
from . import score
from .answers import CONFIGS, latest_rows, read_rows

SUMMARY = config.ROOT / "results" / "summary.json"
PAIRS = (("rules", "none"), ("rules_and_decisions", "rules"), ("rules_and_decisions", "none"))
COMPARED = ("article_hit", "penalty", "both")


def load_labels(path: Path = config.DECISION_LABELS) -> dict[str, dict]:
    return {row["id"]: row for row in (json.loads(line) for line in path.read_text("utf-8").splitlines())}


def gold_for(ids: list[str], labels: dict[str, dict]) -> score.Gold:
    return score.Gold(
        articles={a for i in ids for a in labels[i]["articles"]},
        penalties=[labels[i]["penalty"] for i in ids],
        kind=labels[ids[0]]["kind"],
    )


def marks_for(row: dict, labels: dict[str, dict]) -> score.Marks | None:
    """None when the call gave no answer: it is counted as failed, not scored as wrong."""
    if row["status"] != "ok":
        return None
    a = row["answer"]
    return score.score(a["articles"], a["penalty"], gold_for(row["ids"], labels))


def _breakdown(rows: list[dict], labels: dict, key) -> dict:
    groups: dict[str, list[score.Marks]] = {}
    totals: Counter = Counter()
    for row in rows:
        totals[key(row)] += 1
        marks = marks_for(row, labels)
        if marks is not None:
            groups.setdefault(key(row), []).append(marks)
    return {name: {"questions": totals[name], "answered": len(groups.get(name, [])), **score.mean(groups.get(name, []))}
            for name in sorted(totals)}


def configuration(rows: list[dict], labels: dict) -> dict:
    """Scores and costs of one configuration of one run."""
    answered = [m for m in (marks_for(r, labels) for r in rows) if m is not None]
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(rows) or 1
    return {
        "questions": len(rows),
        "answered": len(ok),
        "failed": dict(Counter(r["status"] for r in rows if r["status"] != "ok")),
        "scores": score.mean(answered),
        "citation_check_passed": sum(r["check"]["passed"] for r in ok) / (len(ok) or 1),
        "cost_per_question": sum(r["cost"] for r in rows) / n,
        "cost_total": sum(r["cost"] for r in rows),
        "seconds_per_question": sum(r["seconds"] for r in rows) / n,
        "tokens_per_question": {
            "input": sum(r["usage"]["input_tokens"] for r in rows) / n,
            "output": sum(r["usage"]["output_tokens"] for r in rows) / n,
            "reasoning": sum(r["usage"]["reasoning_tokens"] for r in rows) / n,
        },
        "by_kind": _breakdown(rows, labels, lambda r: r["kind"]),
        "by_basis": _breakdown(rows, labels, lambda r: "fixed" if r["kind"] in score.FIXED_KINDS else "discretionary"),
    }


def differences(by_config: dict[str, list[dict]], labels: dict) -> dict:
    """Paired differences between configurations, on the questions both answered."""
    out = {}
    for a, b in PAIRS:
        if a not in by_config or b not in by_config:
            continue
        first = {r["question"]: marks_for(r, labels) for r in by_config[a]}
        second = {r["question"]: marks_for(r, labels) for r in by_config[b]}
        both = [q for q in first if first[q] is not None and second.get(q) is not None]
        out[f"{a} - {b}"] = {
            metric: score.paired_bootstrap(
                [first[q].as_dict()[metric] for q in both], [second[q].as_dict()[metric] for q in both]
            )
            for metric in COMPARED
        }
    return out


def _most_common(values: list) -> object | None:
    """The most frequent value; on a tie, the one seen first (the closest decision)."""
    return Counter(values).most_common(1)[0][0] if values else None


def _label(penalty: dict) -> tuple:
    return (penalty["type"], penalty["value"], penalty["unit"])


def _penalty_of(label: tuple | None) -> dict | None:
    return None if label is None else dict(zip(("type", "value", "unit"), label))


def baselines(rows: list[dict], labels: dict, rounds: dict[str, int]) -> dict:
    """The two answers that need no model, on the questions of `rows` (one row per question)."""
    common: list[score.Marks] = []
    majority: list[score.Marks] = []
    for row in rows:
        gold = gold_for(row["ids"], labels)
        earlier = [d for d in labels.values() if rounds[d["event"]] < rounds[row["event"]]]
        article = _most_common([a for d in earlier for a in d["articles"]])
        penalty = _most_common([_label(d["penalty"]) for d in earlier])
        common.append(score.score([article] if article else [], _penalty_of(penalty), gold))

        found = [labels[i] for i in row["shown"]["decisions"]]
        article = _most_common([a for d in found for a in d["articles"]])
        penalty = _most_common([_label(d["penalty"]) for d in found])
        majority.append(score.score([article] if article else [], _penalty_of(penalty), gold))
    return {
        "most_common": {"questions": len(common), **score.mean(common)},
        "majority_of_5": {"questions": len(majority), **score.mean(majority)},
    }


def checks(rows: list[dict], labels: dict, rounds: dict[str, int], regulations: dict, dates: dict[str, str]) -> dict:
    """The evaluation checked against itself, recomputed from the records."""
    questions = list({r["question"]: r for r in rows}.values())
    gold_in = [
        score.score(labels[r["ids"][0]]["articles"], labels[r["ids"][0]]["penalty"], gold_for(r["ids"], labels))
        for r in questions
    ]
    empty = [score.score([], None, gold_for(r["ids"], labels)) for r in questions]
    late = [r["question"] for r in rows if any(rounds[labels[i]["event"]] >= rounds[r["event"]] for i in r["shown"]["decisions"])]
    wrong_issue = []
    for r in rows:
        in_force = set(manifest.issues_in_force(regulations, dates[r["event"]]))
        wrong_issue += [f"{r['question']}: {key}" for key in r["shown"]["articles"] if key.split("/")[0] not in in_force]
    return {
        "gold_in_scores": score.mean(gold_in),
        "empty_answer_scores": score.mean(empty),
        "searches_that_returned_own_or_later_event": len(late),
        "articles_shown_from_an_issue_not_in_force": len(wrong_issue),
        "search_off_sends_the_no_search_prompt": "tests/test_eval_answers.py::test_with_search_switched_off_every_configuration_sends_the_no_search_prompt",
    }


def summarise(run_dirs: list[Path], retrieval_files: list[Path] = ()) -> dict:
    labels = load_labels()
    events = manifest.load()["events"]
    rounds = {e["slug"]: e["round"] for e in events}
    dates = {e["slug"]: e["date"] for e in events}
    regulations = manifest.load(config.REGULATIONS_MANIFEST)

    summary: dict = {"runs": {}, "answers": {}, "retrieval": {}}
    full: dict[str, list[dict]] = {}
    for path in retrieval_files:
        data = json.loads(path.read_text("utf-8"))
        summary["retrieval"][data["split"]] = data
    for run_dir in run_dirs:
        meta = json.loads((run_dir / "run.json").read_text("utf-8"))
        rows = list(latest_rows(read_rows(run_dir / "results.jsonl")).values())
        by_config = {c: [r for r in rows if r["config"] == c] for c in CONFIGS if any(r["config"] == c for r in rows)}
        name = run_dir.name  # two runs of one model (dev and test) must not overwrite each other
        summary["runs"][name] = meta
        summary["answers"][name] = {
            "configurations": {c: configuration(rs, labels) for c, rs in by_config.items()},
            "differences": differences(by_config, labels),
            "checks": checks(rows, labels, rounds, regulations, dates),
        }
        if "rules_and_decisions" in by_config:
            # On the questions the configuration answered, so the rows of one table share a set.
            answered = [r for r in by_config["rules_and_decisions"] if r["status"] == "ok"]
            summary["answers"][name]["baselines"] = baselines(answered, labels, rounds)
        full[name] = by_config.get("rules_and_decisions", [])
    summary["between_models"] = between_models(full, labels)
    return summary


def between_models(full: dict[str, list[dict]], labels: dict) -> dict:
    """The product configuration of each pair of runs, paired on the questions both answered."""
    names = [n for n, rows in full.items() if rows]
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            first = {r["question"]: marks_for(r, labels) for r in full[a]}
            second = {r["question"]: marks_for(r, labels) for r in full[b]}
            both = [q for q in first if first[q] is not None and second.get(q) is not None]
            out[f"{a} - {b}"] = {
                metric: score.paired_bootstrap(
                    [first[q].as_dict()[metric] for q in both], [second[q].as_dict()[metric] for q in both]
                )
                for metric in COMPARED
            }
    return out


def write(summary: dict, path: Path = SUMMARY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", "utf-8")


# ---------------------------------------------------------------- what `eval --report` prints

NAMES = {
    "none": "Nothing (answers from memory)",
    "rules": "Retrieved rules",
    "rules_and_decisions": "Retrieved rules and past decisions",
}
KIND_NAMES = {
    "judgment_incident": "Judgment calls",
    "procedural_or_technical": "Procedural and technical",
    "component_allowance": "Power unit parts",
    "pit_lane_speeding": "Pit lane speeding",
}


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def markdown(summary: dict) -> str:
    """The tables, ready to paste into the README."""
    lines: list[str] = []
    for name, result in summary["answers"].items():
        configs = result["configurations"]
        meta = summary["runs"][name]
        lines += [
            f"### {meta['model']} ({meta['reasoning_effort']}), {meta['split']}, run {name}",
            "",
            "| The model is given | Rule right | Cited articles right | Outcome type right | Outcome right | Both right | Failed calls | Cost per question |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for c, s in configs.items():
            sc = s["scores"]
            failed = sum(s["failed"].values())
            lines.append(
                f"| {NAMES[c]} | {_pct(sc['article_hit'])} | {_pct(sc['citation_precision'])} | {_pct(sc['penalty_type'])} "
                f"| {_pct(sc['penalty'])} | {_pct(sc['both'])} | {failed} | ${s['cost_per_question']:.4f} |"
            )
        for b, s in result.get("baselines", {}).items():
            label = {"most_common": "No model: the most common article and penalty so far",
                     "majority_of_5": "No model: the majority of the 5 past decisions found"}[b]
            lines.append(
                f"| {label} | {_pct(s['article_hit'])} | {_pct(s['citation_precision'])} | {_pct(s['penalty_type'])} "
                f"| {_pct(s['penalty'])} | {_pct(s['both'])} | – | $0 |"
            )
        lines += ["", "| Difference | Questions | Rule right | Outcome right | Both right |", "|---|---|---|---|---|"]
        for pair, metrics in result["differences"].items():
            cells = [_points(metrics[k]) for k in COMPARED]
            lines.append(f"| {pair} | {metrics['both']['questions']} | " + " | ".join(cells) + " |")
        full = configs.get("rules_and_decisions")
        if full:
            lines += ["", "| Kind of incident | Questions | Rule right | Outcome right | Both right |", "|---|---|---|---|---|"]
            for kind, s in full["by_kind"].items():
                lines.append(
                    f"| {KIND_NAMES.get(kind, kind)} | {s['questions']} | {_pct(s['article_hit'])} | {_pct(s['penalty'])} | {_pct(s['both'])} |"
                )
        lines.append("")
    for pair, metrics in summary.get("between_models", {}).items():
        cells = [_points(metrics[k]) for k in COMPARED]
        lines.append(
            f"Rules and past decisions, {pair}, on {metrics['both']['questions']} shared questions: "
            f"rule {cells[0]}, outcome {cells[1]}, both {cells[2]}"
        )
    return "\n".join(lines)


def _points(m: dict) -> str:
    if m["questions"] == 0:
        return "no shared questions"
    return f"{m['difference'] * 100:+.0f} points ({m['low'] * 100:+.0f} to {m['high'] * 100:+.0f})"
