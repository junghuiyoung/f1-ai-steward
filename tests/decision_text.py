"""Made-up decision text, laid out the way pypdf returns a real decision.

No FIA text is used in tests. Only the structure is copied: field names at the start of
a line followed by an ordinary space, and non-breaking spaces between the words of a value.
"""

NBSP = " "

HEADER = [
    "2031 EXAMPLE GRAND PRIX",
    "From The Stewards",
    "To The Team Manager,",
    "Northwind Racing",
    "Document 12",
    "Date 01 June 2031",
    "Time 17:05",
    "The Stewards have looked at the following matter:",
]

CLOSING = [
    "Competitors are reminded that they can appeal.",
    "Decisions of the Stewards are taken on the evidence.",
    "Sam Sample Robin Placeholder",
]

SINGLE_CAR_FIELDS = [
    ("No / Driver", "7 - Ada Example"),
    ("Competitor", "Northwind Racing"),
    ("Time", "15:36"),
    ("Session", "Race"),
    ("Fact", "Car 7 pushed Car 8 wide at turn 3."),
    ("Infringement", "Breach of Article B1.2.3 of the Example Regulations."),
    ("Decision", "5 second time penalty."),
    ("Reason", ["The Stewards watched the video and found that", "Car 7 left no room for Car 8."]),
]


def _glue(text: str) -> str:
    return text.replace(" ", NBSP)


def lines(*texts: str) -> str:
    """Lines of running text, as they come out of a real PDF."""
    return "\n".join(_glue(text) for text in texts)


def form(fields: list[tuple[str, str | list[str]]], header: bool = True, closing: bool = True) -> str:
    """A whole document. A field's value may be a list: one item per printed line."""
    out = [_glue(text) for text in HEADER] if header else []
    # The header's "Document 12", "Date ..." and "Time 17:05" are name, ordinary space, value.
    out = [text.replace(NBSP, " ", 1) if text.split(NBSP)[0] in ("Document", "Date", "Time") else text for text in out]
    for name, value in fields:
        first, *rest = [value] if isinstance(value, str) else value
        out.append(f"{_glue(name)} {_glue(first)}")
        out += [_glue(text) for text in rest]
    if closing:
        out += [_glue(text) for text in CLOSING]
    return "\n".join(out) + "\n"


def without(fields: list[tuple], *names: str) -> list[tuple]:
    return [item for item in fields if item[0] not in names]


def replaced(fields: list[tuple], name: str, value: str | list[str]) -> list[tuple]:
    return [(n, value if n == name else v) for n, v in fields]
