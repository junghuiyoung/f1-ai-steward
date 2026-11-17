"""The command line: `uv run f1aisteward <command>`."""

import os
from typing import Annotated

import typer
from dotenv import load_dotenv

from . import config, manifest
from . import fetch as fetching
from .parse import build as building

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """AI Steward: Formula 1 incidents, the rule in question and similar past decisions."""
    # Copy the lines of .env into this process's environment. The OpenAI library looks
    # for OPENAI_API_KEY there, so the key never appears in the code.
    load_dotenv(config.ROOT / ".env")


@app.command()
def fetch(
    event: Annotated[
        list[str] | None,
        typer.Option("--event", "-e", help="Event slug, e.g. sao-paulo. Repeat for several. Default: every event."),
    ] = None,
    rules: Annotated[
        bool,
        typer.Option("--rules", help="Download the rule documents in data/manifest/regulations.yaml instead."),
    ] = False,
) -> None:
    """Download stewards' decision PDFs, or rule documents, from fia.com into .cache/pdf/."""
    if rules:
        _fetch_rules()
        return
    data = manifest.load()
    by_slug = {e["slug"]: e for e in data["events"]}
    wanted = event or list(by_slug)
    unknown = [slug for slug in wanted if slug not in by_slug]
    if unknown:
        typer.echo(f"Unknown event: {', '.join(unknown)}\nAvailable: {', '.join(by_slug)}", err=True)
        raise typer.Exit(code=1)

    problems: list[str] = []
    rate_limited = False
    with fetching.make_client() as client:
        for slug in wanted:
            result = fetching.fetch_event(by_slug[slug], client)
            # Save after every event so an interrupted run keeps the hashes it recorded.
            manifest.save(data)
            typer.echo(
                f"{slug:<22} {len(by_slug[slug]['docs']):>3} decisions: "
                f"{result.downloaded} downloaded, {result.skipped} already here, "
                f"{len(result.changed)} changed, {len(result.failed)} failed"
            )
            problems += [f"changed  {item}" for item in result.changed]
            problems += [f"failed   {item}" for item in result.failed]
            if result.rate_limited:
                rate_limited = True
                break  # do not ask for the other events either

    typer.echo(f"Files are in {config.PDF_DIR.relative_to(config.ROOT)}/")
    if problems:
        typer.echo("\n".join(["", "Needs a look:"] + problems), err=True)
    if rate_limited:
        waiting = sum(
            not fetching.pdf_path(slug, doc["number"]).exists() for slug in wanted for doc in by_slug[slug]["docs"]
        )
        typer.echo(
            f"\nfia.com answered 429 (too many requests), so fetch stopped. {waiting} decisions are still "
            "to download.\nWait a while and run the same command again: it continues where it stopped.",
            err=True,
        )
    if problems or rate_limited:
        raise typer.Exit(code=1)


def _fetch_rules() -> None:
    data = manifest.load(config.REGULATIONS_MANIFEST)
    with fetching.make_client() as client:
        result = fetching.fetch_rules(data, client)
    manifest.save(data, config.REGULATIONS_MANIFEST)
    typer.echo(
        f"{len(data['issues'])} rule document issues: {result.downloaded} downloaded, "
        f"{result.skipped} already here, {len(result.changed)} changed, {len(result.failed)} failed\n"
        f"Files are in {config.RULES_PDF_DIR.relative_to(config.ROOT)}/"
    )
    problems = [f"changed  {item}" for item in result.changed] + [f"failed   {item}" for item in result.failed]
    if problems:
        typer.echo("\n".join(["", "Needs a look:"] + problems), err=True)
    if result.rate_limited:
        typer.echo("\nfia.com answered 429 (too many requests). Wait a while and run the same command again.", err=True)
    if problems or result.rate_limited:
        raise typer.Exit(code=1)


@app.command()
def build(
    decisions: Annotated[
        bool,
        typer.Option("--decisions", help="Parse the downloaded decision PDFs into fields and labels."),
    ] = False,
    rules: Annotated[
        bool,
        typer.Option("--rules", help="Parse the downloaded rule documents into articles."),
    ] = False,
    index: Annotated[
        bool,
        typer.Option("--index", help="Embed the parsed decisions and articles into the vector index. Calls OpenAI."),
    ] = False,
) -> None:
    """Turn downloaded documents into records the search can use."""
    if not (decisions or rules or index):
        typer.echo("Nothing to build. Use --decisions, --rules or --index.", err=True)
        raise typer.Exit(code=1)

    if decisions:
        report = building.build_decisions(manifest.load())
        building.write(report)
        typer.echo(building.summary(report))
        typer.echo(
            f"\nWrote {config.PARSED_DECISIONS.relative_to(config.ROOT)} (FIA text, stays on this machine)"
            f"\nWrote {config.DECISION_LABELS.relative_to(config.ROOT)} (no FIA text)"
        )
        if report.failed:
            raise typer.Exit(code=1)

    if rules:
        from .parse import rules as rule_parsing

        typer.echo("Reading the rule documents, about ten seconds per issue ...")
        try:
            articles, lines = rule_parsing.build_rules(manifest.load(config.REGULATIONS_MANIFEST))
        except FileNotFoundError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1)
        building.write_jsonl(config.PARSED_RULES, articles)
        typer.echo("\n".join(lines))
        typer.echo(
            f"\n{len(articles)} articles in {len(lines)} issues."
            f"\nWrote {config.PARSED_RULES.relative_to(config.ROOT)} (FIA text, stays on this machine)"
        )

    if index:
        from . import index as indexing  # imported here: these libraries take a second to load

        records = _parsed_decisions()
        _require_api_key()
        embeddings = indexing.openai_embeddings()
        store = indexing.build_vector_store(records, embeddings)
        typer.echo(
            f"Embedded {indexing.count(store)} decisions with {config.EMBEDDING_MODEL} into "
            f"{config.INDEX_DIR.relative_to(config.ROOT)}/ (FIA text, stays on this machine)"
        )
        if config.PARSED_RULES.exists():
            from .parse import rules as rule_parsing

            store = indexing.build_rule_store(rule_parsing.load(), embeddings)
            typer.echo(f"Embedded {indexing.count(store)} articles into the collection `{config.RULES_COLLECTION}`")
        else:
            typer.echo("No parsed rules yet, so no rule index. Run `f1aisteward build --rules` first.")


@app.command()
def search(
    question: Annotated[str, typer.Argument(help="What happened, in plain English.")],
    event: Annotated[
        str | None,
        typer.Option(
            "--event",
            "-e",
            help="e.g. sao-paulo. Decisions: only events before this one. Rules: the issues in force then. "
            "Default: everything / the latest issues.",
        ),
    ] = None,
    rules: Annotated[bool, typer.Option("--rules", help="Search the articles of the rules instead of decisions.")] = False,
    method: Annotated[str | None, typer.Option("--method", "-m", help="bm25, vector or hybrid.")] = None,
    k: Annotated[int | None, typer.Option("-k", help="How many results. Default: 5 decisions or 8 articles.")] = None,
) -> None:
    """Find past decisions similar to an incident, or the articles of the rules that fit it."""
    from .search import METHODS

    method = method or (config.RULES_SEARCH_METHOD if rules else config.SEARCH_METHOD)
    k = k or (config.TOP_K_RULES if rules else config.TOP_K)
    if method not in METHODS:
        typer.echo(f"Unknown method: {method}\nAvailable: {', '.join(METHODS)}", err=True)
        raise typer.Exit(code=1)
    events = {e["slug"]: e for e in manifest.load()["events"]}
    if event is not None and event not in events:
        typer.echo(f"Unknown event: {event}\nAvailable: {', '.join(events)}", err=True)
        raise typer.Exit(code=1)

    if rules:
        searcher = _rule_searcher([method])
        date = events[event]["date"] if event else None
        found = searcher.search(question, date=date, method=method, k=k)
        typer.echo(f"Issues in force{' on ' + date if date else ' now'}: {', '.join(searcher.issues_on(date))}\n")
        for rank, article in enumerate(found, start=1):
            first = " ".join(article["text"].split())[:160]
            typer.echo(f"{rank}. {article['id']}  ({article['issue']})\n   {' > '.join(article['headings'])}\n   {first} ...\n")
        return

    records = _parsed_decisions()
    searcher = _searcher(records, [method])
    results = searcher.search(question, before_round=events[event]["round"] if event else None, method=method, k=k)
    if not results:
        typer.echo(f"No decisions from before the {event} event: it is the first of the season.")
        return
    for rank, record in enumerate(results, start=1):
        penalty = record["penalty"]
        size = f" {penalty['value']} {penalty['unit']}" if penalty["value"] is not None else ""
        typer.echo(
            f"{rank}. {record['id']}  {record['session'] or 'no session'}\n"
            f"   {record['fact']}\n"
            f"   {', '.join(record['articles']) or 'no article'}  ->  {penalty['type']}{size}\n"
        )


@app.command("eval")
def evaluate(
    retrieval: Annotated[
        bool,
        typer.Option("--retrieval", help="Measure search: hit@5 and precision@5 of decisions, recall@8 of articles."),
    ] = False,
    split: Annotated[str, typer.Option("--split", help="dev or test. Tune on dev; report test.")] = "dev",
    method: Annotated[
        list[str] | None,
        typer.Option("--method", "-m", help="bm25, vector or hybrid. Repeat for several. Default: all three."),
    ] = None,
) -> None:
    """Measure how well the app does, with numbers."""
    if not retrieval:
        typer.echo("Nothing to evaluate. Use --retrieval.", err=True)
        raise typer.Exit(code=1)
    from .eval import retrieval as measuring
    from .search import METHODS

    methods = method or list(METHODS)
    unknown = [name for name in methods if name not in METHODS]
    if unknown or split not in ("dev", "test"):
        typer.echo(f"Use --split dev or test, and --method from: {', '.join(METHODS)}", err=True)
        raise typer.Exit(code=1)

    records = _parsed_decisions()
    question_sets = [
        ("Questions in the stewards' own words (session and Fact)", measuring.build_questions(records, split)),
        (
            "The same incidents reworded (data/questions/paraphrased.jsonl)",
            measuring.build_questions(records, split, measuring.load_reworded()),
        ),
    ]
    every_question = [question.text for _, (questions, _) in question_sets for question in questions]
    embeddings = None
    if methods != ["bm25"]:
        embeddings = _question_embeddings()
        embeddings.warm(every_question)  # one request for all questions instead of one per search
    searcher = _searcher(records, methods, embeddings)

    events = list(dict.fromkeys(q.event for _, (questions, _) in question_sets for q in questions))
    typer.echo(
        f"Search evaluation on the {split} events ({events[0]} to {events[-1]}).\n"
        "Each question is searched in the decisions of earlier events only.\n"
    )
    searches = 0
    for title, (questions, left_out) in question_sets:
        scores = [measuring.evaluate(searcher, questions, name) for name in methods]
        searches += len(questions) * len(methods)
        typer.echo(measuring.report(title, records, questions, left_out, scores) + "\n")
    typer.echo(f"Checked: none of the {searches} searches returned a decision from its own or a later event.\n")

    if not config.PARSED_RULES.exists():
        typer.echo("No parsed rules, so no rule search to measure. Run `f1aisteward build --rules` first.")
        return
    rule_searcher = _rule_searcher(methods, embeddings)
    typer.echo(
        "Rule search: the same questions, asked of the articles in force on each event's date.\n"
        "An article counts as found when the retrieved article holds it (B1.8.4 holds B1.8.4.b).\n"
    )
    searches = 0
    for title, (questions, _) in question_sets:
        reach = measuring.rule_reach(rule_searcher, questions)
        scores = [measuring.evaluate_rules(rule_searcher, questions, name) for name in methods]
        searches += len(questions) * len(methods)
        typer.echo(measuring.report_rules(title, questions, reach, scores) + "\n")
    typer.echo(f"Checked: all {searches} rule searches returned articles of the issues in force only.")


def _parsed_decisions() -> list[dict]:
    from . import index as indexing

    if not config.PARSED_DECISIONS.exists():
        typer.echo("No parsed decisions yet. Run `f1aisteward build --decisions` first.", err=True)
        raise typer.Exit(code=1)
    return indexing.load_decisions()


def _require_api_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        typer.echo("OPENAI_API_KEY is not set. Put it in the .env file in the project folder.", err=True)
        raise typer.Exit(code=1)


def _question_embeddings():
    """The embedding model, remembering every question it has embedded."""
    from . import index as indexing

    _require_api_key()
    return indexing.RememberedQuestions(indexing.openai_embeddings())


def _searcher(records: list[dict], methods: list[str], embeddings=None):
    """A DecisionSearch with the vector index attached only when a method needs it.

    BM25 alone needs no API key and no network.
    """
    from . import index as indexing
    from .search import DecisionSearch

    if methods == ["bm25"]:
        return DecisionSearch(records)
    store = indexing.open_vector_store(embeddings or _question_embeddings())
    _require_index(store, len(records), "decisions")
    return DecisionSearch(records, store)


def _rule_searcher(methods: list[str], embeddings=None):
    """A RuleSearch over the parsed articles, with the vector index when a method needs it."""
    from . import index as indexing
    from .parse import rules as rule_parsing
    from .search import RuleSearch

    if not config.PARSED_RULES.exists():
        typer.echo("No parsed rules yet. Run `f1aisteward fetch --rules` and `build --rules` first.", err=True)
        raise typer.Exit(code=1)
    articles = rule_parsing.load()
    regulations = manifest.load(config.REGULATIONS_MANIFEST)
    if methods == ["bm25"]:
        return RuleSearch(articles, regulations)
    store = indexing.open_vector_store(embeddings or _question_embeddings(), collection=config.RULES_COLLECTION)
    _require_index(store, len(articles), "articles")
    return RuleSearch(articles, regulations, store)


def _require_index(store, parsed: int, what: str) -> None:
    from . import index as indexing

    if indexing.count(store) != parsed:
        typer.echo(
            f"The vector index holds {indexing.count(store)} {what} but {parsed} are parsed. "
            "Run `f1aisteward build --index` first.",
            err=True,
        )
        raise typer.Exit(code=1)
