"""The prompt, the citation check, the outcome counts, and the whole flow with a stand-in model.

No network and no FIA text: the decisions and articles are the made-up ones of the search
tests, and `client.ask` is replaced by a function that returns a prepared reply.
"""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from search_data import RECORDS, REGULATIONS, RULE_ARTICLES, WordCountEmbeddings, decision

from f1aisteward import answer as answering
from f1aisteward import index
from f1aisteward.answer import Answer
from f1aisteward.llm import client
from f1aisteward.parse import labels
from f1aisteward.search import DecisionSearch, RuleSearch


def an_answer(**changes) -> Answer:
    fields = {
        "articles": ["ISC-L:IV.2"],
        "penalty_type": "time_penalty",
        "penalty_value": 5,
        "penalty_unit": "s",
        "rationale": "Car 7 pushed Car 8 wide.",
        "precedents_used": ["2031-round1-001"],
    }
    return Answer(**(fields | changes))


def ok(parsed: Answer) -> client.Reply:
    return client.Reply("ok", parsed, "gpt-6-luna", 1.0, client.Usage(5000, 0, 600, 400))


# ---------------------------------------------------------------- the schema


def test_the_penalty_types_are_the_labels_of_step_1():
    # So an answer can be compared with the stewards' decision without translating.
    assert Answer.model_json_schema()["properties"]["penalty_type"]["enum"] == list(labels.PENALTY_TYPES)


def test_every_field_is_required_as_strict_structured_output_demands():
    assert Answer.model_json_schema()["required"] == list(Answer.model_fields)


# ---------------------------------------------------------------- the prompt


def test_the_prompt_is_instructions_then_articles_then_decisions_then_the_incident():
    system, user = answering.messages("Race. Car 9 hit Car 2.", RULE_ARTICLES[4:], RECORDS[:1])

    assert isinstance(system, SystemMessage) and isinstance(user, HumanMessage)
    text = user.content
    positions = [text.index(part) for part in ("[ISC-L:IV.2]", "[2031-round1-001]", "Race. Car 9 hit Car 2.")]
    assert positions == sorted(positions)
    assert text.endswith("Race. Car 9 hit Car 2.")


def test_each_decision_shows_its_fact_articles_and_penalty():
    _, user = answering.messages("q", [], [decision(1, 4, "Car 3 hit Car 4.", ["ISC-L:IV.2.d"])])

    assert "Fact: Car 3 hit Car 4." in user.content
    assert "Articles: ISC-L:IV.2.d" in user.content
    assert "Penalty: time_penalty 5 s" in user.content


def test_an_empty_part_of_the_prompt_says_none():
    # The same words whether search found nothing (the first event of a season) or was
    # switched off (the no-search configuration of the answer evaluation).
    _, user = answering.messages("q", [], [])
    assert user.content == "\n\n".join(
        ["# Articles of the rules in force", "None.", "# Earlier stewards' decisions", "None.", "# The incident", "q"]
    )


# ---------------------------------------------------------------- the check


def test_an_id_copied_with_its_square_brackets_is_still_the_id():
    checked = answering.check(
        an_answer(articles=["[ISC-L:IV.2]"], precedents_used=["[2031-round1-001]"]), [RULE_ARTICLES[4]], RECORDS[:1]
    )
    assert checked.passed
    assert (checked.articles, checked.decisions) == (["ISC-L:IV.2"], ["2031-round1-001"])

SHOWN_ARTICLES = [RULE_ARTICLES[4]]  # ISC-L:IV.2
SHOWN_DECISIONS = [decision(1, 1, "Car 7 pushed Car 8 wide.", ["ISC-L:IV.2.d", "F1-C:9.3"])]


@pytest.mark.parametrize(
    "articles, used, passed",
    [
        (["ISC-L:IV.2"], ["2031-round1-001"], True),  # exactly as shown
        (["ISC-L:IV.2.d"], [], True),  # a point inside a paragraph that was shown
        (["F1-C:9.3"], [], True),  # not a searched book, but a decision shown cites it
        (["F1-B:9.9.9"], [], False),  # never shown
        (["Appendix L, Chapter IV, Article 2 d)"], [], False),  # not an id at all
        (["ISC-L:IV.2"], ["2031-round2-001"], False),  # a decision the model was not shown
        ([], [], False),  # no article
    ],
)
def test_the_check_accepts_only_what_the_model_was_shown(articles, used, passed):
    checked = answering.check(an_answer(articles=articles, precedents_used=used), SHOWN_ARTICLES, SHOWN_DECISIONS)
    assert checked.passed is passed


def test_the_check_keeps_the_good_citations_and_names_the_bad_ones():
    cited = an_answer(articles=["ISC-L:IV.2", "F1-B:9.9.9"], precedents_used=["2031-round1-001", "made-up"])
    checked = answering.check(cited, SHOWN_ARTICLES, SHOWN_DECISIONS)

    assert (checked.articles, checked.unknown_articles) == (["ISC-L:IV.2"], ["F1-B:9.9.9"])
    assert (checked.decisions, checked.unknown_decisions) == (["2031-round1-001"], ["made-up"])


def test_related_does_not_confuse_article_12_with_article_1():
    assert answering.related("ISC:12.2.1", "ISC:12")
    assert not answering.related("ISC:12.2.1", "ISC:1")
    assert not answering.related("F1-B:1.21", "F1-B:1.2")


# ---------------------------------------------------------------- the counts


def with_penalty(record: dict, type_: str, value=None, unit=None) -> dict:
    return record | {"penalty": {"type": type_, "value": value, "unit": unit}}


def test_the_counts_are_over_earlier_decisions_under_the_answers_article():
    pool = [
        with_penalty(decision(1, 1, "a", ["ISC-L:IV.2.d"]), "time_penalty", 5, "s"),
        with_penalty(decision(1, 2, "b", ["ISC-L:IV.2.a"]), "warning"),
        with_penalty(decision(1, 3, "c", ["ISC-L:IV.2.d"]), "time_penalty", 5, "s"),
        with_penalty(decision(1, 4, "d", ["F1-B:4.5.6"]), "fine", 5000, "EUR"),  # another article
    ]
    counted = answering.outcomes(["ISC-L:IV.2"], pool)

    assert counted.looked_at == 4
    assert [d["number"] for d in counted.matching] == [1, 2, 3]
    assert counted.counts == [("time_penalty 5 s", 2), ("warning", 1)]


# ---------------------------------------------------------------- the whole flow


@pytest.fixture
def searchers(tmp_path):
    embeddings = WordCountEmbeddings()
    decisions = DecisionSearch(RECORDS, index.build_vector_store(RECORDS, embeddings, directory=tmp_path))
    rules = RuleSearch(RULE_ARTICLES, REGULATIONS, index.build_rule_store(RULE_ARTICLES, embeddings, tmp_path))
    return decisions, rules


def test_answer_shows_the_model_earlier_decisions_only_and_checks_what_comes_back(searchers, monkeypatch):
    seen = []

    def stand_in(messages, schema, **settings):
        seen.append(messages[1].content)
        return ok(an_answer(articles=["ISC-L:IV.2", "F1-B:9.9.9"], precedents_used=["2031-round1-001"]))

    monkeypatch.setattr(client, "ask", stand_in)
    result = answering.answer("Race. Car 7 pushed Car 8 wide at turn 3.", *searchers, "2031-09-01", before_round=3)

    assert all(d["round"] < 3 for d in result.decisions)
    assert "2031-round3-001" not in seen[0]  # the question's own event never reaches the prompt
    assert {a["issue"] for a in result.articles} <= {"B-02", "L-01"}  # the issues in force in September
    assert result.check.unknown_articles == ["F1-B:9.9.9"]
    assert result.outcomes.articles == ["ISC-L:IV.2"]  # counted under the article that passed only


def test_no_answer_means_nothing_to_check_or_count(searchers, monkeypatch):
    monkeypatch.setattr(client, "ask", lambda messages, schema, **settings: client.Reply("truncated", None, "gpt-6-luna", 9.0))
    result = answering.answer("Car 7 pushed Car 8 wide.", *searchers, "2031-09-01", before_round=3)

    assert (result.check, result.outcomes) == (None, None)
    assert "No answer: the answer was cut off" in answering.report(result, ["B-02", "L-01"])


def test_the_report_leaves_a_failed_citation_out_of_the_grounds(searchers, monkeypatch):
    monkeypatch.setattr(client, "ask", lambda messages, schema, **settings: ok(an_answer(articles=["ISC-L:IV.2", "F1-B:9.9.9"])))
    result = answering.answer("Car 7 pushed Car 8 wide.", *searchers, "2031-09-01", before_round=3)
    text = answering.report(result, ["B-02", "L-01"])

    assert "Articles   ISC-L:IV.2\n" in text
    assert "Citation check: FAILED" in text
    assert "F1-B:9.9.9  is not among the articles shown" in text


def test_the_prompt_fingerprint_changes_with_the_template_not_only_the_instructions(monkeypatch):
    before = answering.prompt_version()
    monkeypatch.setattr(answering, "penalty_label", lambda penalty: "a different layout")
    assert answering.prompt_version() != before
