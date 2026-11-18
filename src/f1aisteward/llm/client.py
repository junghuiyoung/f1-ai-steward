"""The one place a chat model is called (ADR-002).

`ask` sends messages to the model and asks for the answer in a fixed shape. This is
structured output: the request carries a JSON schema made from a Pydantic class, the
model has to reply with JSON that fits it, and LangChain turns that JSON back into an
instance of the class. Whatever happens, `ask` returns a `Reply`:

    status    "ok", or why there is no answer: "refused", "truncated", "unparsed", "timeout"
    parsed    the answer, an instance of the schema; None unless the status is "ok"
    usage     tokens in and out, read from the model's raw response
    seconds   how long the call took
    cost      in USD, from the token counts and the price table in config.py

A refusal, an answer cut off at the token limit and a timeout are kept apart from a
wrong answer. The answer evaluation (step 5) counts them instead of scoring them.
"""

from dataclasses import dataclass, field
from time import perf_counter

from langchain_core.exceptions import ModelRefusalError, ModelTimeoutError
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from .. import config


@dataclass
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0  # part of input_tokens: read from OpenAI's prompt cache, at a lower price
    output_tokens: int = 0
    reasoning_tokens: int = 0  # part of output_tokens: the model's hidden thinking, billed as output

    def cost(self, model: str) -> float:
        """USD. Reasoning tokens are not added again: output_tokens already holds them."""
        price = config.PRICES[model]
        fresh = self.input_tokens - self.cached_tokens
        dollars_per_million = (
            fresh * price["input"] + self.cached_tokens * price["cached"] + self.output_tokens * price["output"]
        )
        return dollars_per_million / 1_000_000


@dataclass
class Reply:
    status: str
    parsed: BaseModel | None
    model: str
    seconds: float
    usage: Usage = field(default_factory=Usage)
    error: str = ""  # what went wrong, when the status is not "ok"

    @property
    def cost(self) -> float:
        return self.usage.cost(self.model)


def chat_model(model: str = config.ANSWER_MODEL):
    """The chat model with this project's settings. It reads OPENAI_API_KEY from the environment.

    `use_responses_api`: OpenAI's newer API, the one its reasoning models are built for.
    `reasoning`: how much the model thinks before it answers. More costs more and takes longer.
    `max_tokens`: the cap on output tokens, thinking included (sent as max_output_tokens).
    """
    from langchain_openai import ChatOpenAI  # imported here: it takes a second to load

    return ChatOpenAI(
        model=model,
        use_responses_api=True,
        reasoning={"effort": config.REASONING_EFFORT},
        max_tokens=config.MAX_OUTPUT_TOKENS,
        timeout=config.MODEL_TIMEOUT_SECONDS,
    )


def ask(messages: list[BaseMessage], schema: type[BaseModel], model: str = config.ANSWER_MODEL) -> Reply:
    """One call to the model; the answer must fit `schema`.

    `strict=True` makes OpenAI hold the reply to the schema while it is being generated,
    instead of only checking it afterwards. `include_raw=True` keeps the raw message as
    well as the parsed answer: the token counts are only in the raw message, and a reply
    that cannot be parsed comes back as an error value instead of an exception.
    """
    structured = chat_model(model).with_structured_output(schema, strict=True, include_raw=True)
    start = perf_counter()
    try:
        result = structured.invoke(messages)
    except ModelTimeoutError as error:
        return Reply("timeout", None, model, perf_counter() - start, error=str(error))
    return read(result, model, perf_counter() - start)


def read(result: dict, model: str, seconds: float) -> Reply:
    """Turn what `with_structured_output(..., include_raw=True)` returned into a Reply.

    `result` has three keys: "raw" (the model's message), "parsed" (an instance of the
    schema, or None) and "parsing_error" (None, or why parsing failed).
    """
    raw: AIMessage = result["raw"]
    error = result["parsing_error"]
    if isinstance(error, ModelRefusalError):  # the model declined, or a content filter stopped it
        status = "refused"
    elif raw.response_metadata.get("status") == "incomplete":  # stopped at MAX_OUTPUT_TOKENS
        status = "truncated"
    elif result["parsed"] is None:
        status = "unparsed"
    else:
        status = "ok"
    parsed = result["parsed"] if status == "ok" else None
    return Reply(status, parsed, model, seconds, usage_of(raw), str(error or ""))


def usage_of(message: AIMessage) -> Usage:
    """The token counts LangChain copied from OpenAI's response into `usage_metadata`."""
    usage = message.usage_metadata or {}
    return Usage(
        input_tokens=usage.get("input_tokens", 0),
        cached_tokens=usage.get("input_token_details", {}).get("cache_read") or 0,
        output_tokens=usage.get("output_tokens", 0),
        reasoning_tokens=usage.get("output_token_details", {}).get("reasoning") or 0,
    )
