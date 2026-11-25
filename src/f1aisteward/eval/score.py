"""Score an answer against the stewards' decision. Rules only: no model grades another model.

    article hit         one of the answer's articles is one the stewards cited
    citation precision  the share of the answer's articles that the stewards cited
    penalty type        the same type of penalty as the stewards gave
    penalty             the same type, and the same value and unit (5 s, 3 places, €5,000)
    both                article hit and penalty

Articles are compared at article-number level: the letters and small roman numerals
after the last number are dropped, so ISC-L:IV.2.d is ISC-L:IV.2 and F1-B:1.6.2.b.i is
F1-B:1.6.2. The rules are cut at numbered paragraphs and the stewards cite down to a
point; a point is part of its article. A broader number is NOT a match: F1-B:1.8 does
not match F1-B:1.8.5, or an answer could cite a whole chapter and hit every article in it.

An answer that is not written as an id ("Appendix L, Chapter IV, Article 2 d)") is first
read with the normaliser that made the stewards' labels. Without that, the configuration
that is shown no ids (no search) would be scored on notation, not on knowledge.

One question can stand for several decisions: one per car in the same incident, all with
the same Fact (eval/retrieval.py). Its gold articles are all their articles, and a
penalty is right when it is the penalty of any of them.
"""

import random
import re
from dataclasses import dataclass

from ..parse import labels

# An article id: a book, a colon, then a number or a chapter. Also accepted with a space
# for the colon ("ISC 12.2.1.i"), which is how a model writes an id it was never shown.
_ID = re.compile(r"^(?P<book>F1-[A-F]|ISC(?:-[A-Z])?)\s*[:\s]\s*(?P<number>[0-9IVX][\w.]*)$")

# Fixed by the rules: a table in the regulations gives the penalty. The other two kinds
# are the stewards' judgment.
FIXED_KINDS = ("component_allowance", "pit_lane_speeding")


@dataclass
class Gold:
    articles: set[str]
    penalties: list[dict]  # one per decision the question stands for
    kind: str


@dataclass
class Marks:
    article_hit: bool
    citation_precision: float
    penalty_type: bool
    penalty: bool

    @property
    def both(self) -> bool:
        return self.article_hit and self.penalty

    def as_dict(self) -> dict[str, float]:
        return {
            "article_hit": float(self.article_hit),
            "citation_precision": self.citation_precision,
            "penalty_type": float(self.penalty_type),
            "penalty": float(self.penalty),
            "both": float(self.both),
        }


METRICS = ("article_hit", "citation_precision", "penalty_type", "penalty", "both")


def as_ids(cited: list[str]) -> list[str]:
    """The answer's articles as ids. An id is kept; anything else goes through the normaliser.

    The normaliser reads a bare number as an article only after the word "Article", as
    the stewards write it. A cited number is an article by definition, so a bare "33.3"
    is read as "Article 33.3". A citation the normaliser cannot read is kept as it was;
    it matches nothing.
    """
    ids: list[str] = []
    for text in cited:
        text = text.strip().strip("[]").strip()
        match = _ID.match(text)
        if match:
            ids.append(f"{match['book']}:{match['number']}")
        else:
            ids += labels.normalise_articles(text) or labels.normalise_articles(f"Article {text}") or [text]
    return list(dict.fromkeys(ids))


def article_number(article_id: str) -> str:
    """'ISC-L:IV.2.d' -> 'ISC-L:IV.2'; 'F1-B:1.6.2.b.i' -> 'F1-B:1.6.2'; 'F1-B:8.2.2a' -> 'F1-B:8.2.2'."""
    book, _, number = article_id.partition(":")
    parts = number.split(".")
    while len(parts) > 1 and re.fullmatch(r"[a-z]+", parts[-1]):
        parts.pop()
    parts[-1] = re.sub(r"(?<=\d)[a-z]+$", "", parts[-1])
    return f"{book}:{'.'.join(parts)}"


def same_penalty(a: dict, b: dict) -> bool:
    return (a["type"], a["value"], a["unit"]) == (b["type"], b["value"], b["unit"])


def score(articles: list[str], penalty: dict | None, gold: Gold) -> Marks:
    """Marks for one answer. `penalty` is {type, value, unit}, or None for no answer at all.

    An answer that cites no article has citation precision 0, not "undefined": it gave
    the stewards nothing to check.
    """
    gold_numbers = {article_number(a) for a in gold.articles}
    numbers = [article_number(a) for a in as_ids(articles)]
    right = [n in gold_numbers for n in numbers]
    penalty_type = penalty is not None and any(penalty["type"] == g["type"] for g in gold.penalties)
    exact = penalty is not None and any(same_penalty(penalty, g) for g in gold.penalties)
    return Marks(
        article_hit=any(right),
        citation_precision=sum(right) / len(right) if right else 0.0,
        penalty_type=penalty_type,
        penalty=exact,
    )


def mean(marks: list[Marks]) -> dict[str, float | None]:
    """The average of each metric over these answers; None for no answers."""
    if not marks:
        return {metric: None for metric in METRICS}
    return {metric: sum(m.as_dict()[metric] for m in marks) / len(marks) for metric in METRICS}


def paired_bootstrap(
    a: list[float], b: list[float], rounds: int = 10_000, seed: int = 20261124
) -> dict[str, float]:
    """The difference mean(a) - mean(b) on the same questions, with a 95% bootstrap interval.

    Paired: question i of `a` and question i of `b` are the same question, answered two
    ways. Each round draws len(a) questions with replacement and takes the difference of
    the two means over the drawn questions; the interval is the middle 95% of the rounds.
    Pairing removes the part of the spread that comes from some questions being harder
    than others, which both configurations share.
    """
    if len(a) != len(b):
        raise ValueError("Paired samples must be the same length.")
    n = len(a)
    if n == 0:  # nothing to compare: say so, rather than report a difference of zero
        return {"difference": None, "low": None, "high": None, "questions": 0}
    differences = [x - y for x, y in zip(a, b)]
    pick = random.Random(seed)
    means = sorted(sum(differences[pick.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
    return {
        "difference": sum(differences) / n,
        "low": means[int(0.025 * rounds)],
        "high": means[int(0.975 * rounds) - 1],
        "questions": n,
    }
