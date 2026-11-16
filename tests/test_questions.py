"""The reworded questions in data/questions/ point at real decisions and give no answer away.

Both files read here are in the repository and hold no FIA text.
"""

import json
import re

from f1aisteward import config
from f1aisteward.parse import labels

QUESTIONS = config.ROOT / "data" / "questions" / "paraphrased.jsonl"
PENALTY_WORDS = re.compile(r"penalt|reprimand|\bfined?\b|\bwarning|disqualif|no further action", re.IGNORECASE)


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_question_belongs_to_one_labelled_decision():
    questions = read(QUESTIONS)
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert set(ids) <= {label["id"] for label in read(config.DECISION_LABELS)}


def test_no_question_names_an_article_or_a_penalty():
    for q in read(QUESTIONS):
        assert q["question"].strip()
        assert labels.normalise_articles(q["question"]) == [], q["id"]
        assert "Article" not in q["question"], q["id"]
        assert not PENALTY_WORDS.search(q["question"]), q["id"]
