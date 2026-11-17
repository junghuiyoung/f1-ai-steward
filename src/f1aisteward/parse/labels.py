"""Turn the free text of a decision's fields into labels a program can compare.

The stewards type every document by hand, so the same thing is written many ways:

    "Appendix L, Chapter IV, Article 2 d)"   "Chapter IV Art 2(d)"   "Article 2d"

To count decisions per article, or to check an answer against the stewards' decision,
all of these must become the same string. That string is the article id:

    ISC-L:IV.2.d     International Sporting Code, Appendix L, Chapter IV, Article 2 d)
    ISC-H:2.5.5.b    International Sporting Code, Appendix H, Article 2.5.5 b)
    ISC:12.2.1.i     International Sporting Code, Article 12.2.1.i
    F1-B:8.2.2.a     FIA F1 Regulations, Section B, Article 8.2.2a

Nothing here needs the PDFs. Every function takes a string and returns plain data.
"""

import re

from .. import config

# ---------------------------------------------------------------- articles

# A sub-clause after an article number: "a", ".a", "(a)", " a)", ".iv". Zero or more of them.
_SUB = r"(?:\.?(?:[ivx]+|[a-z])(?![a-zA-Z])|\s*\((?:[ivx]+|[a-z])\)|\s+(?:[ivx]+|[a-z])\))*"

# One pattern that matches every piece of an Infringement field we care about.
# `finditer` walks the text left to right and hands back one piece at a time; the name of
# the group that matched (`match.lastgroup`) says which kind of piece it is.
_PIECE = re.compile(
    rf"""
      (?P<of_appendix> \bof\s+Appendix\s+(?P<of_appendix_letter>[A-Z])\b )    # "of Appendix H"
    | (?P<appendix> \bAppendix\s+(?P<appendix_letter>[A-Z])\b )
    | (?P<chapter>  \bChapter\s+(?P<chapter_number>[IVX]+)\b )
    | (?P<note>     \b(?i:items?|documents?)\s+[\d.]+ )                    # "item 5.7", "document 34"
    | (?P<keyword>  \bArt(?:icles?|\.)?(?![a-z]) )                         # "Article", "Articles", "Art"
    | (?P<of_f1>    \bof\s+the\s+(?:FIA\s+)?(?:F1|Formula\s+(?:One|1))\b ) # "of the FIA F1 Regulations"
    | (?P<of_the>   \bof\s+the\b )
    | (?P<f1>       \b(?P<section>[A-F])\s?(?P<f1_number>\d+(?:\.\d+)+)(?P<f1_sub>{_SUB}) )  # "B8.2.2a", "B 1.8.4b"
    | (?P<bare>     (?<![\w.])(?P<bare_number>\d+(?:\.\d+)*)(?P<bare_sub>{_SUB}) )         # "2 d)", "12.2.1.i"
    """,
    re.VERBOSE,
)


def _with_sub(number: str, sub: str) -> str:
    """'8.2.2' and ' a) i)' -> '8.2.2.a.i'."""
    return ".".join([number] + re.findall(r"[a-z]+", sub))


def normalise_articles(infringement: str) -> list[str]:
    """Every article cited in an Infringement field, as ids, in the order they appear.

    An F1 Regulations article names itself: it starts with its section letter ("B1.8.6").
    A bare number ("2 d)", "12.2.1.i") only means something next to the words around it,
    so the loop remembers what it has read:

    - `appendix` and `chapter`: the last "Appendix L" and "Chapter IV" seen. They apply to
      the bare numbers that follow, until "of the ..." closes the citation.
    - `armed`: True after the word "Article". Only then is a bare number an article.
      "item 5.7" and "document 34" (a Race Director's note) are never articles.
    - `waiting`: bare numbers read outside an appendix. The book is often named after the
      number ("Article 1.8.5 of the FIA F1 Regulations", "Article 2.5.5 b) of Appendix H"),
      so they wait for the next "of ...". Anything else, or nothing, means the body of the Code.

    "of the FIA F1 Regulations" without a section letter is taken as Section B, the
    Sporting Regulations. That is a guess: in the 2026 decisions every article of another
    section was written with its letter ("C9.3").
    """
    ids: list[list[str]] = []  # [book prefix, number]; the prefix is "" while it waits
    waiting: list[list[str]] = []
    appendix = chapter = None
    cited_under_appendix = False
    armed = False

    def settle(prefix: str) -> None:
        for entry in waiting:
            entry[0] = prefix
        waiting.clear()

    for match in _PIECE.finditer(infringement):
        piece = match.lastgroup
        if piece == "of_appendix" and waiting:
            settle(f"ISC-{match['of_appendix_letter']}:")
        elif piece in ("appendix", "of_appendix"):  # "Breach of Appendix H, Article 2.5.5" opens one
            appendix = match["appendix_letter"] or match["of_appendix_letter"]
            chapter, cited_under_appendix = None, False
        elif piece == "chapter":
            chapter = match["chapter_number"]
        elif piece == "keyword":
            armed = True
        elif piece == "note":
            armed = False
        elif piece in ("of_the", "of_f1"):
            settle("F1-B:" if piece == "of_f1" else "ISC:")
            armed = False
            if cited_under_appendix:
                appendix = chapter = None
        elif piece == "f1":
            ids.append([f"F1-{match['section']}:", _with_sub(match["f1_number"], match["f1_sub"])])
        elif piece == "bare" and armed:
            number = _with_sub(match["bare_number"], match["bare_sub"])
            if appendix:
                ids.append([f"ISC-{appendix}:" + (f"{chapter}." if chapter else ""), number])
                cited_under_appendix = True
            else:
                ids.append(["", number])
                waiting.append(ids[-1])
    settle("ISC:")

    return list(dict.fromkeys(prefix + number for prefix, number in ids))  # drop repeats, keep the order


# ---------------------------------------------------------------- penalty

PENALTY_TYPES = (
    "disqualification",
    "stop_go",
    "drive_through",
    "time_penalty",
    "grid_drop",
    "pit_lane_start",
    "fine",
    "reprimand",
    "warning",
    "no_further_action",
    "other",
)

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_COUNT = r"(\d+|" + "|".join(_NUMBER_WORDS) + ")"

# Checked from top to bottom; the first pattern found in the Decision field wins.
# The order is from the heaviest penalty to the lightest, so "5 second time penalty.
# No further action on the second matter." is a time penalty.
_PENALTY_RULES: list[tuple[str, re.Pattern, str | None]] = [
    ("disqualification", re.compile(r"disqualif", re.I), None),
    ("stop_go", re.compile(r"(?:(\d+)\s*seconds?\s+)?stop[\s-]*(?:and|&)?[\s-]*go", re.I), "s"),
    ("drive_through", re.compile(r"drive[\s-]*through", re.I), None),
    ("time_penalty", re.compile(r"(\d+)\s*seconds?\s+time\s+penalty", re.I), "s"),
    ("grid_drop", re.compile(rf"drop\s+of\s+{_COUNT}\s+grid\s+(?:positions?|places?)", re.I), "places"),
    ("pit_lane_start", re.compile(r"start\b.*\bfrom\s+(?:the\s+)?pit\s*lane", re.I), None),
    # "€5,000", "€5.000" and "€1000" are all written. When part of a fine is suspended,
    # the first amount is the whole fine.
    ("fine", re.compile(r"\bfined?\b[^€]*€\s*(\d{1,3}(?:[.,]\d{3})+|\d+)", re.I), "EUR"),
    ("reprimand", re.compile(r"reprimand", re.I), None),
    ("warning", re.compile(r"warning", re.I), None),
    ("no_further_action", re.compile(r"no\s+further\s+action|no\s+penalty", re.I), None),
]


def parse_penalty(decision: str) -> dict:
    """'5 second time penalty. 2 penalty points' -> {'type': 'time_penalty', 'value': 5, 'unit': 's'}.

    Penalty points are left out: they follow from the penalty and are not what we predict.
    A text that fits no rule is 'other', so nothing is lost silently and it can be counted.
    """
    for penalty_type, pattern, unit in _PENALTY_RULES:
        match = pattern.search(decision)
        if match is None:
            continue
        amount = match.group(1) if pattern.groups else None
        if amount is None:
            return {"type": penalty_type, "value": None, "unit": None}
        amount = amount.lower()
        value = _NUMBER_WORDS.get(amount) or int(re.sub(r"[.,]", "", amount))
        return {"type": penalty_type, "value": value, "unit": unit}
    return {"type": "other", "value": None, "unit": None}


# ---------------------------------------------------------------- kind

KINDS = ("component_allowance", "pit_lane_speeding", "judgment_incident", "procedural_or_technical")

# Articles under which the stewards judge how a car was driven: collisions, forcing a car
# off the track, impeding, driving slowly, yellow flags. Read off the Facts of the 2026
# decisions; extend it when a new driving article shows up.
_JUDGMENT_PREFIXES = (
    "ISC-L:IV.",  # Appendix L, Chapter IV: the code of driving conduct on circuits
    "ISC-H:2.5.5",  # Appendix H: yellow flags
    "F1-B:1.8.4",  # yellow flags
    "F1-B:1.8.5",  # driving unnecessarily slowly
    "F1-B:1.8.6",  # leaving the track
    "F1-B:4.1.1",  # impeding
)
_COMPONENT_PREFIX = "F1-B:8.2."  # use of more Power Unit elements than allowed
_PIT_LANE_SPEEDING = re.compile(r"pit\s*lane\s+speeding", re.I)


def classify_kind(fact: str, articles: list[str]) -> str:
    """Which of the four kinds of decision this is.

    The first two are fixed by the rules (a table gives the penalty), the third is a
    judgment, and the rest is procedure and technical compliance. Scores are reported
    per kind, because the fixed ones are easy and would hide how the judgment ones do.
    """
    if any(article.startswith(_COMPONENT_PREFIX) for article in articles):
        return "component_allowance"
    if _PIT_LANE_SPEEDING.search(fact):
        return "pit_lane_speeding"
    if any(article.startswith(_JUDGMENT_PREFIXES) for article in articles):
        return "judgment_incident"
    return "procedural_or_technical"


# ---------------------------------------------------------------- split


def split_for(event_date: str, dev_from: str = config.DEV_FROM, test_from: str = config.TEST_FROM) -> str | None:
    """Whether an event's decisions are asked as dev questions, test questions or not at all."""
    if event_date < dev_from:
        return None
    return "dev" if event_date < test_from else "test"
