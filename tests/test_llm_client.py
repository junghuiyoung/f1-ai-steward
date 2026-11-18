"""Reading the model's reply: status, token counts and cost. No network: the replies are built here."""

import pytest
from langchain_core.exceptions import ModelRefusalError, ModelTimeoutError, OutputParserException
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from f1aisteward.llm import client


class Small(BaseModel):
    word: str


def raw(status="completed", input_tokens=1200, cached=0, output_tokens=300, reasoning=200):
    """An AIMessage shaped like the ones ChatOpenAI returns from the Responses API."""
    return AIMessage(
        content="",
        response_metadata={"status": status},
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cached},
            "output_token_details": {"reasoning": reasoning},
        },
    )


def test_a_parsed_reply_is_ok_and_carries_its_token_counts():
    reply = client.read({"raw": raw(), "parsed": Small(word="yes"), "parsing_error": None}, "gpt-6-luna", 1.5)

    assert reply.status == "ok"
    assert reply.parsed == Small(word="yes")
    assert (reply.usage.input_tokens, reply.usage.output_tokens, reply.usage.reasoning_tokens) == (1200, 300, 200)
    assert reply.seconds == 1.5


@pytest.mark.parametrize(
    "result, status",
    [
        ({"raw": raw(), "parsed": None, "parsing_error": ModelRefusalError("no")}, "refused"),
        ({"raw": raw(status="incomplete"), "parsed": None, "parsing_error": OutputParserException("cut")}, "truncated"),
        ({"raw": raw(), "parsed": None, "parsing_error": OutputParserException("bad json")}, "unparsed"),
    ],
)
def test_no_answer_says_why_and_still_counts_the_tokens(result, status):
    reply = client.read(result, "gpt-6-luna", 2.0)

    assert reply.status == status
    assert reply.parsed is None
    assert reply.error
    assert reply.usage.input_tokens == 1200  # a failed call is still paid for


def test_cost_prices_cached_input_lower_and_does_not_count_reasoning_twice():
    # Luna: $0.10 per million fresh input tokens, $0.01 cached, $0.50 output.
    usage = client.Usage(input_tokens=1_000_000, cached_tokens=200_000, output_tokens=100_000, reasoning_tokens=80_000)

    assert usage.cost("gpt-6-luna") == pytest.approx(0.8 * 0.10 + 0.2 * 0.01 + 0.1 * 0.50)


def test_a_reply_without_usage_counts_zero():
    usage = client.usage_of(AIMessage(content=""))
    assert usage == client.Usage()


def test_a_timeout_is_a_status_not_a_crash(monkeypatch):
    class Slow:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            raise ModelTimeoutError("took too long")

    monkeypatch.setattr(client, "chat_model", lambda model: Slow())
    reply = client.ask([], Small)

    assert reply.status == "timeout"
    assert reply.parsed is None
    assert reply.cost == 0
