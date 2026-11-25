"""Scoring recorded answers: per configuration, paired differences, baselines, the self-checks.

The rows are written by hand in the shape eval/answers.py records. No FIA text, no model.
"""

import pytest

from f1aisteward.eval import report

FIVE = {"type": "time_penalty", "value": 5, "unit": "s"}
TEN = {"type": "time_penalty", "value": 10, "unit": "s"}
NFA = {"type": "no_further_action", "value": None, "unit": None}

LABELS = {
    "e1-001": {"id": "e1-001", "event": "e1", "articles": ["ISC-L:IV.2.d"], "penalty": TEN, "kind": "judgment_incident"},
    "e1-002": {"id": "e1-002", "event": "e1", "articles": ["ISC-L:IV.2.d"], "penalty": TEN, "kind": "judgment_incident"},
    "e1-003": {"id": "e1-003", "event": "e1", "articles": ["F1-B:8.2.2"], "penalty": FIVE, "kind": "component_allowance"},
    "e2-001": {"id": "e2-001", "event": "e2", "articles": ["ISC-L:IV.2.d"], "penalty": FIVE, "kind": "judgment_incident"},
    "e2-002": {"id": "e2-002", "event": "e2", "articles": ["ISC-L:IV.2.d"], "penalty": NFA, "kind": "judgment_incident"},
    "e2-003": {"id": "e2-003", "event": "e2", "articles": ["F1-B:8.2.2"], "penalty": FIVE, "kind": "component_allowance"},
}
ROUNDS = {"e1": 1, "e2": 2}
DATES = {"e1": "2031-03-01", "e2": "2031-07-01"}
REGULATIONS = {"issues": [{"id": "B-01", "book": "F1-B", "in_force_from": "2031-01-01"}]}


def row(question, config, status="ok", articles=("ISC-L:IV.2",), penalty=FIVE, ids=None, shown=("e1-001",), cost=0.001):
    return {
        "question": question,
        "ids": ids or [question],
        "event": LABELS[question]["event"],
        "kind": LABELS[question]["kind"],
        "config": config,
        "status": status,
        "answer": {"articles": list(articles), "penalty": penalty, "precedents_used": []} if status == "ok" else None,
        "check": {"passed": True, "unknown_articles": [], "unknown_decisions": []} if status == "ok" else None,
        "shown": {"articles": ["B-01/F1-B:8.2.2"], "decisions": list(shown)},
        "usage": {"input_tokens": 2000, "cached_tokens": 0, "output_tokens": 300, "reasoning_tokens": 200},
        "seconds": 3.0,
        "cost": cost,
    }


def test_a_failed_call_is_counted_and_not_scored_as_wrong():
    rows = [row("e2-001", "none"), row("e2-003", "none", status="truncated")]
    result = report.configuration(rows, LABELS)
    assert result["answered"] == 1 and result["failed"] == {"truncated": 1}
    assert result["scores"]["both"] == 1.0  # the one answer was right; the failure is not a zero
    assert result["cost_per_question"] == pytest.approx(0.001)  # a failed call still costs


def test_scores_are_split_by_kind_and_by_fixed_or_discretionary():
    rows = [row("e2-001", "rules"), row("e2-003", "rules", articles=["F1-B:8.2.2"], penalty=TEN)]
    result = report.configuration(rows, LABELS)
    assert result["by_kind"]["judgment_incident"]["both"] == 1.0
    assert result["by_kind"]["component_allowance"]["penalty"] == 0.0
    assert set(result["by_basis"]) == {"fixed", "discretionary"}


def test_a_question_for_two_cars_takes_either_penalty():
    shared = ["e2-001", "e2-002"]
    rows = [row("e2-001", "none", ids=shared, penalty=NFA), row("e2-001", "rules", ids=shared, penalty=FIVE)]
    assert report.configuration(rows[:1], LABELS)["scores"]["penalty"] == 1.0
    assert report.configuration(rows[1:], LABELS)["scores"]["penalty"] == 1.0


def test_differences_are_paired_on_the_questions_both_configurations_answered():
    by_config = {
        "none": [row("e2-001", "none", penalty=TEN), row("e2-003", "none", status="timeout")],
        "rules": [row("e2-001", "rules"), row("e2-003", "rules", articles=["F1-B:8.2.2"])],
    }
    result = report.differences(by_config, LABELS)["rules - none"]
    assert result["penalty"]["questions"] == 1  # e2-003 failed in one of the two
    assert result["penalty"]["difference"] == 1.0


def test_baselines_need_no_model():
    rows = [row("e2-001", "rules_and_decisions", shown=["e1-001", "e1-002", "e1-003"])]
    result = report.baselines(rows, LABELS, ROUNDS)
    # Earlier event e1: IV.2.d twice and 10 s twice, so both baselines say IV.2.d, 10 s.
    # The stewards gave 5 s: the article is right, the penalty is not.
    for baseline in ("most_common", "majority_of_5"):
        assert result[baseline]["article_hit"] == 1.0
        assert result[baseline]["penalty"] == 0.0


def test_the_checks_pass_on_clean_rows_and_catch_a_leak():
    clean = [row("e2-001", "rules_and_decisions"), row("e2-003", "rules_and_decisions")]
    result = report.checks(clean, LABELS, ROUNDS, REGULATIONS, DATES)
    assert set(result["gold_in_scores"].values()) == {1.0}
    assert set(result["empty_answer_scores"].values()) == {0.0}
    assert result["searches_that_returned_own_or_later_event"] == 0
    assert result["articles_shown_from_an_issue_not_in_force"] == 0

    leaked = [row("e2-001", "rules_and_decisions", shown=["e2-002"])]  # a decision of its own event
    assert report.checks(leaked, LABELS, ROUNDS, REGULATIONS, DATES)["searches_that_returned_own_or_later_event"] == 1


def test_markdown_has_one_row_per_configuration_and_baseline():
    by_config = {c: [row("e2-001", c)] for c in ("none", "rules", "rules_and_decisions")}
    summary = {
        "runs": {"test-luna": {"model": "gpt-6-luna", "reasoning_effort": "medium", "split": "test"}},
        "answers": {
            "test-luna": {
                "configurations": {c: report.configuration(rs, LABELS) for c, rs in by_config.items()},
                "differences": report.differences(by_config, LABELS),
                "baselines": report.baselines(by_config["rules_and_decisions"], LABELS, ROUNDS),
            }
        }
    }
    text = report.markdown(summary)
    assert text.count("| Retrieved rules and past decisions |") == 1
    assert "No model: the majority of the 5 past decisions found" in text
    assert "| rules_and_decisions - none |" in text


def test_two_models_are_compared_on_the_questions_both_answered():
    full = {
        "a": [row("e2-001", "rules_and_decisions"), row("e2-003", "rules_and_decisions", articles=["F1-B:8.2.2"])],
        "b": [row("e2-001", "rules_and_decisions", penalty=TEN), row("e2-003", "rules_and_decisions", status="timeout")],
    }
    result = report.between_models(full, LABELS)["a - b"]
    assert result["penalty"]["questions"] == 1 and result["penalty"]["difference"] == 1.0


def test_no_shared_questions_is_not_reported_as_no_difference():
    full = {"a": [row("e2-001", "rules_and_decisions")], "b": [row("e2-003", "rules_and_decisions")]}
    result = report.between_models(full, LABELS)["a - b"]["both"]
    assert result["questions"] == 0 and result["difference"] is None
    assert report._points(result) == "no shared questions"

