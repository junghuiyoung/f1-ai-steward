"""The command line: `uv run f1aisteward <command>`."""

from typing import Annotated

import typer

from . import config, manifest
from . import fetch as fetching
from .parse import build as building

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """AI Steward: Formula 1 incidents, the rule in question and similar past decisions."""


@app.command()
def fetch(
    event: Annotated[
        list[str] | None,
        typer.Option("--event", "-e", help="Event slug, e.g. sao-paulo. Repeat for several. Default: every event."),
    ] = None,
) -> None:
    """Download stewards' decision PDFs from fia.com into .cache/pdf/."""
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


@app.command()
def build(
    decisions: Annotated[
        bool,
        typer.Option("--decisions", help="Parse the downloaded decision PDFs into fields and labels."),
    ] = False,
) -> None:
    """Turn downloaded documents into records the search can use."""
    if not decisions:
        typer.echo("Nothing to build. Use --decisions.", err=True)
        raise typer.Exit(code=1)

    report = building.build_decisions(manifest.load())
    building.write(report)
    typer.echo(building.summary(report))
    typer.echo(
        f"\nWrote {config.PARSED_DECISIONS.relative_to(config.ROOT)} (FIA text, stays on this machine)"
        f"\nWrote {config.DECISION_LABELS.relative_to(config.ROOT)} (no FIA text)"
    )
    if report.failed:
        raise typer.Exit(code=1)
