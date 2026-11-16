"""Turn one stewards' decision PDF into its fields.

A decision is a form. Each field starts on its own line with the field's name:

    No / Driver   16 - Charles Leclerc
    Competitor    Scuderia Ferrari HP
    Time          15:36
    Session       Race
    Fact          Car 16 made contact with Car 30 in turn 12.
    Infringement  Breach of ...
    Decision      5 second time penalty.
    Reason        The Stewards heard from ...

A PDF stores no "fields", only characters and where they sit on the page. So the work is:
get the characters out as plain text (`extract_text`), find where each field name starts,
and take the text between one name and the next (`parse`).

Three layouts exist in the 2026 documents:

    single_car  the form above: one car, one decision
    car_table   a cover page plus an attached decision about several cars, listed in a table
    no_fields   not a decision about an incident (a permission, a technical report)

A car_table document can also be a list of deleted lap times. Like the no_fields ones it
is named in `other_document` and left out.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# The field names, in the order they appear on the page.
# "Reasons" is how the car_table layout spells "Reason".
_FIELDS = [
    ("driver", "No / Driver"),
    ("competitor", "Competitor"),
    ("time", "Time"),
    ("session", "Session"),
    ("fact", "Fact"),
    ("infringement", "Infringement"),
    ("decision", "Decision"),
    ("reason", "Reasons?"),
]

# A decision we can use must have these. The others are allowed to be missing:
# a driver who was late for a press conference has no Session.
REQUIRED = ("fact", "infringement", "decision")

# Every decision ends with the same two paragraphs. They are not part of the Reason.
_CLOSING = re.compile(
    r"^(?:Note[ \t]+)?Competitors\s+are\s+reminded|^Decisions\s+of\s+the\s+Stewards\s+are\s+taken",
    re.MULTILINE,
)

# The header of the table in the car_table layout: "No. Car Driver Competitor Time of Day ...".
_TABLE_HEADER = re.compile(r"^No\.?\s+Car\s+Driver\b.*$", re.MULTILINE)
# A row of that table: a row number, then the car number.
_TABLE_ROW = re.compile(r"^\s*\d+\s+(\d+)\s+\S", re.MULTILINE)

# A list of deleted lap times looks like a car_table decision, and is sometimes published
# under an ordinary title. Its Decision field gives it away.
_LAP_DELETION = re.compile(r"^\s*Deletion\s+of\s+(?:the\s+)?lap\s+times?", re.IGNORECASE)

# Under the signatures the page says "The Stewards". pypdf returns that label as the first
# line of every later page, so when a Reason runs on to page 2 the label lands in the
# middle of it. A line that is only those two words is never part of a sentence.
_SIGNATURE_LABEL = re.compile(r"^The\s+Stewards[ \t]*\n", re.MULTILINE)

_DRIVER = re.compile(r"^(\d+)\s*[-–]\s*(.+)$")
_DOCUMENT_NUMBER = re.compile(r"^Document[ \t]+(\d+)", re.MULTILINE)


@dataclass
class Decision:
    layout: str  # "single_car", "car_table" or "no_fields"
    document: int | None = None  # the number printed on the page
    cars: list[int] = field(default_factory=list)
    driver: str | None = None
    competitor: str | None = None
    time: str | None = None  # time of the incident, not of the document
    session: str | None = None
    fact: str | None = None
    infringement: str | None = None
    decision: str | None = None
    reason: str | None = None
    other_document: str | None = None  # set when this is not a decision about an incident
    notes: list[str] = field(default_factory=list)  # oddities we worked around

    @property
    def missing(self) -> list[str]:
        """Required fields that were not found. Empty means the parse succeeded."""
        if self.other_document:
            return []
        return [name for name in REQUIRED if not getattr(self, name)]


def extract_text(pdf_path: Path) -> str:
    """All the text of a PDF, page after page.

    pypdf reads the drawing instructions of each page and returns the characters in
    reading order. Line breaks are where the page breaks its lines, not where a
    paragraph ends.
    """
    from pypdf import PdfReader  # imported here so that tests of `parse` do not need pypdf

    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _label(printed_name: str) -> re.Pattern:
    """A pattern that finds a field name at the start of a line.

    Two details come from the real documents:

    - Inside a value the words are joined by non-breaking spaces (the character U+00A0),
      but a field name is followed by an ordinary space. `[ \\t]` matches only the
      ordinary kind, so a wrapped line of the Fact that happens to start with
      "Infringement was ..." is not mistaken for the Infringement field.
    - The spaces inside "No / Driver" can be of either kind, so `\\s*` is used there
      (`\\s` matches both).
    """
    flexible = r"\s*".join(printed_name.split())
    return re.compile(rf"^{flexible}[ \t]+", re.MULTILINE)


_LABELS = [(name, _label(printed)) for name, printed in _FIELDS]


def _tidy(text: str) -> str:
    """One line, single ordinary spaces. `str.split()` splits on every kind of whitespace."""
    return " ".join(text.split())


def parse(text: str) -> Decision:
    """Cut the text of one document into fields. Never raises: look at `.missing`."""
    number = _DOCUMENT_NUMBER.search(text)
    document = int(number.group(1)) if number else None

    # 1. Find where each field name starts. Search for them in page order, each one
    #    starting after the previous one. The header also has a "Time" line (when the
    #    document was issued); starting from "No / Driver" skips it.
    found: list[tuple[str, re.Match]] = []
    position = 0
    for name, pattern in _LABELS:
        match = pattern.search(text, position)
        if match is None:
            continue
        if name == "time" and not found:
            continue  # no "No / Driver" before it, so this is the header's Time
        found.append((name, match))
        position = match.end()

    names = [name for name, _ in found]
    if "fact" not in names and "decision" not in names:
        return Decision(layout="no_fields", document=document, other_document=_what_else(text))

    # 2. The fields stop where the closing paragraphs begin.
    closing = _CLOSING.search(text, found[0][1].start())
    end_of_fields = closing.start() if closing else len(text)

    # 3. A field's value runs from the end of its name to the start of the next name.
    raw: dict[str, str] = {}
    for index, (name, match) in enumerate(found):
        next_start = found[index + 1][1].start() if index + 1 < len(found) else end_of_fields
        value = text[match.end() : min(next_start, end_of_fields)]
        raw[name] = _SIGNATURE_LABEL.sub("", value)

    result = Decision(layout="single_car" if "driver" in raw else "car_table", document=document)
    if "driver" not in raw and _LAP_DELETION.match(raw.get("decision", "")):
        result.other_document = "lap_deletion_list"
        return result

    # 4. Layout-specific pieces.
    if "driver" in raw:
        driver = _DRIVER.match(_tidy(raw["driver"]))
        if driver:
            result.cars = [int(driver.group(1))]
            result.driver = driver.group(2)
        else:
            result.driver = _tidy(raw["driver"])
            result.notes.append("driver field is not 'number - name'")
    elif "fact" in raw:
        # The Fact is one sentence followed by a table of cars. Keep the sentence as the
        # fact and the car numbers as the cars.
        header = _TABLE_HEADER.search(raw["fact"])
        if header:
            result.cars = [int(n) for n in _TABLE_ROW.findall(raw["fact"], header.end())]
            raw["fact"] = raw["fact"][: header.start()]
        else:
            result.notes.append("no driver field and no table of cars")

    # 5. Some documents leave out the word "Reason": the reason simply follows the decision.
    #    The decision is then the first sentence, up to a line that ends with a full stop.
    if "reason" not in raw and "decision" in raw:
        decision, reason = _split_decision(raw["decision"])
        if reason:
            raw["decision"], raw["reason"] = decision, reason
            result.notes.append("no Reason label: split the Decision field after its first sentence")

    for name in ("competitor", "time", "session", "fact", "infringement", "decision", "reason"):
        value = _tidy(raw.get(name, ""))
        setattr(result, name, value or None)
    return result


def _split_decision(raw_decision: str) -> tuple[str, str]:
    lines = raw_decision.strip().splitlines()
    for index, line in enumerate(lines[:-1]):
        # "(5 seconds added to elapsed Race time)." on the next line still belongs to the decision.
        if line.rstrip().endswith(".") and not lines[index + 1].lstrip().startswith("("):
            return "\n".join(lines[: index + 1]), "\n".join(lines[index + 1 :])
    return raw_decision, ""


def _what_else(text: str) -> str:
    """Name the kinds of field-less document we have seen. Anything else is 'unknown'."""
    flat = _tidy(text)
    if "Technical Delegate’s Report" in flat or "Technical Delegate's Report" in flat:
        return "technical_report"
    # A team asked for something (to start despite no qualifying time, to change a driver)
    # and the stewards answered. No incident, no penalty.
    if re.search(r"Stewards have received a request from|eligible to start", flat):
        return "permission"
    # The stewards used a power of their own to run the event, such as stopping a session
    # while a barrier was repaired. Nobody is accused of anything.
    if "exercising their authority" in flat:
        return "event_ruling"
    return "unknown"
