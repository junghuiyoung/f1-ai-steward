"""The web app: names on the screen, the document image, and the JSON API.

No network and no FIA text: the documents are the made-up ones of the search tests, and
the model is a stand-in that returns a prepared answer.
"""

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from search_data import DATES, RECORDS, REGULATIONS, RULE_ARTICLES, WordCountEmbeddings

from f1aisteward import index
from f1aisteward.answer import Answer
from f1aisteward.app import pages, server, view
from f1aisteward.llm import client

# ---------------------------------------------------------------- names


@pytest.mark.parametrize(
    "article, label",
    [
        ("F1-B:1.8.6", "B1.8.6"),
        ("ISC:12.2.1.i", "ISC Art. 12.2.1.i"),
        ("ISC-L:IV.2.d", "ISC App. L Ch. IV Art. 2 d)"),
        ("ISC-L:IV.2", "ISC App. L Ch. IV Art. 2"),
        ("ISC-H:2.5.5.b", "ISC App. H Art. 2.5.5 b)"),
    ],
)
def test_article_labels_read_the_way_the_stewards_write_them(article, label):
    assert view.article_label(article) == label


@pytest.mark.parametrize(
    "penalty, text",
    [
        ({"type": "time_penalty", "value": 5, "unit": "s"}, "5 second time penalty"),
        ({"type": "grid_drop", "value": 3, "unit": "places"}, "3 place grid drop"),
        ({"type": "fine", "value": 5000, "unit": "EUR"}, "€5,000 fine"),
        ({"type": "stop_go", "value": None, "unit": None}, "Stop and go penalty"),
        ({"type": "no_further_action", "value": None, "unit": None}, "No further action"),
    ],
)
def test_penalty_text(penalty, text):
    assert view.penalty_text(penalty) == text


@pytest.mark.parametrize(
    "heading, name",
    [("ARTICLE 12.2 BREACH OF RULES", "Breach of rules"), ("B1.8 Driving", "Driving"), ("2. Overtaking", "Overtaking")],
)
def test_heading_name_drops_the_number(heading, name):
    assert view.heading_name(heading) == name


def test_issue_names():
    assert view.issue_name({"id": "F1-B-09", "book": "F1-B", "in_force_from": "2026-10-01"}) == "Sporting Regulations, Issue 09"
    assert view.issue_name({"id": "ISC-L-2026-06", "book": "ISC-L", "in_force_from": "2026-06-11"}) == "Appendix L of June 2026"


# ---------------------------------------------------------------- judgements


FIVE = {"type": "time_penalty", "value": 5, "unit": "s"}
TEN = {"type": "time_penalty", "value": 10, "unit": "s"}


def test_compare_uses_the_scoring_rules_of_the_evaluation():
    stewards = {"articles": ["ISC-L:IV.2.d"], "penalty": FIVE}
    assert view.compare(["ISC-L:IV.2"], FIVE, stewards) == {"rule": "yes", "outcome": "yes"}
    assert view.compare(["ISC-L:IV.2"], TEN, stewards) == {"rule": "yes", "outcome": "partial"}
    assert view.compare(["ISC-L:IV.2", "F1-B:1.8.6"], FIVE, stewards)["rule"] == "partial"
    assert view.compare(["F1-B:1.8.6"], {"type": "warning", "value": None, "unit": None}, stewards) == {
        "rule": "no",
        "outcome": "no",
    }


def test_basis_says_fixed_for_a_penalty_set_by_a_table():
    assert view.basis("Race. Pit lane speeding – 85 km/h", ["F1-B:1.6.3.a"], []) == "fixed"
    assert view.basis("Race. Car 7 hit Car 8.", ["ISC-L:IV.2"], [{"id": "x"}]) == "usual"
    assert view.basis("Race. Car 7 hit Car 8.", ["ISC-L:IV.2"], []) == "rules_only"


# ---------------------------------------------------------------- the document image


def page(height, ink_rows):
    """A white page with black lines at the given rows."""
    image = Image.new("RGB", (100, height), "white")
    for y in ink_rows:
        image.paste((0, 0, 0), (10, y, 90, y + 2))
    return image


def test_pages_are_trimmed_and_stacked_with_a_line_between():
    sheet = pages.stack([page(1000, [50, 200]), page(1000, [100, 150]), page(1000, [])])
    # page 1 from its top to its last line + margin; page 2 from its first line - margin; the blank page dropped
    first = 202 + pages.MARGIN
    second = (152 + pages.MARGIN) - (100 - pages.MARGIN)
    assert sheet.size == (100, first + 2 + second)
    assert sheet.getpixel((50, first)) == pages.DIVIDER


def test_a_document_of_blank_pages_still_gives_an_image():
    assert pages.stack([page(500, []), page(500, [])]).size == (100, 500)


def test_no_image_without_the_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "pdf_path", lambda event, number: tmp_path / "missing.pdf")
    assert pages.page_image({"id": "2031-round1-001", "event": "round1", "number": 1}, tmp_path) is None


# ---------------------------------------------------------------- the API


def full(record):
    """A made-up record with the fields a parsed decision has beyond the search tests' ones."""
    return {
        **record,
        "url": f"https://example.org/{record['id']}.pdf",
        "infringement": "Breach of a made-up article.",
        "decision": "5 second time penalty.",
        "reason": "Made up for a test.",
    }


EVENTS = [
    {"slug": f"round{n}", "name": f"Round {n} Grand Prix", "round": n, "date": DATES[n],
     "docs": [{"number": 1, "subject": "Car 7 - Pushing another car wide"}]}
    for n in (1, 2, 3)
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    records = [full(r) for r in RECORDS]
    embeddings = WordCountEmbeddings()
    steward = server.Steward(
        records,
        server.DecisionSearch(records, index.build_vector_store(records, embeddings, tmp_path)),
        server.RuleSearch(RULE_ARTICLES, REGULATIONS, index.build_rule_store(RULE_ARTICLES, embeddings, tmp_path)),
        EVENTS,
    )
    asked = []

    def stand_in(messages, schema, **settings):
        asked.append(messages[1].content)
        answer = Answer(
            articles=["ISC-L:IV.2", "F1-B:9.9.9"],
            penalty_type="time_penalty",
            penalty_value=5,
            penalty_unit="s",
            rationale="Made up.",
            precedents_used=["2031-round2-001"],
        )
        return client.Reply("ok", answer, "gpt-6-luna", 1.0, client.Usage(3000, 0, 300, 200))

    monkeypatch.setattr(client, "ask", stand_in)
    test_client = TestClient(server.create_app(steward))
    test_client.asked = asked
    return test_client


def test_events_are_newest_first_after_an_entry_for_after_the_latest(app):
    reply = app.get("/api/events").json()
    assert [e["slug"] for e in reply["events"]] == [None, "round3", "round2", "round1"]
    round3 = reply["events"][1]
    assert round3["weekends_before"] == 2 and round3["decisions_before"] == 5
    assert round3["incidents"][0]["title"] == "Car 7 - Pushing another car wide"
    assert reply["default"] == "round3"


def test_ask_answers_from_earlier_events_and_drops_a_citation_that_was_not_shown(app):
    reply = app.post(
        "/api/ask", json={"text": "Car 7 pushed Car 8 wide at turn 3.", "session": "Race", "event": "round3"}
    ).json()

    assert reply["question"] == "Race. Car 7 pushed Car 8 wide at turn 3."
    assert "2031-round3-" not in app.asked[0]  # its own event never reaches the prompt
    answer = reply["answer"]
    assert answer["outcome"] == "5 second time penalty"
    assert [a["label"] for a in answer["articles"]] == ["ISC App. L Ch. IV Art. 2"]
    assert answer["articles"][0]["title"] == "Overtaking"
    assert answer["left_out"] == ["F1-B:9.9.9 is not among the articles shown"]
    assert [p["id"] for p in answer["precedents"]] == ["2031-round2-001"]
    # The made-up earlier collisions were decided under F1-B:1.2.3, not IV.2: nothing to count,
    # so the penalty rests on the rules only.
    assert reply["similar"]["total"] == 0 and answer["basis"] == "rules_only"
    assert reply["stewards"] is None  # a typed incident has no decision to compare with


def test_a_real_incident_comes_back_with_the_stewards_decision_and_the_comparison(app):
    reply = app.post(
        "/api/ask",
        json={"text": "Car 7 pushed Car 8 wide at turn 3.", "session": "Race", "event": "round3", "decision": "2031-round3-001"},
    ).json()
    stewards = reply["stewards"]
    assert stewards["id"] == "2031-round3-001" and stewards["outcome"] == "5 second time penalty"
    assert stewards["verdict"] == {"rule": "no", "outcome": "yes"}  # made-up article F1-B:1.2.3 against IV.2


def test_a_decision_of_another_weekend_is_not_shown_as_the_stewards_decision(app):
    reply = app.post(
        "/api/ask", json={"text": "Car 7 pushed Car 8 wide.", "event": "round3", "decision": "2031-round2-001"}
    ).json()
    assert reply["stewards"] is None


def test_an_empty_incident_is_refused_before_any_search(app):
    reply = app.post("/api/ask", json={"text": "   ", "event": "round3"})
    assert reply.status_code == 400 and reply.json()["detail"] == "Describe what happened first."
    assert app.asked == []


def test_a_missing_document_is_a_404_that_says_what_to_run(app):
    reply = app.get("/api/decisions/2031-round1-001.png")
    assert reply.status_code == 404 and "fetch" in reply.json()["detail"]
    assert app.get("/api/decisions/no-such-id.pdf").status_code == 404


def test_a_call_with_no_answer_says_why_and_shows_nothing_else(app, monkeypatch):
    monkeypatch.setattr(
        client, "ask", lambda messages, schema, **settings: client.Reply("truncated", None, "gpt-6-luna", 9.0)
    )
    reply = app.post("/api/ask", json={"text": "Car 7 pushed Car 8 wide.", "event": "round3"}).json()
    assert reply["status"] == "truncated" and "cut off" in reply["message"]
    assert (reply["answer"], reply["similar"], reply["stewards"]) == (None, None, None)
