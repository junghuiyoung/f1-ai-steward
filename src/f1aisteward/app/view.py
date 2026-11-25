"""What the screen shows, as plain data: names for article ids and penalties, the basis of
the penalty, and how an answer compares with the stewards' decision.

The page (app/static/index.html) only lays this out. Every judgement about an answer is
made here, in Python, with the same rules the evaluation scores with (eval/score.py), so
"Matches" on the screen means what "right" means in the README.
"""

import re

from ..eval import score
from ..parse import labels

# ---------------------------------------------------------------- names


def article_label(article_id: str) -> str:
    """How the stewards write an article: 'ISC-L:IV.2.d' -> 'ISC App. L Ch. IV Art. 2 d)'."""
    book, _, number = article_id.partition(":")
    parts = number.split(".")
    numbers = [p for p in parts if not re.fullmatch(r"[a-z]+", p)]
    points = "".join(f" {p})" for p in parts[len(numbers):])
    if book.startswith("F1-"):  # "F1-B:1.8.6" -> "B1.8.6", the way the F1 Regulations number themselves
        return f"{book[3:]}{number}"
    if book == "ISC":
        return f"ISC Art. {number}"
    appendix = book.split("-")[1]
    if appendix == "L":  # Appendix L restarts its numbering in every chapter: "IV.2"
        return f"ISC App. L Ch. {numbers[0]} Art. {'.'.join(numbers[1:])}{points}"
    return f"ISC App. {appendix} Art. {'.'.join(numbers)}{points}"


def heading_name(heading: str) -> str:
    """'ARTICLE 12.2 BREACH OF RULES' -> 'Breach of rules'; 'B1.8 Driving' -> 'Driving'."""
    name = re.sub(r"^(?:ARTICLE\s+)?[A-Z]?\d+(?:\.\d+)*\.?\s*[:–-]?\s*", "", heading.strip())
    return name.capitalize() if name.isupper() else name


def penalty_text(penalty: dict) -> str:
    """{'type': 'time_penalty', 'value': 5, 'unit': 's'} -> '5 second time penalty'."""
    kind, value = penalty["type"], penalty["value"]
    if kind == "time_penalty":
        return f"{value} second time penalty"
    if kind == "stop_go":
        return f"{value} second stop and go penalty" if value else "Stop and go penalty"
    if kind == "grid_drop":
        return f"{value} place grid drop"
    if kind == "fine":
        return f"€{value:,} fine"
    return {
        "drive_through": "Drive-through penalty",
        "pit_lane_start": "Start from the pit lane",
        "disqualification": "Disqualification",
        "reprimand": "Reprimand",
        "warning": "Warning",
        "no_further_action": "No further action",
    }.get(kind, "Another penalty")


def event_short(name: str) -> str:
    """'São Paulo Grand Prix' -> 'São Paulo GP'."""
    return name.replace("Grand Prix", "GP")


_BOOKS = {"F1-B": "Sporting Regulations", "ISC": "International Sporting Code", "ISC-L": "Appendix L", "ISC-H": "Appendix H"}
_MONTHS = "January February March April May June July August September October November December".split()


def issue_name(issue: dict) -> str:
    """'F1-B-09' -> 'Sporting Regulations, Issue 09'; an appendix -> 'Appendix L of June 2026'."""
    book = issue["book"]
    if book == "F1-B":
        return f"{_BOOKS[book]}, Issue {issue['id'].rsplit('-', 1)[1]}"
    year, month, _ = issue["in_force_from"].split("-")
    return f"{_BOOKS.get(book, book)} of {_MONTHS[int(month) - 1]} {year}"


# ---------------------------------------------------------------- judgements


def basis(question: str, articles: list[str], matching: list[dict]) -> str:
    """'fixed' when a table in the rules sets the penalty; 'rules_only' when no earlier
    decision under the answer's article was found; otherwise 'usual'."""
    if labels.classify_kind(question, articles) in score.FIXED_KINDS:
        return "fixed"
    return "usual" if matching else "rules_only"


def compare(articles: list[str], penalty: dict, decision: dict) -> dict[str, str]:
    """'yes', 'partial' or 'no' for the rule and for the outcome, against one decision.

    Rule: the same articles at article-number level is a match; some in common is partly.
    Outcome: the same type, value and unit is a match; the same type alone is partly.

    `articles` are the ones the screen shows: those that passed the citation check. The
    evaluation scores every article an answer cites, because the no-search configuration
    is shown nothing and would otherwise score zero by construction. When every citation
    passes, as it did for all test answers that were shown documents, the two agree.
    """
    ours = {score.article_number(a) for a in score.as_ids(articles)}
    theirs = {score.article_number(a) for a in decision["articles"]}
    rule = "yes" if ours and ours == theirs else "partial" if ours & theirs else "no"
    if score.same_penalty(penalty, decision["penalty"]):
        outcome = "yes"
    elif penalty["type"] == decision["penalty"]["type"]:
        outcome = "partial"
    else:
        outcome = "no"
    return {"rule": rule, "outcome": outcome}
