"""The answer evaluation runner, with a stand-in model. No network and no FIA text."""

import json
import threading

import pytest
from search_data import RECORDS, REGULATIONS, RULE_ARTICLES, WordCountEmbeddings, decision

from f1aisteward import answer as answering
from f1aisteward import index
from f1aisteward.answer import Answer
from f1aisteward.eval import answers as asking
from f1aisteward.llm import client
from f1aisteward.search import DecisionSearch, RuleSearch

BY_ID = {r["id"]: r for r in RECORDS}


def searchers(directory, records, articles):
    embeddings = WordCountEmbeddings()
    decisions = DecisionSearch(records, index.build_vector_store(records, embeddings, directory))
    rules = RuleSearch(articles, REGULATIONS, index.build_rule_store(articles, embeddings, directory) if articles else None)
    return decisions, rules


class StandIn:
    """Answers every call the same way and remembers the prompts it was sent."""

    def __init__(self, status="ok"):
        self.status = status
        self.prompts = []
        self.lock = threading.Lock()

    def __call__(self, messages, schema, model, effort):
        with self.lock:
            self.prompts.append([m.content for m in messages])
        parsed = Answer(
            articles=["ISC-L:IV.2"],
            penalty_type="time_penalty",
            penalty_value=5,
            penalty_unit="s",
            rationale="Made up.",
            precedents_used=[],
        )
        if self.status != "ok":
            return client.Reply(self.status, None, model, 0.5, client.Usage(100, 0, 0, 0), error="stand-in")
        return client.Reply("ok", parsed, model, 0.5, client.Usage(1000, 0, 200, 100))


def prepared(directory, records=RECORDS, articles=RULE_ARTICLES):
    """The made-up questions with their searches done. The vector index goes in `directory`."""
    questions, _ = asking.questions_for(records, "test")
    decisions, rules = searchers(directory, records, articles)
    return asking.prepare(questions, {r["id"]: r for r in records}, decisions, rules)


# ---------------------------------------------------------------- questions


def test_a_question_that_names_a_penalty_is_left_out():
    records = RECORDS + [decision(3, 9, "Car 2 was given a 5 second time penalty for the second time.")]
    questions, left_out = asking.questions_for(records, "test")
    assert left_out["the question names a penalty"] == 1
    assert all("time penalty" not in q.text for q in questions)


def test_a_number_of_seconds_alone_is_not_a_penalty():
    assert not asking.PENALTY_IN_TEXT.search("Race. Car 55 left equipment on the grid after the 15 second signal.")


def test_a_sample_is_the_same_every_time():
    first, _ = asking.questions_for(RECORDS, "test", sample=2)
    again, _ = asking.questions_for(RECORDS, "test", sample=2)
    assert [q.ids for q in first] == [q.ids for q in again] and len(first) == 2


# ---------------------------------------------------------------- what each configuration is shown


def test_each_configuration_is_shown_only_its_part_of_the_search(tmp_path):
    for item in prepared(tmp_path):
        assert item.shown["none"] == ([], [])
        rule_articles, no_decisions = item.shown["rules"]
        assert no_decisions == [] and len(rule_articles) <= 8
        articles, decisions = item.shown["rules_and_decisions"]
        assert all(d["round"] < item.question.round for d in decisions)
        assert [a["key"] for a in articles[: len(rule_articles)]] == [a["key"] for a in rule_articles]


def test_with_search_switched_off_every_configuration_sends_the_no_search_prompt(tmp_path):
    # Searchers with nothing to find: no decisions of earlier events, no rule articles.
    items = prepared(tmp_path / "index", records=[r for r in RECORDS if r["round"] == 1], articles=[])
    model = StandIn()
    asking.run(items, tmp_path / "run", "gpt-6-luna", ask=model)

    assert len(model.prompts) == 3 * len(items)
    no_search = {tuple(m.content for m in answering.messages(i.question.text, [], [])) for i in items}
    assert {tuple(p) for p in model.prompts} == no_search


# ---------------------------------------------------------------- the run


def test_results_hold_ids_and_labels_but_never_the_question_text(tmp_path):
    items = prepared(tmp_path / "index")
    asking.run(items, tmp_path, "gpt-6-luna", ask=StandIn())

    text = (tmp_path / "results.jsonl").read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    assert len(rows) == 3 * len(items)
    assert all(item.question.text not in text for item in items)  # the Fact is FIA text
    row = rows[0]
    assert row["answer"]["penalty"] == {"type": "time_penalty", "value": 5, "unit": "s"}
    assert row["usage"]["input_tokens"] == 1000 and row["cost"] > 0
    # The prompt goes to the transcripts, which stay on this machine.
    transcript = json.loads((tmp_path / "transcripts" / f"{row['question']}__{row['config']}.json").read_text())
    assert transcript["messages"][-1]["content"].endswith(BY_ID[row["question"]]["fact"])


def test_the_citation_check_is_recorded_with_the_answer(tmp_path):
    asking.run(prepared(tmp_path / "index"), tmp_path, "gpt-6-luna", ask=StandIn())
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text().splitlines()]
    none = [r for r in rows if r["config"] == "none"]
    full = [r for r in rows if r["config"] == "rules_and_decisions"]
    assert all(not r["check"]["passed"] for r in none)  # shown nothing, so nothing it cites was shown
    assert all(r["check"]["passed"] for r in full)  # ISC-L:IV.2 is among the articles shown


def test_a_resumed_run_asks_only_what_is_missing_or_hit_a_rate_limit(tmp_path):
    items = prepared(tmp_path / "index")
    asking.run(items[:1], tmp_path, "gpt-6-luna", ask=StandIn())
    asking.run(items[1:2], tmp_path, "gpt-6-luna", ask=StandIn(status="rate_limited"))
    asking.run(items[2:3], tmp_path, "gpt-6-luna", ask=StandIn(status="truncated"))

    model = StandIn()
    written = asking.run(items, tmp_path, "gpt-6-luna", ask=model)
    # Item 0 is done, item 2 truncated (a model outcome, kept). Item 1 is asked again, and the rest.
    assert len(written) == 3 * (len(items) - 2)
    rows = asking.latest_rows(asking.read_rows(tmp_path / "results.jsonl"))
    assert rows[(items[1].question.ids[0], "none")]["status"] == "ok"
    assert rows[(items[2].question.ids[0], "none")]["status"] == "truncated"


def test_meta_keeps_the_first_start(tmp_path):
    asking.write_meta(tmp_path, model="gpt-6-luna")
    first = json.loads((tmp_path / "run.json").read_text())
    asking.write_meta(tmp_path, model="gpt-6-luna")
    again = json.loads((tmp_path / "run.json").read_text())
    assert again["started"] == first["started"] and again["model"] == "gpt-6-luna"


def test_a_run_cannot_be_resumed_with_another_prompt(tmp_path):
    asking.write_meta(tmp_path, model="gpt-6-luna", prompt="aaa")
    with pytest.raises(ValueError, match="prompt"):
        asking.write_meta(tmp_path, model="gpt-6-luna", prompt="bbb")


def test_a_run_cannot_be_resumed_on_another_split(tmp_path):
    asking.write_meta(tmp_path, model="gpt-6-luna", split="dev", questions=87, configs=["rules_and_decisions"])
    with pytest.raises(ValueError, match="split"):
        asking.write_meta(tmp_path, model="gpt-6-luna", split="test", questions=144, configs=["none"])


def test_more_configurations_on_the_same_questions_are_added(tmp_path):
    asking.write_meta(tmp_path, model="gpt-6-luna", split="dev", configs=["rules_and_decisions"])
    asking.write_meta(tmp_path, model="gpt-6-luna", split="dev", configs=["none", "rules_and_decisions"])
    assert json.loads((tmp_path / "run.json").read_text())["configs"] == ["rules_and_decisions", "none"]


def test_a_bug_in_one_call_stops_the_run_before_the_rest_are_paid_for(tmp_path):
    items = prepared(tmp_path / "index")
    calls = []

    def broken(messages, schema, model, effort):
        calls.append(1)
        return client.Reply("ok", None, model, 0.1)  # "ok" with no answer: row_for fails on it

    with pytest.raises(AttributeError):
        asking.run(items, tmp_path / "run", "gpt-6-luna", ask=broken, workers=1)
    assert len(calls) < 3 * len(items)
