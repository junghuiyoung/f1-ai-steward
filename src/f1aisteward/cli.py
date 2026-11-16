"""The command line: `uv run f1aisteward <command>`."""

from typing import Annotated

import typer

from . import config, manifest
from . import fetch as fetching

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

    typer.echo(f"Files are in {config.PDF_DIR.relative_to(config.ROOT)}/")
    if problems:
        typer.echo("\n".join(["", "Needs a look:"] + problems), err=True)
        raise typer.Exit(code=1)
