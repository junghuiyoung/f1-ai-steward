"""Search returns earlier decisions only, by every method, and loses none of them.

The vector index is a real Chroma collection in a temporary folder, filled by a stand-in
embedding model. Nothing here uses the network.
"""

import pytest
from search_data import RECORDS, WordCountEmbeddings, decision

from f1aisteward import index
from f1aisteward.search import METHODS, DecisionSearch, RuleSearch


@pytest.fixture
def searcher(tmp_path):
    embeddings = WordCountEmbeddings()
    return DecisionSearch(RECORDS, index.build_vector_store(RECORDS, embeddings, directory=tmp_path))


@pytest.mark.parametrize("method", METHODS)
def test_no_decision_from_the_same_or_a_later_event_is_ever_retrieved(searcher, method):
    # Every decision is asked as a question, with its own text: the strongest pull
    # there can be towards its own event.
    for record in RECORDS:
        results = searcher.search(index.chunk_text(record), before_round=record["round"], method=method, k=10)
        assert all(found["round"] < record["round"] for found in results), (method, record["id"])
        assert record["id"] not in [found["id"] for found in results]


@pytest.mark.parametrize("method", METHODS)
def test_everything_earlier_can_be_reached(searcher, method):
    results = searcher.search("Car 7 pushed Car 8 wide at turn 3.", before_round=3, method=method, k=10)
    assert {found["id"] for found in results} == {r["id"] for r in RECORDS if r["round"] < 3}
    assert results[0]["fact"] == "Car 7 pushed Car 8 wide at turn 3."


@pytest.mark.parametrize("method", METHODS)
def test_the_first_event_has_nothing_to_search_and_does_not_crash(searcher, method):
    assert searcher.search("Car 7 pushed Car 8 wide.", before_round=1, method=method) == []


@pytest.mark.parametrize("method", METHODS)
def test_without_an_event_every_decision_is_searched(searcher, method):
    results = searcher.search("released from its pit box", method=method, k=3)
    assert {found["round"] for found in results} == {1, 2, 3}


@pytest.mark.parametrize("method", METHODS)
def test_decisions_with_identical_text_are_all_returned(tmp_path, method):
    # One incident, one decision per car, the same Fact in both.
    twins = [
        decision(1, 11, "Car 7 and Car 8 collided at turn 3."),
        decision(1, 12, "Car 7 and Car 8 collided at turn 3."),
        *RECORDS[1:5],  # BM25 needs a few other decisions before a word counts as rare
    ]
    searcher = DecisionSearch(twins, index.build_vector_store(twins, WordCountEmbeddings(), directory=tmp_path))

    results = searcher.search("Car 7 and Car 8 collided at turn 3.", method=method, k=2)
    assert {found["id"] for found in results} == {"2031-round1-011", "2031-round1-012"}


def test_vector_is_the_method_when_none_is_named(searcher):
    question = "Car 5 was released from its pit box into the path of Car 2."
    assert searcher.search(question, before_round=3) == searcher.search(question, before_round=3, method="vector")
    with pytest.raises(ValueError, match="vector method needs the vector index"):
        DecisionSearch(RECORDS).search(question)


def test_k_is_the_number_of_results(searcher):
    for method in METHODS:
        assert len(searcher.search("Car 7 pushed Car 8 wide", method=method, k=2)) == 2


def test_bm25_needs_no_vector_index_and_the_others_say_what_is_missing():
    searcher = DecisionSearch(RECORDS)
    assert searcher.search("pit lane speed limit", method="bm25")[0]["id"] == "2031-round2-003"
    for method in ("vector", "hybrid"):
        with pytest.raises(ValueError, match="build --index"):
            searcher.search("pit lane speed limit", method=method)
    with pytest.raises(ValueError, match="Unknown method"):
        searcher.search("pit lane speed limit", method="magic")


def test_a_stale_vector_index_is_reported(tmp_path):
    store = index.build_vector_store(RECORDS, WordCountEmbeddings(), directory=tmp_path)
    searcher = DecisionSearch(RECORDS[:-1], store)  # the index knows a decision the records do not
    with pytest.raises(ValueError, match="build --index"):
        searcher.search("released from its pit box into the path of Car 1", method="vector", k=10)


# ---------------------------------------------------------------- rules


@pytest.fixture
def rule_searcher(tmp_path):
    from search_data import REGULATIONS, RULE_ARTICLES

    store = index.build_rule_store(RULE_ARTICLES, WordCountEmbeddings(), directory=tmp_path)
    return RuleSearch(RULE_ARTICLES, REGULATIONS, store)


@pytest.mark.parametrize("method", METHODS)
def test_only_the_issues_in_force_on_the_day_are_searched(rule_searcher, method):
    for date, in_force in [("2031-03-01", {"B-01", "L-01"}), ("2031-07-01", {"B-02", "L-01"})]:
        results = rule_searcher.search("released from the pit box", date=date, method=method, k=10)
        assert {article["issue"] for article in results} == in_force, (method, date)


@pytest.mark.parametrize("method", METHODS)
def test_an_unchanged_article_is_found_in_the_issue_in_force(rule_searcher, method):
    # Issues 1 and 2 hold this article word for word; only one of them may come back.
    [best, *_] = rule_searcher.search("pit lane speed limit", date="2031-07-01", method=method)
    assert best["key"] == "B-02/F1-B:7.8.9"


@pytest.mark.parametrize("method", METHODS)
def test_before_any_issue_there_is_nothing_to_search(rule_searcher, method):
    assert rule_searcher.search("pit lane speed limit", date="2030-01-01", method=method) == []


def test_without_a_date_the_latest_issues_are_searched(rule_searcher):
    assert sorted(rule_searcher.issues_on(None)) == ["B-02", "L-01"]
