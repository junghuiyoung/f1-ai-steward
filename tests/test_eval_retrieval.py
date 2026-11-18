"""The search evaluation asks the right questions and counts hits the way it says it does."""

from collections import Counter

import pytest
from search_data import RECORDS, decision

from f1aisteward.eval import retrieval
from f1aisteward.parse import labels
from f1aisteward.search import DecisionSearch, RuleSearch


def records_2026():
    """The made-up decisions on dates around the real boundaries: round 1 is before the
    dev period, round 2 is dev and round 3 is test."""
    dates = {1: "2026-05-01", 2: "2026-07-01", 3: "2026-09-01"}
    return [{**record, "date": dates[record["round"]]} for record in RECORDS]


def test_the_season_is_cut_at_the_model_cutoff_and_at_the_summer_break():
    assert labels.split_for("2026-05-25") is None  # Canadian
    assert labels.split_for("2026-06-07") == "dev"  # Monaco
    assert labels.split_for("2026-07-26") == "dev"  # Hungarian
    assert labels.split_for("2026-08-23") == "test"  # Dutch


def test_a_split_holds_only_its_own_events():
    dev, _ = retrieval.build_questions(records_2026(), "dev")
    test, _ = retrieval.build_questions(records_2026(), "test")

    assert {question.event for question in dev} == {"round2"}
    assert {question.event for question in test} == {"round3"}
    assert dev[0].text == "Race. Car 7 pushed Car 8 wide at turn 3."
    assert dev[0].articles == {"F1-B:1.2.3"}


def test_decisions_that_share_a_text_make_one_question_with_all_their_articles():
    records = records_2026() + [
        {**decision(2, 4, "Car 7 pushed Car 8 wide at turn 3.", ["F1-B:9.9.9"]), "date": "2026-07-01"}
    ]
    questions, _ = retrieval.build_questions(records, "dev")

    [shared] = [q for q in questions if q.text == "Race. Car 7 pushed Car 8 wide at turn 3."]
    assert shared.ids == ["2031-round2-001", "2031-round2-004"]
    assert shared.articles == {"F1-B:1.2.3", "F1-B:9.9.9"}
    assert len(questions) == 3


def test_questions_that_cannot_be_asked_fairly_are_left_out_and_counted():
    july = {"date": "2026-07-01"}
    records = records_2026() + [
        {**decision(2, 5, "The cars below were too slow.", layout="car_table"), **july},
        {**decision(2, 6, "Car 9 breached Article B1.2.3 at turn 3."), **july},
        {**decision(2, 7, "Car 9 used tyres it should not have.", articles=[]), **july},
    ]
    questions, left_out = retrieval.build_questions(records, "dev")

    assert len(questions) == 3
    assert left_out == Counter(
        {
            "the Fact only points at a table of cars": 1,
            "the question names an article": 1,
            "no article to score against": 1,
        }
    )


def test_reworded_questions_replace_the_text_and_keep_the_gold_answer():
    reworded = {"2031-round2-001": "One driver forced another off the road.", "2031-round2-003": "Too fast in the pits."}
    questions, left_out = retrieval.build_questions(records_2026(), "dev", reworded)

    assert [q.text for q in questions] == ["One driver forced another off the road.", "Too fast in the pits."]
    assert questions[0].articles == {"F1-B:1.2.3"}
    assert left_out == Counter({"no reworded question": 1})


class FixedSearch:
    """Returns the same decisions for every question."""

    def __init__(self, results):
        self.results = results

    def search(self, question, before_round, method, k):
        return self.results[:k]


def test_hit_and_precision_are_counted_per_question():
    questions, _ = retrieval.build_questions(records_2026(), "dev")  # articles 1.2.3, 4.5.6, 7.8.9
    found = [RECORDS[0], RECORDS[0], RECORDS[1], RECORDS[0]]  # round 1: three under 1.2.3, one under 4.5.6

    score = retrieval.evaluate(FixedSearch(found), questions, "bm25", k=4)

    assert score.hit == pytest.approx(2 / 3)  # the pit lane speeding question finds nothing
    assert score.precision == pytest.approx((3 / 4 + 1 / 4 + 0) / 3)


def test_missing_results_count_as_wrong():
    questions, _ = retrieval.build_questions(records_2026(), "dev")
    score = retrieval.evaluate(FixedSearch([RECORDS[0]]), questions[:1], "bm25", k=5)
    assert score.hit == 1.0
    assert score.precision == pytest.approx(1 / 5)


def test_the_evaluation_stops_if_search_returns_the_questions_own_event():
    questions, _ = retrieval.build_questions(records_2026(), "dev")
    with pytest.raises(AssertionError, match="2031-round2-001"):
        retrieval.evaluate(FixedSearch([RECORDS[2]]), questions, "bm25")


def test_questions_with_no_earlier_decision_under_their_article_are_counted():
    records = records_2026()
    questions, _ = retrieval.build_questions(records, "dev")
    assert retrieval.out_of_reach(records, questions) == 1  # pit lane speeding first appears in round 2


def test_the_real_search_scores_the_made_up_decisions():
    records = records_2026()
    questions, left_out = retrieval.build_questions(records, "dev")
    score = retrieval.evaluate(DecisionSearch(records), questions, "bm25", k=2)

    assert score.hit == pytest.approx(2 / 3)
    text = retrieval.report("Made-up questions", records, questions, left_out, [score])
    assert "Made-up questions: 3 questions" in text
    assert "no earlier decision under the same article: 1" in text
    assert "bm25" in text and "0.667" in text


# ---------------------------------------------------------------- rules


def rule_questions():
    """Made-up dev questions: two in March (issue B-01), one in July (issue B-02)."""
    from f1aisteward.eval.retrieval import Question

    return [
        Question("Car 4 was released into the path of Car 9.", "march", 2, "2031-03-01", ["a"], {"F1-B:4.5.6"}),
        Question("Car 7 pushed Car 8 wide.", "march", 2, "2031-03-01", ["b"], {"ISC-L:IV.2.d", "F1-C:1.2"}),
        Question("Car 6 was too fast in the pit lane.", "july", 3, "2031-07-01", ["c"], {"F1-B:7.8.9"}),
    ]


class FixedRuleSearch(RuleSearch):
    """Search alone returns the same articles for every question; the rest is the real thing."""

    def __init__(self, results):
        from search_data import REGULATIONS, RULE_ARTICLES

        super().__init__(RULE_ARTICLES, REGULATIONS)
        self.results = results

    def closest(self, question, date, method, k):
        return self.results[:k]


class FixedDecisionSearch:
    """Finds the same past decisions for every question, and notes which rounds it was asked about."""

    def __init__(self, decisions):
        self.decisions = decisions
        self.before = []

    def search(self, question, before_round, method):
        self.before.append(before_round)
        return self.decisions


def test_recall_counts_the_share_of_cited_articles_found_per_question():
    from search_data import RULE_ARTICLES

    # B-01's 4.5.6 and the appendix article. The July question is asked of issue B-02, so it
    # may not get these: a search that returned them would be stopped (next test).
    found = [RULE_ARTICLES[1], RULE_ARTICLES[4]]
    questions = rule_questions()[:2]

    score = retrieval.evaluate_rules(FixedRuleSearch(found), questions, "bm25", k=8)

    # question 1 finds its one article; question 2 finds IV.2.d inside IV.2 but not F1-C:1.2
    assert score.recall == pytest.approx((1 + 1 / 2) / 2)
    assert (score.method, score.articles, score.most) == ("bm25", 2, 2)


def test_the_articles_cited_by_the_decisions_found_count_towards_recall():
    # Search alone finds nothing. The one past decision found cites IV.2.b and a Section C article.
    decisions = FixedDecisionSearch([{"id": "2031-round1-001", "articles": ["ISC-L:IV.2.b", "F1-C:1.2"]}])
    questions = rule_questions()[:2]

    alone = retrieval.evaluate_rules(FixedRuleSearch([]), questions, "bm25")
    cited = retrieval.evaluate_rules(FixedRuleSearch([]), questions, "bm25", decision_search=decisions)

    assert (alone.recall, alone.articles) == (0, 0)
    # Question 2 cites IV.2.d, which IV.2 holds, and IV.2 also holds the decision's IV.2.b.
    # F1-C is not included, so neither the decision's nor the question's F1-C:1.2 counts.
    assert cited.recall == pytest.approx((0 + 1 / 2) / 2)
    assert (cited.method, cited.articles, cited.most) == ("bm25 + cited", 1, 1)
    assert decisions.before == [2, 2]  # decisions were looked for in earlier rounds only


def test_the_evaluation_stops_if_search_returns_an_issue_not_in_force():
    from search_data import RULE_ARTICLES

    july = rule_questions()[2:]
    with pytest.raises(AssertionError, match="B-01/F1-B:7.8.9"):
        retrieval.evaluate_rules(FixedRuleSearch([RULE_ARTICLES[0]]), july, "bm25")


def test_citations_outside_the_included_books_are_counted_and_lower_the_best_possible_recall():
    reach = retrieval.rule_reach(FixedRuleSearch([]), rule_questions())

    assert reach.cited == 4
    assert reach.outside_the_books == Counter({"F1-C": 1})
    assert reach.not_in_the_issue == []
    assert reach.best_recall == pytest.approx((1 + 1 / 2 + 1) / 3)


def test_the_real_rule_search_scores_the_made_up_rules():
    from search_data import REGULATIONS, RULE_ARTICLES

    searcher = RuleSearch(RULE_ARTICLES, REGULATIONS)
    questions = rule_questions()
    score = retrieval.evaluate_rules(searcher, questions, "bm25", k=1)
    text = retrieval.report_rules("Made-up", questions, retrieval.rule_reach(searcher, questions), [score])

    assert "Made-up: 3 questions citing 4 articles" in text
    assert "not included (F1-C): 1" in text
    assert "best possible recall: 0.833" in text
    assert "bm25" in text and "recall" in text and "articles" in text
