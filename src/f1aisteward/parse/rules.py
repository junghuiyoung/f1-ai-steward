"""Turn the rule documents into articles: one chunk per article, with its heading path.

    PDF page ──pdfplumber──▶ lines of English ──▶ blocks ──────────────▶ articles
             the ISC and its     page headers and    a block starts at     id, issue, heading
             appendices print    footers dropped     a heading or at a     path, text
             French on the left                      numbered clause
             and English on the
             right: keep the right

Each book numbers its text its own way, so each has a Layout: patterns for its headings
and numbered clauses, its page headers and footers, and the line where its main text
ends. Article ids follow the labels (parse/labels.py), so search results can be compared
with what the stewards cited:

    F1-B:1.8.5      Section B of the FIA F1 Regulations, Article B1.8.5
    ISC:12.2.1.i    International Sporting Code, Article 12.2.1.i
    ISC-L:IV.2      Appendix L, Chapter IV, Article 2 (its points a) to e) are inside it)
    ISC-H:2.5.5     Appendix H, Article 2.5.5

pdfplumber is used here and not pypdf (which reads the decisions): pypdf reads the two
languages of a page in an order that changes from page to page, and pdfplumber can crop
a page to one column. Nothing here calls the network.
"""

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from .. import config, fetch


@dataclass(frozen=True)
class Layout:
    two_columns: bool  # French left, English right
    furniture: re.Pattern  # a whole line that is a page header, footer or page number
    headings: tuple[re.Pattern, ...]  # a line that is a title; the text under it follows
    clause: re.Pattern  # a line that starts a numbered paragraph; it is text itself
    end: re.Pattern  # the main text ends here; what follows is not in force yet, or not rules
    chapter: re.Pattern | None = None  # Appendix L numbers its articles again in each chapter


def _lines(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


# A clause starts with its number and a capital letter (or a bracket or quote). A line that
# starts with a number and a small letter is a sentence that wrapped at a cross-reference:
# "B5.15.2 shall remain unchanged ...".
_STARTS_TEXT = r"\s+[A-Z(“\"\[]"

LAYOUTS = {
    "F1-B": Layout(
        two_columns=False,
        furniture=_lines(
            r"B|0|SECTION B: SPORTING REGULATIONS",
            r"©\d{4} Fédération Internationale de l’Automobile Issue \d+",
            r"\d{4} Form ?ula 1: Sporting Regulations.*",
            r"B\d+ ?\d*",  # the page number, e.g. "B30", sometimes read as "B3 0"
            r"Advisory Committee:.*|Governance:.*",  # who may change the article, not what it says
        ),
        # The contents pages list the same headings followed by a page number. A heading
        # that ends in a number is therefore a contents line, and is not a heading.
        headings=(
            re.compile(r"ARTICLE B(?P<n>\d+): .*\D"),
            re.compile(r"B(?P<n>\d+\.\d+) [A-Z].*\D"),
        ),
        clause=re.compile(rf"B(?P<n>\d+(?:\.\d+){{2,}}){_STARTS_TEXT}.*"),
        end=re.compile(r"APPENDIX B\d+: .*\D"),  # definitions, forms, and changes for later years
    ),
    "ISC": Layout(
        two_columns=True,
        furniture=_lines(r"Application from .*", r"\d* ?/\d+ FIA International Sporting Code", r"\d+"),
        headings=(
            # "ARTICLE 12 INFRINGEMENTS, PENALTIES AND ...", "ARTICLE 12.2 BREACH OF RULES"; some have no title
            re.compile(r"ARTICLE (?P<n>\d+)(?:\s+[A-Z].*)?"),
            re.compile(r"ARTICLE (?P<n>\d+\.\d+)(?:\s+[A-Z].*)?"),
        ),
        # "12.2.1.i Failure to follow ...", and in Articles 13 and 14 "14.2 A review has no ...".
        # At most three digits a part, so "1.609344 Kilometres." in the definitions is text.
        clause=re.compile(rf"(?P<n>\d{{1,3}}(?:\.\d{{1,3}})+(?:\.[a-z]{{1,4}})?){_STARTS_TEXT}.*"),
        end=re.compile(r"MODIFICATIONS FOR \d{4}"),
    ),
    "ISC-L": Layout(
        two_columns=True,
        furniture=_lines(
            r"ANNEXE L|APPENDIX L|Page \d+ de \d+", r"ANNEXE L \d{4} / APPENDIX L \d{4}.*", r"Publié le .*|Published on .*"
        ),
        headings=(re.compile(r"(?P<n>\d+)\.\s+[A-Z].*"),),  # "2. Overtaking, car control and track limits"
        clause=re.compile(rf"(?P<n>\d+(?:\.\d+)+)\.?{_STARTS_TEXT}.*"),  # "1.6.1 Higher licence grades ..."
        end=re.compile(r"MODIFICATIONS FOR \d{4}"),
        chapter=re.compile(r"CHAPTER (?P<n>[IVX]+)\s*[-–].*"),
    ),
    "ISC-H": Layout(
        two_columns=True,
        furniture=_lines(
            r"ANNEXE H|APPENDIX H|\d+", r"ANNEXE H \d{4} / APPENDIX H \d{4}.*", r"Publié le .*|Published on .*"
        ),
        headings=(
            re.compile(r"ARTICLE (?P<n>\d+)\s*[-–].*"),
            re.compile(r"(?P<n>\d+\.\d+)\.?\s+[A-Z].*"),  # "2.5 SIGNALLING", "2.4. MARSHAL POSTS"
        ),
        clause=re.compile(rf"(?P<n>\d+(?:\.\d+){{2,}})\.?{_STARTS_TEXT}.*"),  # "2.5.5 Signals used at marshal posts"
        end=re.compile(r"MODIFICATIONS FOR \d{4}|SUPPLEMENT \d+"),
    ),
}


# ---------------------------------------------------------------- pages to lines


def column_gap(words: list[dict], width: float) -> float | None:
    """The x position of the empty band between two columns, or None if there is none.

    Every word covers a stretch of the page from its left edge to its right edge. In the
    middle of a two-column page there is a band no word covers. A page without one is
    not two-column text: a contents page, or a table across the whole page.
    """
    lo, hi = int(width * 0.35), int(width * 0.65)
    covered = [False] * (hi - lo + 1)
    for word in words:
        for x in range(max(lo, int(word["x0"])), min(hi, int(word["x1"])) + 1):
            covered[x - lo] = True
    best_width, best_middle, start = 0, None, None
    for offset, is_covered in enumerate(covered + [True]):
        if not is_covered and start is None:
            start = offset
        elif is_covered and start is not None:
            if offset - start > best_width:
                best_width, best_middle = offset - start, lo + (start + offset - 1) / 2
            start = None
    return best_middle


@dataclass
class Extracted:
    lines: list[str]
    pages: int
    skipped_pages: list[int] = field(default_factory=list)  # cover and contents
    cut_at_usual_gap: list[int] = field(default_factory=list)  # pages with a table across both columns


def extract_lines(pdf_path: Path, layout: Layout) -> Extracted:
    """The English text of a rule document, one list item per line, headers and footers dropped.

    In a two-column book, the pages before the first two-column page (the cover and the
    contents) are skipped. A later page without a gap has a table across the page; it is
    cut where the columns usually meet, so its two-column text is still read.
    """
    lines: list[str] = []
    result = Extracted(lines, 0)
    with pdfplumber.open(pdf_path) as pdf:
        result.pages = len(pdf.pages)
        gaps = [column_gap(p.extract_words(), float(p.width)) if layout.two_columns else None for p in pdf.pages]
        found = [gap for gap in gaps if gap is not None]
        usual = statistics.median(found) if found else None
        body_started = not layout.two_columns
        for number, (page, gap) in enumerate(zip(pdf.pages, gaps), start=1):
            region = page
            if layout.two_columns:
                if gap is None and not body_started:
                    result.skipped_pages.append(number)
                    continue
                body_started = True
                if gap is None:
                    result.cut_at_usual_gap.append(number)
                region = page.crop((gap if gap is not None else usual, 0, page.width, page.height))
            for line in (region.extract_text() or "").splitlines():
                line = line.strip()
                if line and not layout.furniture.fullmatch(line):
                    lines.append(line)
    return result


# ---------------------------------------------------------------- lines to articles


def _is_title_continuation(line: str) -> bool:
    """'ON CIRCUITS' after 'CHAPTER IV - CODE OF DRIVING CONDUCT': a heading that wrapped."""
    letters = [c for c in line if c.isalpha()]
    return len(letters) > 1 and all(c.isupper() for c in letters)


def split_articles(lines: list[str], layout: Layout, book: str, issue: str) -> list[dict]:
    """Cut the lines into articles.

    A heading ("B1.8 Driving") starts a block whose text is the lines under it; a clause
    ("B1.8.5 At no time may ...") starts a block whose text begins on its own line. Every
    heading also replaces the headings at its level and below in the heading path. Blocks
    with no text (a heading followed straight away by its first clause) are dropped.

    The FIA's own numbering sometimes repeats a number in one issue. Both paragraphs are
    kept, under the same article id; `key` tells them apart.
    """
    articles: list[dict] = []
    path: list[str] = []  # the headings above the current line, outermost first
    levels: list[int] = []  # the level of each entry in `path`
    chapter = ""
    current: dict | None = None
    after_heading = False

    def start(number: str, heading_path: list[str], text: list[str]) -> dict:
        article_id = f"{book}:{chapter + '.' if chapter else ''}{number}"
        block = {"id": article_id, "book": book, "issue": issue, "headings": heading_path, "text": text}
        articles.append(block)
        return block

    def push_heading(level: int, line: str) -> None:
        while levels and levels[-1] >= level:
            levels.pop()
            path.pop()
        levels.append(level)
        path.append(line)

    for line in lines:
        if articles and layout.end.fullmatch(line):
            break

        if layout.chapter and (match := layout.chapter.fullmatch(line)):
            chapter = match["n"]
            push_heading(0, line)
            current, after_heading = None, True
            continue
        for level, pattern in enumerate(layout.headings, start=1):
            if match := pattern.fullmatch(line):
                push_heading(level, line)
                current, after_heading = start(match["n"], list(path), []), True
                break
        else:
            if match := layout.clause.fullmatch(line):
                current, after_heading = start(match["n"], list(path), [line]), False
            elif after_heading and _is_title_continuation(line):
                path[-1] += " " + line
                if current is not None:
                    current["headings"] = list(path)
            elif current is not None:
                current["text"].append(line)
                after_heading = False

    kept = []
    seen: dict[str, int] = {}
    for article in articles:
        if not article["text"]:
            continue
        seen[article["id"]] = seen.get(article["id"], 0) + 1
        repeat = seen[article["id"]]
        kept.append(
            {
                "key": f"{issue}/{article['id']}" + (f"#{repeat}" if repeat > 1 else ""),
                "id": article["id"],
                "book": book,
                "issue": issue,
                "headings": article["headings"],
                "text": "\n".join(article["text"]),
            }
        )
    return kept


def parse_issue(pdf_path: Path, issue: dict) -> tuple[list[dict], Extracted]:
    """The articles of one issue of a rule document, and what the extraction skipped."""
    layout = LAYOUTS[issue["book"]]
    extracted = extract_lines(pdf_path, layout)
    articles = split_articles(extracted.lines, layout, issue["book"], issue["id"])
    return articles, extracted


def build_rules(regulations: dict, pdf_dir: Path = config.RULES_PDF_DIR) -> tuple[list[dict], list[str]]:
    """Every article of every issue in the regulations manifest, and one report line per issue."""
    articles: list[dict] = []
    report: list[str] = []
    for issue in regulations["issues"]:
        path = fetch.rule_pdf_path(issue["id"], pdf_dir)
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing. Run `f1aisteward fetch --rules` first.")
        found, extracted = parse_issue(path, issue)
        articles += found
        notes = []
        if extracted.skipped_pages:
            notes.append(f"skipped {_pages(extracted.skipped_pages)} (cover, contents)")
        if extracted.cut_at_usual_gap:
            notes.append(f"{_pages(extracted.cut_at_usual_gap)} cut where the columns usually meet")
        repeated = sorted({a["id"] for a in found if "#" in a["key"]})
        if repeated:
            notes.append(f"numbered twice by the FIA: {', '.join(repeated)}")
        report.append(f"{issue['id']:<14} {extracted.pages:>3} pages  {len(found):>4} articles  " + "; ".join(notes))
    return articles, report


def _pages(numbers: list[int]) -> str:
    return ("page " if len(numbers) == 1 else "pages ") + ", ".join(map(str, numbers))


def load(path: Path = config.PARSED_RULES) -> list[dict]:
    """The articles `build --rules` wrote."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def chunk_text(article: dict) -> str:
    """What is searched: the heading path, then the article itself."""
    return " > ".join(article["headings"] + [article["id"]]) + "\n" + article["text"]
