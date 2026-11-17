"""Rule documents become articles: the right ids, heading paths and text, and nothing else.

The lines are written for these tests. They copy the shapes found in the real documents
(numbering, contents pages, page footers, headings that wrap), not their words.
"""

from f1aisteward.parse import rules


def split(book, lines, issue="T-01"):
    return rules.split_articles(lines, rules.LAYOUTS[book], book, issue)


def by_id(articles):
    return {article["id"]: article for article in articles}


# ---------------------------------------------------------------- columns


def word(x0, x1):
    return {"x0": x0, "x1": x1}


def test_the_gap_between_two_columns_is_found():
    words = [word(40, 120), word(130, 280), word(320, 400), word(410, 550)]
    gap = rules.column_gap(words, width=600)
    assert 280 < gap < 320


def test_a_page_with_a_line_across_the_middle_has_no_gap():
    words = [word(40, 120), word(130, 470), word(480, 550)]
    assert rules.column_gap(words, width=600) is None


# ---------------------------------------------------------------- Section B

SECTION_B = [
    "CONTENTS:",
    "ARTICLE B1: GENERAL MATTERS 4",  # contents lines end with a page number
    "B1.1 Wheels 4",
    "APPENDIX B1: DEFINITIONS 30",
    "ARTICLE B1: GENERAL MATTERS",
    "B1.1 Wheels",
    "B1.1.1 Every car must have four wheels, as set out in",
    "B3.2.1 and the other rules.",  # a sentence wrapped at a cross-reference
    "B1.1.2 A wheel that comes off must be reported.",
    "a. To the stewards, and",
    "b. To the team.",
    "B1.2 Safety Cars",
    "The safety car is used when the track is blocked.",  # a heading with text of its own
    "B1.2.1 Cars may not overtake the safety car.",
    "B1.2.1 Cars must keep their place.",  # the FIA numbered two paragraphs alike
    "APPENDIX B1: DEFINITIONS",
    "B9.9.9 A paragraph after the end of the main text.",
]


def test_section_b_articles_are_cut_at_their_numbers():
    articles = split("F1-B", SECTION_B)
    assert [a["id"] for a in articles] == ["F1-B:1.1.1", "F1-B:1.1.2", "F1-B:1.2", "F1-B:1.2.1", "F1-B:1.2.1"]


def test_a_wrapped_cross_reference_stays_in_its_paragraph():
    article = by_id(split("F1-B", SECTION_B))["F1-B:1.1.1"]
    assert article["text"] == "B1.1.1 Every car must have four wheels, as set out in\nB3.2.1 and the other rules."


def test_lettered_points_stay_inside_their_article():
    assert by_id(split("F1-B", SECTION_B))["F1-B:1.1.2"]["text"].endswith("a. To the stewards, and\nb. To the team.")


def test_the_heading_path_is_kept_and_contents_lines_are_not_headings():
    article = by_id(split("F1-B", SECTION_B))["F1-B:1.1.1"]
    assert article["headings"] == ["ARTICLE B1: GENERAL MATTERS", "B1.1 Wheels"]
    assert rules.chunk_text(article).startswith("ARTICLE B1: GENERAL MATTERS > B1.1 Wheels > F1-B:1.1.1\n")


def test_a_heading_with_text_of_its_own_is_an_article_and_one_without_is_not():
    found = by_id(split("F1-B", SECTION_B))
    assert found["F1-B:1.2"]["text"] == "The safety car is used when the track is blocked."
    assert "F1-B:1.1" not in found


def test_a_number_used_twice_gives_two_articles_with_different_keys():
    twice = [a for a in split("F1-B", SECTION_B) if a["id"] == "F1-B:1.2.1"]
    assert [a["key"] for a in twice] == ["T-01/F1-B:1.2.1", "T-01/F1-B:1.2.1#2"]


def test_nothing_after_the_end_of_the_main_text_is_read():
    assert "F1-B:9.9.9" not in by_id(split("F1-B", SECTION_B))


def test_page_furniture_of_section_b_is_recognised():
    furniture = rules.LAYOUTS["F1-B"].furniture
    for line in ["B", "0", "B30", "B3 0", "SECTION B: SPORTING REGULATIONS", "Governance: F1 Commission / WMSC"]:
        assert furniture.fullmatch(line), line
    assert not furniture.fullmatch("B1.2.1 Cars may not overtake the safety car.")


# ---------------------------------------------------------------- the Code and its appendices


def test_appendix_l_numbers_its_articles_again_in_each_chapter():
    lines = [
        "MODIFICATIONS FOR 2099",  # in the contents: the main text has not started yet
        "CHAPTER III - EQUIPMENT",
        "1. Gloves",
        "Gloves must be worn.",
        "CHAPTER IV - CODE OF CONDUCT ON",
        "TRACKS",  # the chapter title wrapped
        "1. Signals",
        "Drivers must obey the signals.",
        "2. Overtaking and track limits",
        "a) A car alone may use the whole track.",
        "d) Hitting another car will be reported.",
        "1.1 Signals at night",
        "Lights replace flags at night.",
        "MODIFICATIONS FOR 2099",
        "1. Gloves",
        "Gloves will be orange.",
    ]
    found = by_id(split("ISC-L", lines))

    assert list(found) == ["ISC-L:III.1", "ISC-L:IV.1", "ISC-L:IV.2", "ISC-L:IV.1.1"]
    assert found["ISC-L:IV.2"]["headings"] == ["CHAPTER IV - CODE OF CONDUCT ON TRACKS", "2. Overtaking and track limits"]
    assert found["ISC-L:IV.2"]["text"].endswith("d) Hitting another car will be reported.")
    assert found["ISC-L:III.1"]["text"] == "Gloves must be worn."  # not next year's text


def test_appendix_h_headings_with_a_full_stop_and_titles_that_do_not_swallow_the_next_heading():
    lines = [
        "ARTICLE 2 – TRACK RACING",
        "2.1 CONTROL ROOM",
        "The control room overlooks the track.",
        "2.4. FLAG POSTS",
        "2.4.1 Flag posts stand every 500 metres.",
        "SUPPLEMENT 1",
        "2.4.2 Not part of the appendix itself.",
    ]
    found = by_id(split("ISC-H", lines))

    assert list(found) == ["ISC-H:2.1", "ISC-H:2.4.1"]
    assert found["ISC-H:2.1"]["headings"] == ["ARTICLE 2 – TRACK RACING", "2.1 CONTROL ROOM"]
    assert found["ISC-H:2.4.1"]["headings"] == ["ARTICLE 2 – TRACK RACING", "2.4. FLAG POSTS"]


def test_the_code_has_headings_without_titles_and_two_level_paragraphs():
    lines = [
        "ARTICLE 9 REVIEWS",
        "ARTICLE 9.1",  # printed with no title
        "Any review must be in writing.",
        "9.2 A review does not stop a penalty.",
        "9.3.1.c Failure to follow the officials.",
        "One mile is",
        "1.609344 Kilometres.",  # a number in the text, not a paragraph
    ]
    found = by_id(split("ISC", lines))

    assert list(found) == ["ISC:9.1", "ISC:9.2", "ISC:9.3.1.c"]
    assert found["ISC:9.1"]["headings"] == ["ARTICLE 9 REVIEWS", "ARTICLE 9.1"]
    assert found["ISC:9.3.1.c"]["text"].endswith("1.609344 Kilometres.")
