"""Measure search with numbers. No chat model is called here.

Every decision of the chosen split becomes a question: "what happened", with the
stewards' decision hidden. Search then looks through the decisions of earlier events.
A retrieved decision counts as right when it was decided under one of the same
articles as the question's own decision.

    hit@5        share of questions with at least one right decision among the 5
    precision@5  share of the 5 retrieved decisions that are right, averaged over questions

"Same article" stands in for "similar incident". It is a rule a program can check, not
a perfect one: one article can cover different situations.

The same questions are then asked of the rules, in the issues in force on the event's date:

    recall@8     share of the articles the stewards cited that are among the 8 retrieved
                 articles, averaged over questions
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .. import config, index
from ..parse import labels
from ..search import DecisionSearch, RuleSearch


@dataclass
class Question:
    text: str
    event: str
    round: int
    date: str
    ids: list[str]  # the decisions it was made from: several when they share one text
    articles: set[str]  # gold answer: the articles of those decisions


@dataclass
class Score:
    method: str
    hit: float
    precision: float


def load_reworded(path: Path = config.PARAPHRASED_QUESTIONS) -> dict[str, str]:
    """Decision id -> the same incident in other words than the stewards used."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return {row["id"]: row["question"] for row in rows}


def build_questions(
    records: list[dict], split: str, reworded: dict[str, str] | None = None
) -> tuple[list[Question], Counter]:
    """The questions of one split, and how many decisions were left out and why.

    Without `reworded` the question is the decision's own searched text (session and
    Fact). With it, the question is the reworded text for that decision.
    """
    questions: dict[tuple[str, str], Question] = {}
    left_out: Counter = Counter()
    for record in records:
        if labels.split_for(record["date"]) != split:
            continue
        if record["layout"] == "car_table":
            left_out["the Fact only points at a table of cars"] += 1
            continue
        if not record["articles"]:
            left_out["no article to score against"] += 1
            continue
        text = index.chunk_text(record) if reworded is None else reworded.get(record["id"])
        if text is None:
            left_out["no reworded question"] += 1
            continue
        if labels.normalise_articles(text) or "Article" in text:
            left_out["the question names an article"] += 1  # that would give the answer away
            continue

        # One incident can produce one decision per car, all with the same Fact. That is
        # one question with several gold answers, not the same question asked three times.
        key = (record["event"], text)
        if key not in questions:
            questions[key] = Question(text, record["event"], record["round"], record["date"], [], set())
        questions[key].ids.append(record["id"])
        questions[key].articles.update(record["articles"])
    return list(questions.values()), left_out


def out_of_reach(records: list[dict], questions: list[Question]) -> int:
    """Questions no search can get right: no earlier decision has any of their articles."""
    count = 0
    for question in questions:
        seen = {article for r in records if r["round"] < question.round for article in r["articles"]}
        count += not (question.articles & seen)
    return count


def evaluate(searcher: DecisionSearch, questions: list[Question], method: str, k: int = config.TOP_K) -> Score:
    hits = 0
    precision = 0.0
    for question in questions:
        results = searcher.search(question.text, before_round=question.round, method=method, k=k)

        # The rule of search.py, checked on every real question and not only in a unit test.
        late = [r["id"] for r in results if r["round"] >= question.round]
        if late:
            raise AssertionError(f"{method} search for a {question.event} question returned {late}")

        right = [bool(question.articles & set(r["articles"])) for r in results]
        hits += any(right)
        precision += sum(right) / k  # fewer than k results count as wrong ones
    total = len(questions) or 1
    return Score(method, hits / total, precision / total)


def report(title: str, records: list[dict], questions: list[Question], left_out: Counter, scores: list[Score]) -> str:
    """One block of the text `eval --retrieval` prints."""
    k = config.TOP_K
    lines = [f"{title}: {len(questions)} questions"]
    for reason, count in left_out.most_common():
        lines.append(f"  left out {count:>3}  {reason}")
    if questions:
        unreachable = out_of_reach(records, questions)
        best = 1 - unreachable / len(questions)
        lines.append(f"  no earlier decision under the same article: {unreachable} (best possible hit@{k} {best:.3f})")
    lines += ["", f"  {'method':<8}{f'hit@{k}':>8}{f'precision@{k}':>14}"]
    lines += [f"  {score.method:<8}{score.hit:>8.3f}{score.precision:>14.3f}" for score in scores]
    return "\n".join(lines)


# ---------------------------------------------------------------- rules


@dataclass
class RuleScore:
    method: str
    recall: float


def holding(cited: str, ids_in_issue: set[str]) -> set[str]:
    """The articles of one issue whose text holds a cited article.

    The stewards cite down to a point ("ISC-L:IV.2.d"); the rules are cut at numbered
    paragraphs ("ISC-L:IV.2", whose text holds points a) to e)). So a citation is held by:
    the article with the same id; else its nearest parent; else, when the citation is
    broader than the paragraphs ("F1-B:5.11"), every article under it. Empty: not found.
    """
    if cited in ids_in_issue:
        return {cited}
    book, number = cited.split(":")
    parts = number.split(".")
    for end in range(len(parts) - 1, 0, -1):
        parent = f"{book}:{'.'.join(parts[:end])}"
        if parent in ids_in_issue:
            return {parent}
    return {i for i in ids_in_issue if i.startswith(cited + ".")}


@dataclass
class RuleReach:
    """Which cited articles a rule search could find at all."""

    cited: int = 0
    outside_the_books: Counter = field(default_factory=Counter)  # book -> cited articles of a book not included
    not_in_the_issue: list[str] = field(default_factory=list)  # cited articles of an included book, not found
    best_recall: float = 0.0


def _targets(searcher: RuleSearch, question: Question) -> dict[str, set[str] | None]:
    """Cited article -> the article ids that hold it in the issues in force; None if its book is not included."""
    ids_by_book = {searcher.book_of[issue]: searcher.ids_in.get(issue, set()) for issue in searcher.issues_on(question.date)}
    targets: dict[str, set[str] | None] = {}
    for cited in sorted(question.articles):
        book = cited.split(":")[0]
        targets[cited] = holding(cited, ids_by_book[book]) if book in ids_by_book else None
    return targets


def rule_reach(searcher: RuleSearch, questions: list[Question]) -> RuleReach:
    reach = RuleReach()
    best = 0.0
    for question in questions:
        targets = _targets(searcher, question)
        reach.cited += len(targets)
        for cited, held_by in targets.items():
            if held_by is None:
                reach.outside_the_books[cited.split(":")[0]] += 1
            elif not held_by:
                reach.not_in_the_issue.append(f"{question.event}: {cited}")
        best += sum(bool(held_by) for held_by in targets.values()) / len(targets)
    reach.best_recall = best / (len(questions) or 1)
    return reach


def evaluate_rules(
    searcher: RuleSearch, questions: list[Question], method: str, k: int = config.TOP_K_RULES
) -> RuleScore:
    recall = 0.0
    for question in questions:
        results = searcher.search(question.text, date=question.date, method=method, k=k)

        # The rule of search.py, checked on every real question and not only in a unit test.
        in_force = set(searcher.issues_on(question.date))
        wrong = [article["key"] for article in results if article["issue"] not in in_force]
        if wrong:
            raise AssertionError(f"{method} rule search for a {question.event} question returned {wrong}")

        retrieved = {article["id"] for article in results}
        targets = _targets(searcher, question)
        recall += sum(bool(held_by and held_by & retrieved) for held_by in targets.values()) / len(targets)
    return RuleScore(method, recall / (len(questions) or 1))


def report_rules(title: str, questions: list[Question], reach: RuleReach, scores: list[RuleScore]) -> str:
    """One block of the rules part of what `eval --retrieval` prints."""
    k = config.TOP_K_RULES
    lines = [f"{title}: {len(questions)} questions citing {reach.cited} articles"]
    for book, count in sorted(reach.outside_the_books.items()):
        lines.append(f"  in a rule book that is not included ({book}): {count}")
    if reach.not_in_the_issue:
        lines.append(f"  not found in the issue in force: {', '.join(reach.not_in_the_issue)}")
    lines.append(f"  best possible recall@{k}: {reach.best_recall:.3f}")
    lines += ["", f"  {'method':<8}{f'recall@{k}':>10}"]
    lines += [f"  {score.method:<8}{score.recall:>10.3f}" for score in scores]
    return "\n".join(lines)
