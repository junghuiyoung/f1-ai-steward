"""The scoring rules of the answer evaluation. Every article and penalty here is made up."""

import pytest

from f1aisteward.eval import score
from f1aisteward.eval.score import Gold

FIVE_SECONDS = {"type": "time_penalty", "value": 5, "unit": "s"}
TEN_SECONDS = {"type": "time_penalty", "value": 10, "unit": "s"}
WARNING = {"type": "warning", "value": None, "unit": None}


def gold(articles=("ISC-L:IV.2.d",), penalties=(FIVE_SECONDS,), kind="judgment_incident"):
    return Gold(set(articles), list(penalties), kind)


@pytest.mark.parametrize(
    "article, number",
    [
        ("ISC-L:IV.2.d", "ISC-L:IV.2"),
        ("F1-B:1.6.2.b.i", "F1-B:1.6.2"),
        ("ISC:12.2.1.i", "ISC:12.2.1"),
        ("F1-B:8.2.2a", "F1-B:8.2.2"),
        ("F1-B:1.8.5", "F1-B:1.8.5"),
        ("ISC-L:IV", "ISC-L:IV"),  # the chapter numeral is upper case, so it stays
    ],
)
def test_article_number_drops_the_points_after_the_last_number(article, number):
    assert score.article_number(article) == number


def test_a_point_matches_its_article_and_the_article_matches_its_point():
    assert score.score(["ISC-L:IV.2"], FIVE_SECONDS, gold(["ISC-L:IV.2.d"])).article_hit
    assert score.score(["ISC-L:IV.2.b"], FIVE_SECONDS, gold(["ISC-L:IV.2.d"])).article_hit


def test_a_broader_number_is_not_a_match():
    # Otherwise an answer could cite a whole chapter and hit every article in it.
    assert not score.score(["F1-B:1.8"], FIVE_SECONDS, gold(["F1-B:1.8.5"])).article_hit
    assert not score.score(["ISC-L:IV"], FIVE_SECONDS, gold(["ISC-L:IV.2.d"])).article_hit


def test_a_citation_written_out_in_words_is_read_with_the_label_normaliser():
    marks = score.score(["Appendix L, Chapter IV, Article 2 d)"], FIVE_SECONDS, gold(["ISC-L:IV.2.d"]))
    assert marks.article_hit


@pytest.mark.parametrize(
    "written, ids",
    [
        ("ISC-L:IV.2.d", ["ISC-L:IV.2.d"]),
        ("[F1-B:1.8.5]", ["F1-B:1.8.5"]),
        ("ISC 12.2.1.i", ["ISC:12.2.1.i"]),  # a space for the colon
        ("B1.8.6", ["F1-B:1.8.6"]),
        ("33.3", ["ISC:33.3"]),  # a bare number is read as "Article 33.3": the body of the Code
    ],
)
def test_citations_a_model_writes_without_seeing_ids_are_read(written, ids):
    assert score.as_ids([written]) == ids


def test_a_citation_the_normaliser_cannot_read_matches_nothing():
    assert score.as_ids(["the collision rule"]) == ["the collision rule"]
    assert not score.score(["the collision rule"], FIVE_SECONDS, gold()).article_hit


def test_citation_precision_is_the_share_of_cited_articles_the_stewards_cited():
    marks = score.score(["ISC-L:IV.2", "F1-B:1.8.5"], FIVE_SECONDS, gold(["ISC-L:IV.2.d"]))
    assert marks.article_hit
    assert marks.citation_precision == 0.5


def test_an_answer_with_no_article_has_precision_zero():
    marks = score.score([], FIVE_SECONDS, gold())
    assert (marks.article_hit, marks.citation_precision) == (False, 0.0)


def test_the_penalty_type_can_match_while_the_size_does_not():
    marks = score.score(["ISC-L:IV.2"], TEN_SECONDS, gold())
    assert marks.penalty_type and not marks.penalty and not marks.both


def test_a_penalty_without_a_number_matches_on_its_type():
    assert score.score(["ISC-L:IV.2"], WARNING, gold(penalties=[WARNING])).both


def test_one_question_for_two_cars_accepts_the_penalty_of_either():
    group = gold(penalties=[FIVE_SECONDS, WARNING])
    assert score.score(["ISC-L:IV.2"], WARNING, group).penalty
    assert score.score(["ISC-L:IV.2"], FIVE_SECONDS, group).penalty
    assert not score.score(["ISC-L:IV.2"], TEN_SECONDS, group).penalty


def test_no_answer_scores_zero_on_everything():
    assert score.score([], None, gold()).as_dict() == dict.fromkeys(score.METRICS, 0.0)


def test_the_gold_labels_score_one_on_everything():
    g = gold(["ISC-L:IV.2.d", "F1-B:1.8.5"], [FIVE_SECONDS])
    assert score.score(["ISC-L:IV.2.d", "F1-B:1.8.5"], FIVE_SECONDS, g).as_dict() == dict.fromkeys(score.METRICS, 1.0)


def test_a_wrong_but_plausible_answer_scores_lower_than_the_right_one():
    right = score.score(["ISC-L:IV.2.d"], FIVE_SECONDS, gold())
    plausible = score.score(["ISC-L:IV.2.d", "F1-B:1.8.6"], TEN_SECONDS, gold())
    assert sum(plausible.as_dict().values()) < sum(right.as_dict().values())


def test_mean_of_no_answers_is_none_not_zero():
    assert score.mean([]) == dict.fromkeys(score.METRICS, None)


def test_paired_bootstrap_of_the_same_answers_is_zero():
    result = score.paired_bootstrap([1, 0, 1, 1], [1, 0, 1, 1])
    assert (result["difference"], result["low"], result["high"]) == (0, 0, 0)


def test_paired_bootstrap_of_always_better_is_one_everywhere():
    result = score.paired_bootstrap([1.0] * 20, [0.0] * 20)
    assert (result["difference"], result["low"], result["high"], result["questions"]) == (1, 1, 1, 20)


def test_paired_bootstrap_interval_holds_the_difference_and_is_repeatable():
    a = [1, 1, 0, 1, 0, 1, 1, 0, 1, 1] * 5
    b = [1, 0, 0, 1, 0, 0, 1, 0, 1, 0] * 5
    first = score.paired_bootstrap(a, b)
    assert first["low"] <= first["difference"] <= first["high"]
    assert first["low"] > 0  # 15 of 50 better and none worse: clearly above zero
    assert score.paired_bootstrap(a, b) == first  # a fixed seed


def test_paired_bootstrap_needs_pairs():
    with pytest.raises(ValueError):
        score.paired_bootstrap([1, 0], [1])
