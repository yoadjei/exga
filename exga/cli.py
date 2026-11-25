"""the exga command line (spec 7.10).

each command loads settings, does one job through the library and writes its results to
files. commands exit with 0 on success, 2 on a configuration error and 3 when the model
budget is spent.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from exga.errors import BudgetExceededError, ConfigError
from exga.extract import extract_all, load_prompts, parse_failure_rate
from exga.fields import load_fields
from exga.llm.cache import CachedLLMClient
from exga.llm.hosted import HostedLLMClient
from exga.papers import load_folder
from exga.settings import Settings, load_settings

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Extract fields from papers with an LLM and accept values under a certified error bound.",
)

EXIT_CONFIG = 2
EXIT_BUDGET = 3


def build_client(settings: Settings) -> HostedLLMClient:
    """the model client for a run; tests replace this to serve canned responses."""
    return HostedLLMClient(settings.hosted)


@app.callback()
def _main() -> None:
    """exga command line."""


@app.command()
def extract(
    papers: Annotated[Path, typer.Option(help="Folder of PDFs, or of .md/.txt text files.")],
    fields: Annotated[Path, typer.Option(help="Field list (YAML).")],
    out: Annotated[Path, typer.Option(help="Folder for samples.jsonl and run.json.")],
    cache: Annotated[Path, typer.Option(help="Folder of cached model responses.")] = Path(
        ".exga/cache"
    ),
    env_file: Annotated[Path | None, typer.Option(help="Settings file (.env format).")] = None,
) -> None:
    """Ask the model for every field of every paper and save its parsed answers."""
    try:
        settings = load_settings(env_file)
        specs = load_fields(fields)
        prompts = load_prompts(settings.extraction.prompt_version)
        documents, skipped = load_folder(papers, settings.document)
        client = build_client(settings)
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    for file in skipped:
        typer.echo(f"skipped {file.filename}: {file.reason}", err=True)
    typer.echo(
        f"Paper text is sent to {settings.hosted.base_url} for model {settings.hosted.model}."
    )
    cached = CachedLLMClient(client, cache)
    started = datetime.now(UTC)
    with client:
        try:
            items = extract_all(documents, specs, cached, prompts, settings)
        except BudgetExceededError as exc:
            typer.echo(f"stopped: {exc}. Rerun to continue; answers so far are cached.", err=True)
            raise typer.Exit(EXIT_BUDGET) from exc
    out.mkdir(parents=True, exist_ok=True)
    with (out / "samples.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(item.model_dump_json() + "\n" for item in items)
    failure_rate = parse_failure_rate(items)
    summary = {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "model_id": cached.model_id,
        "prompt_version": prompts.version,
        "papers": len(documents),
        "skipped": [{"file": file.filename, "reason": file.reason} for file in skipped],
        "fields": [spec.name for spec in specs],
        "items": len(items),
        "items_without_answers": sum(item.error is not None for item in items),
        "parse_failure_rate": failure_rate,
        "requests_sent": cached.misses,
        "requests_from_cache": cached.hits,
        "usage": client.meter.summary(),
    }
    (out / "run.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _report(summary, failure_rate)


def _report(summary: dict[str, object], failure_rate: float | None) -> None:
    typer.echo(f"Extracted {summary['items']} items from {summary['papers']} papers.")
    if failure_rate is not None:
        typer.echo(f"Answers unusable after repair: {failure_rate:.1%}.")
    typer.echo(
        f"Requests sent: {summary['requests_sent']}; "
        f"answered from cache: {summary['requests_from_cache']}."
    )
    usage = summary["usage"]
    if isinstance(usage, dict) and usage.get("cost_usd") is not None:
        typer.echo(f"Cost: {usage['cost_usd']:.4f} USD.")
