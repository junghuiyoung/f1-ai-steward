"""From a described incident to an answer: the article, the likely penalty, and the grounds.

    1. search   the 5 closest decisions of earlier events, and the articles in force on
                the event's date (8 found by search, plus the ones those decisions cite)
    2. prompt   instructions, then the articles, then the decisions, then the incident
    3. model    one call; the answer comes back as an `Answer` (structured output)
    4. check    every article and decision the answer cites must be one the model was shown
    5. count    how the closest earlier decisions under the answer's article ended

Steps 4 and 5 are code, not the model. A model can invent an article number or miscount
"5 of 8"; code that reads the search results cannot. The check is done once: a citation
that fails it is flagged and left out of the grounds shown, and the model is not asked again.
"""

import textwrap
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import config
from .llm import client
from .parse import labels
from .search import DecisionSearch, RuleSearch


class Answer(BaseModel):
    """What the model must return. Strict structured output needs every field to be required,
    so a field that can be empty is "X or None" rather than optional.

    The penalty types are the labels step 1 made from the stewards' decisions, so an answer
    can be compared with a decision field by field. The article is a free string, not a
    list to choose from: that list would hand the answer to a model that was shown no rules.
    """

    articles: list[str] = Field(
        description="The articles the incident breaches, at least one. When articles are given above, the id "
        "shown in square brackets before each, without the brackets, e.g. ISC-L:IV.2; otherwise the article numbers."
    )
    penalty_type: Literal[labels.PENALTY_TYPES] = Field(description="The penalty the stewards would most likely give.")
    penalty_value: int | None = Field(description="Seconds, grid places or euros; null when the penalty has no number.")
    penalty_unit: Literal["s", "places", "EUR"] | None = Field(
        description="s for a time penalty or a stop and go, places for a grid drop, EUR for a fine; otherwise null."
    )
    rationale: str = Field(description="Why, in at most three sentences.")
    precedents_used: list[str] = Field(
        description="The ids of the earlier decisions this answer relies on, as shown in square brackets, "
        "without the brackets. Empty if none."
    )


INSTRUCTIONS = """\
You assist the stewards of a Formula 1 event. You are given the articles of the rules in
force at the event, earlier stewards' decisions that search found for similar incidents,
and a new incident.

Say which articles the incident breaches and which penalty the stewards would most likely give.

- Always name at least one article. When articles and decisions are given here, cite only those,
  by the id shown in square brackets before each, written exactly as shown, without the brackets.
- The earlier decisions show how the stewards apply an article in practice. Prefer the penalty
  they gave in comparable cases, and list the decisions you relied on.
- Search finds decisions by similar wording. Some may not be comparable; do not rely on those.
- If the stewards would most likely take no further action, answer no_further_action and still
  name the article the incident would be investigated under."""


# ---------------------------------------------------------------- 2. prompt


def prompt_version() -> str:
    """A short fingerprint of the whole prompt, recorded with every evaluation run, so a
    number can always be traced to the prompt that produced it.

    It covers the instructions, the Answer format and the template that lays out the
    articles, the decisions and the incident: the template is filled with a made-up
    example, empty and full, and the result is hashed.
    """
    import hashlib
    import json

    article = {"id": "X:1", "headings": ["H"], "text": "T"}
    decision = {"id": "d", "event": "e", "session": "s", "fact": "f", "articles": ["X:1"],
                "penalty": {"type": "warning", "value": None, "unit": None}}
    filled = [m.content for m in messages("q", [article], [decision]) + messages("q", [], [])]
    text = json.dumps([filled, Answer.model_json_schema()], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def penalty_label(penalty: dict) -> str:
    """{'type': 'time_penalty', 'value': 5, 'unit': 's'} -> 'time_penalty 5 s'."""
    if penalty["value"] is None:
        return penalty["type"]
    return f"{penalty['type']} {penalty['value']} {penalty['unit']}"


def messages(question: str, articles: list[dict], decisions: list[dict]) -> list:
    """The prompt: a system message with the instructions, then one message with the rest.

    Each article and decision starts with its id in square brackets, the form the answer
    has to cite. The incident comes last, after everything it is to be judged against.
    """
    rules = [f"[{a['id']}] {' > '.join(a['headings'])}\n{a['text']}" for a in articles]
    earlier = [
        f"[{d['id']}] {d['event']}, {d['session'] or 'no session'}\n"
        f"Fact: {d['fact']}\n"
        f"Articles: {', '.join(d['articles']) or 'none'}\n"
        f"Penalty: {penalty_label(d['penalty'])}"
        for d in decisions
    ]
    parts = [
        "# Articles of the rules in force",
        "\n\n".join(rules) or "None.",
        "# Earlier stewards' decisions",
        "\n\n".join(earlier) or "None.",
        "# The incident",
        question,
    ]
    return [SystemMessage(INSTRUCTIONS), HumanMessage("\n\n".join(parts))]


# ---------------------------------------------------------------- 4. check


def related(a: str, b: str) -> bool:
    """True when one article id is the other or lies inside it, like ISC-L:IV.2 and ISC-L:IV.2.d.

    The rules are cut at numbered paragraphs and the stewards cite down to a point, so
    the same rule as `search.holding`, the one the rule search was measured with.
    """
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


@dataclass
class Check:
    articles: list[str]  # cited, and among what the model was shown
    unknown_articles: list[str]  # cited, and not among what the model was shown
    decisions: list[str]
    unknown_decisions: list[str]

    @property
    def passed(self) -> bool:
        return bool(self.articles) and not (self.unknown_articles or self.unknown_decisions)


def _bare(cited: str) -> str:
    """'[ISC-L:IV.2]' -> 'ISC-L:IV.2'. The brackets mark an id in the prompt; a model that
    copies them has still written the id. Nothing else about a citation is forgiven."""
    return cited.strip().removeprefix("[").removesuffix("]").strip()


def check(answer: Answer, articles: list[dict], decisions: list[dict]) -> Check:
    """Was every article and decision the answer cites in the prompt?

    An article counts as shown when it is one of the articles or is cited by one of the
    decisions, so a decision's Section C article (a book that is not searched) can be cited.
    This catches invented citations. It does not check that the reason follows from them.
    """
    shown = {a["id"] for a in articles} | {cited for d in decisions for cited in d["articles"]}
    cited = list(dict.fromkeys(_bare(a) for a in answer.articles))
    good = [a for a in cited if any(related(a, s) for s in shown)]
    ids = {d["id"] for d in decisions}
    used = list(dict.fromkeys(_bare(d) for d in answer.precedents_used))
    return Check(
        articles=good,
        unknown_articles=[a for a in cited if a not in good],
        decisions=[d for d in used if d in ids],
        unknown_decisions=[d for d in used if d not in ids],
    )


# ---------------------------------------------------------------- 5. count


@dataclass
class Outcomes:
    articles: list[str]  # what was counted: the answer's articles that passed the check
    looked_at: int  # how many of the closest earlier decisions were looked at
    matching: list[dict]  # those decided under one of the articles
    counts: list[tuple[str, int]]  # penalty -> how many, most common first


def outcomes(articles: list[str], pool: list[dict]) -> Outcomes:
    """How the earlier decisions in `pool` that were decided under one of `articles` ended."""
    matching = [d for d in pool if any(related(a, c) for a in articles for c in d["articles"])]
    counts = Counter(penalty_label(d["penalty"]) for d in matching).most_common()
    return Outcomes(articles, len(pool), matching, counts)


# ---------------------------------------------------------------- all five


@dataclass
class Result:
    question: str
    articles: list[dict]  # the articles in the prompt
    decisions: list[dict]  # the decisions in the prompt
    reply: client.Reply
    check: Check | None  # None when there is no answer to check
    outcomes: Outcomes | None
    search_seconds: float  # the question's embedding, the searches


def answer(
    question: str,
    decision_search: DecisionSearch,
    rule_search: RuleSearch,
    date: str | None = None,
    before_round: int | None = None,
    model: str = config.ANSWER_MODEL,
    effort: str = config.REASONING_EFFORT,
) -> Result:
    """Answer one incident. `date` and `before_round` say which event it belongs to.

    Decisions come from events before `before_round` only; articles from the issues in
    force on `date`. Without them: every decision, and the latest issues.
    """
    start = perf_counter()
    decisions = decision_search.search(question, before_round=before_round)
    # A second, wider search for the counts. The 5 above are the ones step 2 measured.
    pool = decision_search.search(question, before_round=before_round, k=config.OUTCOME_POOL)
    articles = rule_search.search(question, date=date, decisions=decisions)
    search_seconds = perf_counter() - start

    reply = client.ask(messages(question, articles, decisions), Answer, model=model, effort=effort)
    if reply.status != "ok":
        return Result(question, articles, decisions, reply, None, None, search_seconds)
    checked = check(reply.parsed, articles, decisions)
    return Result(question, articles, decisions, reply, checked, outcomes(checked.articles, pool), search_seconds)


# ---------------------------------------------------------------- what `ask` prints

_NO_ANSWER = {
    "refused": "the model refused, or a content filter stopped it",
    "truncated": f"the answer was cut off at {config.MAX_OUTPUT_TOKENS:,} output tokens",
    "unparsed": "the reply did not fit the Answer format",
    "timeout": f"no reply within {config.MODEL_TIMEOUT_SECONDS:.0f} seconds",
    "rate_limited": "OpenAI answered 429 (too many requests); try again in a minute",
    "error": "no connection to OpenAI, or a server error",
}


def report(result: Result, issues: list[str]) -> str:
    """The text `ask` prints. `issues` are the rule issues the articles were taken from."""
    lines: list[str] = []
    a = result.reply.parsed
    if a is None:
        lines += [f"No answer: {_NO_ANSWER[result.reply.status]}.", f"  {result.reply.error}".rstrip(), ""]
    else:
        checked = result.check
        size = f" {a.penalty_value} {a.penalty_unit}" if a.penalty_value is not None else ""
        reason = textwrap.wrap(a.rationale, 88)
        lines += [
            f"Articles   {', '.join(checked.articles) or 'none that passed the check'}",
            f"Penalty    {a.penalty_type}{size}",
            f"Reason     {reason[0] if reason else ''}",
            *(f"           {line}" for line in reason[1:]),
            f"Relied on  {', '.join(checked.decisions) or 'no earlier decision'}",
            "",
        ]
        if checked.passed:
            lines.append("Citation check: passed. Every article and decision cited was shown to the model.")
        else:
            lines.append("Citation check: FAILED. Left out of the grounds above:")
            if not a.articles:
                lines.append("  the answer cites no article")
            lines += [f"  {x}  is not among the articles shown" for x in checked.unknown_articles]
            lines += [f"  {x}  is not among the decisions shown" for x in checked.unknown_decisions]
        lines.append("")

        counted = result.outcomes
        if counted.articles:
            lines.append(
                f"Earlier decisions under {', '.join(counted.articles)}: "
                f"{len(counted.matching)} of the {counted.looked_at} closest"
            )
            lines += [f"  {n:>3}  {penalty}" for penalty, n in counted.counts]
            lines.append("")

    usage = result.reply.usage
    lines += [
        f"Shown to the model: {len(result.decisions)} earlier decisions "
        f"({', '.join(d['id'] for d in result.decisions) or 'none'})",
        f"  and {len(result.articles)} articles from {', '.join(issues)}",
        f"Search {result.search_seconds:.1f} s. Model {result.reply.model} (reasoning {config.REASONING_EFFORT}) "
        f"{result.reply.seconds:.1f} s: {usage.input_tokens:,} tokens in ({usage.cached_tokens:,} cached), "
        f"{usage.output_tokens:,} out ({usage.reasoning_tokens:,} of them reasoning). Cost ${result.reply.cost:.4f}",
    ]
    return "\n".join(lines)
