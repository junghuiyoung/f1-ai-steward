"""Labels: one id per article however it is written, a structured penalty, a kind.

Each table is a list of (text, expected). The texts are our own; they copy the ways of
writing a citation or a penalty that appear in real decisions, not the decisions.
"""

import pytest

from f1aisteward.parse import labels

ARTICLES = [
    # --- F1 Regulations: the section letter is part of the number
    ("Breach of Article B1.2.3 of the FIA F1 Regulations.", ["F1-B:1.2.3"]),
    ("Alleged breach of Article B4.5.6 of the FIA F1 Regulations.", ["F1-B:4.5.6"]),
    ("Breach of Article B3.3.1 of the FIA Formula One Sporting Regulations.", ["F1-B:3.3.1"]),
    ("Breach of Article C5.3.2 of the FIA F1 Regulations.", ["F1-C:5.3.2"]),
    ("Breach of Article C9.3 of the FIA F1 Regulations.", ["F1-C:9.3"]),
    ("Breach of Article B10.1.4 of the FIA F1 Regulations.", ["F1-B:10.1.4"]),
    ("Breach of Article B7.1.2.", ["F1-B:7.1.2"]),
    ("Breach of Article B1.2.3 of the FIA F1 Regu lations.", ["F1-B:1.2.3"]),  # a word broken by the PDF
    # --- sub-clauses, written six ways
    ("Article B8.2.2a", ["F1-B:8.2.2.a"]),
    ("Article B8.2.2.a", ["F1-B:8.2.2.a"]),
    ("Article B8.2.2(a)", ["F1-B:8.2.2.a"]),
    ("Article B8.2.2 (a)", ["F1-B:8.2.2.a"]),
    ("Article B8.2.2 a)", ["F1-B:8.2.2.a"]),
    ("Article B10.1.4e of the FIA F1 Regulations", ["F1-B:10.1.4.e"]),
    ("Article B1.6.2b.i", ["F1-B:1.6.2.b.i"]),
    ("Article B1.6.2 b) i)", ["F1-B:1.6.2.b.i"]),
    ("Article B5.5.5 a) i) of the FIA F1 Regulations.", ["F1-B:5.5.5.a.i"]),
    ("Article B2.5.4b.iv of the FIA F1 Regulations", ["F1-B:2.5.4.b.iv"]),
    # --- several articles in one field
    ("Article B8.2.2a (read with B8.2.3)", ["F1-B:8.2.2.a", "F1-B:8.2.3"]),
    ("Breaches of Article B8.2.2 (read with Article B8.2.3) of the FIA F1 Regulations.", ["F1-B:8.2.2", "F1-B:8.2.3"]),
    ("Breaches of Articles B3.4.2a and B3.5.7 of the FIA F1 Regulations.", ["F1-B:3.4.2.a", "F1-B:3.5.7"]),
    ("Breaches of Articles B3.4.3, B3.5.3 and B3.5.4.", ["F1-B:3.4.3", "F1-B:3.5.3", "F1-B:3.5.4"]),
    ("Alleged breach of Article B1.8.5 and/or B5.12.2.a", ["F1-B:1.8.5", "F1-B:5.12.2.a"]),
    ("Breach of Article B8.2.2 (read with B8.2.3) & B3.5.3", ["F1-B:8.2.2", "F1-B:8.2.3", "F1-B:3.5.3"]),
    ("Breach of Articles C5.12.6 and C5.12.7 of the FIA F1 Regulations.", ["F1-C:5.12.6", "F1-C:5.12.7"]),
    ("Breach of Article B1.2.3. See also Article B1.2.3.", ["F1-B:1.2.3"]),  # cited twice, listed once
    # --- International Sporting Code, body
    ("Breach of Article 12.2.1.i of the FIA International Sporting Code.", ["ISC:12.2.1.i"]),
    ("Breach of Article 12.2.1i of the International Sporting Code.", ["ISC:12.2.1.i"]),
    ("Breach of Article 12.2.1 i) of the International Sporting Code.", ["ISC:12.2.1.i"]),
    ("Breach of Article 12.2.1.l of the FIA International Sporting Code.", ["ISC:12.2.1.l"]),
    # --- ... with a Race Director's note, whose item and document numbers are not articles
    ("Breach of Article 12.2.1.i of the Code and non-compliance with the Event Note (item 5.7, document 34).", ["ISC:12.2.1.i"]),
    ("Breach of Article 12.2.1.i of the Code in combination with Item 14.1 of the Notes (Document 8).", ["ISC:12.2.1.i"]),
    ("Breach of Article 12.2.1i of the Code – Non-compliance with the Event Note (item 16.3, document 8).", ["ISC:12.2.1.i"]),
    # --- International Sporting Code, appendices
    ("Breach of Appendix L, Chapter IV, Article 2 d) of the FIA International Sporting Code.", ["ISC-L:IV.2.d"]),
    ("Breach of Appendix L, Chapter IV, Article 2d of the FIA International Sporting Code.", ["ISC-L:IV.2.d"]),
    ("Breach of Appendix L, Chapter IV, Article 2.d of the International Sporting Code.", ["ISC-L:IV.2.d"]),
    ("Alleged breach of Appendix L, Chapter IV Art 2(d) of the FIA International Sporting Code.", ["ISC-L:IV.2.d"]),
    ("Alleged breaches of Appendix L, Chapter IV, Articles 2 c) of the Code.", ["ISC-L:IV.2.c"]),
    ("Breach of Appendix L, Chapter IV Article 6 c) of the International Sporting Code.", ["ISC-L:IV.6.c"]),
    ("Breach of Appendix L, Chapter IV, Article 5b of the International Sporting Code.", ["ISC-L:IV.5.b"]),
    ("Breach of Appendix L, Chapter IV, Articles 2 b) and 2 d) of the Code.", ["ISC-L:IV.2.b", "ISC-L:IV.2.d"]),
    ("Alleged breach of Appendix H, Article 2.5.5 b) of the International Sporting Code.", ["ISC-H:2.5.5.b"]),
    # --- both rule books in one field, in either order
    (
        "Breaches of Article B1.8.6 of the FIA F1 Regulations and Appendix L, Chapter IV, Article 2 c) of the Code.",
        ["F1-B:1.8.6", "ISC-L:IV.2.c"],
    ),
    (
        "Breaches of Appendix L, Chapter IV, Article 2 c) of the Code and B1.8.6 of the FIA F1 Regulations.",
        ["ISC-L:IV.2.c", "F1-B:1.8.6"],
    ),
    (
        "Alleged breach of Article B1.8.5 of the FIA F1 Regulations and Article 12.2.1i of the Code (item 1, document 29).",
        ["F1-B:1.8.5", "ISC:12.2.1.i"],
    ),
    (  # "of the ..." closes the appendix: the second article is in the body of the Code
        "Breach of Appendix L, Chapter IV, Article 2 d) of the Code and Article 12.2.1.i of the Code.",
        ["ISC-L:IV.2.d", "ISC:12.2.1.i"],
    ),
    # --- the book named after the number, or a space after the section letter
    ("Alleged breach of Article 1.2.3 of the FIA F1 Regulations.", ["F1-B:1.2.3"]),
    ("Breach of Article 4.5.6.b of the FIA Formula One Sporting Regulations.", ["F1-B:4.5.6.b"]),
    ("Breach of Article 4.5.6 of the Formula 1 Regulations.", ["F1-B:4.5.6"]),
    ("Breach of Article B 1.2.3b of the FIA F1 Regulations.", ["F1-B:1.2.3.b"]),
    ("Alleged breach of Article 3.4.5 b) of Appendix H to the International Sporting Code.", ["ISC-H:3.4.5.b"]),
    (
        "Breaches of Appendix H, Article 3.4.5 b) of the Code and Article 1.2.3.b of the FIA F1 Regulations.",
        ["ISC-H:3.4.5.b", "F1-B:1.2.3.b"],
    ),
    (
        "Breach of Article B1.2.3 a) of the FIA F1 Regulations and Article 3.4.5 b) of Appendix H to the Code.",
        ["F1-B:1.2.3.a", "ISC-H:3.4.5.b"],
    ),
    (
        "Breaches of Article 1.2.3 of the FIA F1 Regulations and Appendix L, Chapter IV, Article 2 e) of the Code.",
        ["F1-B:1.2.3", "ISC-L:IV.2.e"],
    ),
    (  # a waiting number keeps its place in the order when an appendix article follows it
        "Breaches of Article 12.2.1.i and Appendix L, Chapter IV, Article 2 d) of the Code.",
        ["ISC:12.2.1.i", "ISC-L:IV.2.d"],
    ),
    ("Breach of Article 12.2.1.i", ["ISC:12.2.1.i"]),  # no book named at all: the body of the Code
    # --- numbers that are not articles
    ("Car 44 was slow at turn 12 on lap 3.", []),
    ("Track limits in Q1 and SQ2, cars 7 and 21.", []),
    ("Non-compliance with the Event Note, item 3.2, document 8.", []),
]


@pytest.mark.parametrize("text, expected", ARTICLES)
def test_normalise_articles(text, expected):
    assert labels.normalise_articles(text) == expected


def test_the_article_table_covers_at_least_forty_ways_of_writing():
    assert len(ARTICLES) >= 40


def penalty(penalty_type, value=None, unit=None):
    return {"type": penalty_type, "value": value, "unit": unit}


PENALTIES = [
    ("5 second time penalty.", penalty("time_penalty", 5, "s")),
    ("10 second time penalty imposed after the race.", penalty("time_penalty", 10, "s")),
    ("5 seconds time penalty", penalty("time_penalty", 5, "s")),
    ("5 second time penalty. 2 penalty points (total of 3 for the period).", penalty("time_penalty", 5, "s")),
    ("Drive through penalty.", penalty("drive_through")),
    ("Drive-through penalty imposed after the race. (20 seconds added to the race time).", penalty("drive_through")),
    ("Stop and Go Penalty", penalty("stop_go")),
    ("Stop-go penalty imposed after the race.", penalty("stop_go")),
    ("10 second stop and go penalty.", penalty("stop_go", 10, "s")),
    ("Drop of 10 grid positions for the driver's next race.", penalty("grid_drop", 10, "places")),
    ("A drop of one grid position for the next race. One penalty point.", penalty("grid_drop", 1, "places")),
    ("Drop of 5 grid places.", penalty("grid_drop", 5, "places")),
    ("Required to start the Sprint from the pit lane.", penalty("pit_lane_start")),
    ("Required to start the race from pit lane under Article B3.5.7b.", penalty("pit_lane_start")),
    ("The competitor (Northwind Racing) is fined €5,000.", penalty("fine", 5000, "EUR")),
    ("The Competitor (Northwind Racing) is fined €5.000.", penalty("fine", 5000, "EUR")),
    ("The competitor (Northwind Racing) is fined €1000.", penalty("fine", 1000, "EUR")),
    ("The competitor (Northwind Racing) is fined €200.", penalty("fine", 200, "EUR")),
    ("The competitor is fined €30,000, €20,000 of which is suspended for 12 months.", penalty("fine", 30000, "EUR")),
    ("A fine of €10,000 is imposed on the driver.", penalty("fine", 10000, "EUR")),
    ("Driver: Reprimand (Driving). This is the driver’s 2nd reprimand of the season.", penalty("reprimand")),
    ("Driver: Reprimand", penalty("reprimand")),
    ("Driver: Warning.", penalty("warning")),
    ("Competitor: Formal warning.", penalty("warning")),
    ("No further action.", penalty("no_further_action")),
    ("No Further Action", penalty("no_further_action")),
    ("No penalty is applied.", penalty("no_further_action")),
    ("Car 9 is disqualified from the Sprint classification.", penalty("disqualification")),
    ("The lap time of car 9 is deleted.", penalty("other")),
    # the heavier penalty wins when two are named
    ("5 second time penalty. No further action on the second matter.", penalty("time_penalty", 5, "s")),
]


@pytest.mark.parametrize("text, expected", PENALTIES)
def test_parse_penalty(text, expected):
    assert labels.parse_penalty(text) == expected


def test_every_penalty_type_a_rule_can_return_is_a_known_type():
    assert {expected["type"] for _, expected in PENALTIES} <= set(labels.PENALTY_TYPES)


KINDS = [
    ("The following elements have been used: 5th engine", ["F1-B:8.2.2", "F1-B:8.2.3"], "component_allowance"),
    # a component breach stays one even when a second, procedural article is cited with it
    ("The following elements have been used: 4th battery", ["F1-B:8.2.2", "F1-B:3.5.3"], "component_allowance"),
    ("Pit lane speeding – 96.3 km/h", ["F1-B:1.6.3.a"], "pit_lane_speeding"),
    ("Car 7 hit Car 8 at turn 3.", ["ISC-L:IV.2.d"], "judgment_incident"),
    ("Car 7 left the track and kept the place.", ["F1-B:1.8.6", "ISC-L:IV.2.c"], "judgment_incident"),
    ("Car 7 held up Car 8 in qualifying.", ["F1-B:4.1.1"], "judgment_incident"),
    ("Car 7 did not slow for yellow flags.", ["ISC-H:2.5.5.b"], "judgment_incident"),
    ("Car 7 was sent out with a loose wheel.", ["F1-B:1.6.2.a"], "procedural_or_technical"),
    ("The floor of car 7 was too low.", ["F1-C:3.5.5"], "procedural_or_technical"),
    ("The driver did not follow an instruction.", ["ISC:12.2.1.i"], "procedural_or_technical"),
    ("Nothing was cited.", [], "procedural_or_technical"),
]


@pytest.mark.parametrize("fact, articles, expected", KINDS)
def test_classify_kind(fact, articles, expected):
    assert labels.classify_kind(fact, articles) == expected


def test_an_event_date_decides_the_split():
    boundaries = {"dev_from": "2031-06-01", "test_from": "2031-08-01"}
    assert labels.split_for("2031-05-31", **boundaries) is None
    assert labels.split_for("2031-06-01", **boundaries) == "dev"
    assert labels.split_for("2031-07-31", **boundaries) == "dev"
    assert labels.split_for("2031-08-01", **boundaries) == "test"

