"""The local web app: one static page and a small JSON API, served by FastAPI.

    GET  /                          the page, app/static/index.html
    GET  /api/events                race weekends, the rules in force at each, its real incidents
    POST /api/ask                   answer an incident with `answer.answer`, the same path `ask` prints
    GET  /api/decisions/{id}.png    a stewards' document as one image (made once, kept in .cache/pages/)
    GET  /api/decisions/{id}.pdf    the PDF itself, from .cache/pdf/

How a page and a server talk: the browser loads the page once; when you press "Ask", the
page's JavaScript sends the incident as JSON to /api/ask and draws the JSON that comes
back. Nothing is rendered on the server except the document images.

For a real incident the stewards' decision comes back in the same reply, under
`stewards`. It never reaches the prompt: search reads events before the incident's own
only, and the page draws the answer first.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import answer as answering
from .. import config, manifest
from ..fetch import pdf_path
from ..parse import labels
from ..search import DecisionSearch, RuleSearch
from . import pages, view

STATIC = Path(__file__).parent / "static"


@dataclass
class Steward:
    """Everything a question needs, loaded once when the server starts."""

    records: list[dict]
    decision_search: DecisionSearch
    rule_search: RuleSearch
    events: list[dict]
    model: str = config.ANSWER_MODEL
    effort: str = config.REASONING_EFFORT
    by_id: dict[str, dict] = field(init=False)
    by_slug: dict[str, dict] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {r["id"]: r for r in self.records}
        self.by_slug = {e["slug"]: e for e in self.events}


def load(model: str = config.ANSWER_MODEL, effort: str = config.REASONING_EFFORT) -> Steward:
    """The parsed documents, both indexes and the embedding model, as `ask` uses them."""
    from .. import index
    from ..parse import rules

    if not (config.PARSED_DECISIONS.exists() and config.PARSED_RULES.exists()):
        raise SystemExit("No parsed documents yet. Run `f1aisteward fetch`, then `build --decisions --rules --index`.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Put it in the .env file in the project folder.")
    embeddings = index.RememberedQuestions(index.openai_embeddings())
    records = index.load_decisions()
    articles = rules.load()
    decision_search = DecisionSearch(records, index.open_vector_store(embeddings))
    rule_search = RuleSearch(
        articles,
        manifest.load(config.REGULATIONS_MANIFEST),
        index.open_vector_store(embeddings, collection=config.RULES_COLLECTION),
    )
    return Steward(records, decision_search, rule_search, manifest.load()["events"], model, effort)


class Incident(BaseModel):
    text: str
    session: str | None = None
    event: str | None = None  # a slug; None: after the latest weekend, every decision and the latest rules
    decision: str | None = None  # the id of the real incident it was picked from, if its text is unchanged


# ---------------------------------------------------------------- what the replies hold


def incident_question(incident: Incident) -> str:
    """The question in the form the decisions were indexed in: '<session>. <what happened>'."""
    text = " ".join(incident.text.split())
    return f"{incident.session}. {text}" if incident.session else text


def _decision_view(record: dict, events: dict[str, dict]) -> dict:
    return {
        "id": record["id"],
        "event": view.event_short(events[record["event"]]["name"]),
        "session": record["session"],
        "number": record["number"],
        "fact": record["fact"],
        "articles": [view.article_label(a) for a in record["articles"]],
        "outcome": view.penalty_text(record["penalty"]),
        "url": record["url"],
    }


def _article_view(article_id: str, shown: list[dict]) -> dict:
    """An article of the answer with the name and opening words of the shown article that holds it."""
    holder = next((a for a in shown if answering.related(article_id, a["id"])), None)
    return {
        "id": article_id,
        "label": view.article_label(article_id),
        "title": view.heading_name(holder["headings"][-1]) if holder and holder["headings"] else "",
        "text": " ".join(holder["text"].split())[:400] if holder else "",
    }


def events_view(steward: Steward) -> dict:
    """The race weekends for the drop-down, newest first, each with the real incidents to pick from."""
    rule_search = steward.rule_search
    issues = {i["id"]: i for i in rule_search.regulations["issues"]}
    out = []
    for event in steward.events:
        incidents = [
            {
                "id": r["id"],
                "number": r["number"],
                "session": r["session"],
                "title": next((d["subject"] for d in event["docs"] if d["number"] == r["number"]), r["fact"]),
                "fact": r["fact"],
                "outcome": view.penalty_text(r["penalty"]),
            }
            for r in steward.records
            if r["event"] == event["slug"] and r["layout"] == "single_car" and r["articles"]
        ]
        out.append(
            {
                "slug": event["slug"],
                "name": view.event_short(event["name"]),
                "date": event["date"],
                "round": event["round"],
                "split": labels.split_for(event["date"]),
                "weekends_before": event["round"] - 1,
                "decisions_before": sum(r["round"] < event["round"] for r in steward.records),
                "rules": [view.issue_name(issues[i]) for i in rule_search.issues_on(event["date"])],
                "incidents": incidents,
            }
        )
    latest = {
        "slug": None,
        "name": f"After the {view.event_short(steward.events[-1]['name'])}",
        "weekends_before": len(steward.events),
        "decisions_before": len(steward.records),
        "rules": [view.issue_name(issues[i]) for i in rule_search.issues_on(None)],
        "incidents": [],
    }
    return {"events": [latest] + out[::-1], "model": steward.model, "default": steward.events[-1]["slug"]}


def ask_view(steward: Steward, incident: Incident) -> dict:
    """Answer an incident and say everything the screen shows about it."""
    if not incident.text.strip():
        raise HTTPException(400, "Describe what happened first.")
    event = steward.by_slug.get(incident.event) if incident.event else None
    if incident.event and event is None:
        raise HTTPException(404, f"No race weekend {incident.event!r}.")
    question = incident_question(incident)
    result = answering.answer(
        question,
        steward.decision_search,
        steward.rule_search,
        event["date"] if event else None,
        event["round"] if event else None,
        model=steward.model,
        effort=steward.effort,
    )
    events = steward.by_slug
    issues = {i["id"]: i for i in steward.rule_search.regulations["issues"]}
    reply = result.reply
    out: dict = {
        "status": reply.status,
        "question": question,
        "shown": {
            "decisions": len(result.decisions),
            "articles": len(result.articles),
            "rules": [view.issue_name(issues[i]) for i in steward.rule_search.issues_on(event["date"] if event else None)],
        },
        "meta": {
            "model": reply.model,
            "effort": steward.effort,
            "search_seconds": round(result.search_seconds, 1),
            "model_seconds": round(reply.seconds, 1),
            "cost": reply.cost,
            "input_tokens": reply.usage.input_tokens,
            "output_tokens": reply.usage.output_tokens,
        },
        "answer": None,
        "similar": None,
        "stewards": None,
    }
    if reply.status != "ok":
        out["message"] = answering._NO_ANSWER[reply.status]
        return out

    a, checked, counted = reply.parsed, result.check, result.outcomes
    penalty = {"type": a.penalty_type, "value": a.penalty_value, "unit": a.penalty_unit}
    out["answer"] = {
        "outcome": view.penalty_text(penalty),
        "penalty": penalty,
        "basis": view.basis(question, checked.articles, counted.matching),
        "articles": [_article_view(x, result.articles) for x in checked.articles],
        "rationale": a.rationale,
        "precedents": [_decision_view(steward.by_id[i], events) for i in checked.decisions],
        "left_out": [f"{x} is not among the articles shown" for x in checked.unknown_articles]
        + [f"{x} is not among the decisions shown" for x in checked.unknown_decisions],
    }
    names = {answering.penalty_label(d["penalty"]): view.penalty_text(d["penalty"]) for d in counted.matching}
    out["similar"] = {
        "articles": [view.article_label(x) for x in counted.articles],
        "looked_at": counted.looked_at,
        "total": len(counted.matching),
        "counts": [[names[label], n] for label, n in counted.counts],
        "list": [_decision_view(d, events) for d in counted.matching],
    }
    record = steward.by_id.get(incident.decision) if incident.decision else None
    if record is not None and event is not None and record["event"] == event["slug"]:
        out["stewards"] = {
            **_decision_view(record, events),
            "infringement": record["infringement"],
            "decision": record["decision"],
            "reason": record["reason"],
            "has_document": pdf_path(record["event"], record["number"]).exists(),
            "verdict": view.compare(checked.articles, penalty, record),
        }
    return out


# ---------------------------------------------------------------- the app


def create_app(steward: Steward | None = None) -> FastAPI:
    """The app. Tests hand in a Steward with made-up documents; `serve` loads the real ones."""
    app = FastAPI(title="AI Steward", docs_url=None, redoc_url=None)
    state: dict[str, Steward] = {}

    def current() -> Steward:
        if "steward" not in state:
            state["steward"] = steward or load()
        return state["steward"]

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/events")
    def events() -> dict:
        return events_view(current())

    @app.post("/api/ask")
    def ask(incident: Incident) -> dict:
        return ask_view(current(), incident)

    @app.get("/api/decisions/{decision_id}.png")
    def image(decision_id: str) -> FileResponse:
        record = current().by_id.get(decision_id)
        path = pages.page_image(record) if record else None
        if path is None:
            raise HTTPException(404, "This document is not on this machine. Run `uv run f1aisteward fetch`.")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/decisions/{decision_id}.pdf")
    def pdf(decision_id: str) -> FileResponse:
        record = current().by_id.get(decision_id)
        path = pdf_path(record["event"], record["number"]) if record else None
        if path is None or not path.exists():
            raise HTTPException(404, "This document is not on this machine. Run `uv run f1aisteward fetch`.")
        return FileResponse(path, media_type="application/pdf")

    return app
