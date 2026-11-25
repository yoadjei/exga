"""the exga command line (spec 7.10).

each command loads settings, does one job through the library and writes its results to
files. commands exit with 0 on success, 2 on a configuration error and 3 when the model
budget is spent.
"""

import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from exga.errors import BudgetExceededError, ConfigError
from exga.extract import extract_all, load_prompts, parse_failure_rate
from exga.fields import load_fields
from exga.gold import GOLD_COLUMNS, agreement, load_gold
from exga.llm.cache import CachedLLMClient
from exga.llm.hosted import HostedLLMClient
from exga.messages import percent
from exga.papers import load_folder
from exga.records import save_jsonl
from exga.settings import Settings, load_settings
from exga.splits import double_annotation_sample

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Extract fields from papers with an LLM and accept values under a certified error bound.",
)

EXIT_CONFIG = 2
EXIT_BUDGET = 3
APP_MAIN = Path(__file__).parent / "app" / "main.py"


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
    save_jsonl(items, out / "samples.jsonl")
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


@app.command("annotation-sheet")
def annotation_sheet(
    papers: Annotated[Path, typer.Option(help="Folder of the PDFs to annotate.")],
    fields: Annotated[Path, typer.Option(help="Field list (YAML).")],
    out: Annotated[Path, typer.Option(help="Folder for gold_template.csv and the plan.")],
    seed: Annotated[int, typer.Option(help="Seed for the double-annotation sample.")] = 0,
    env_file: Annotated[Path | None, typer.Option(help="Settings file (.env format).")] = None,
) -> None:
    """Write a blank gold file and the papers a second person should label (spec 10.2)."""
    try:
        settings = load_settings(env_file)
        specs = load_fields(fields)
        documents, skipped = load_folder(papers, settings.document)
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    for file in skipped:
        typer.echo(f"skipped {file.filename}: {file.reason}", err=True)
    double = double_annotation_sample(
        (document.paper_id for document in documents), seed, settings.splits
    )
    out.mkdir(parents=True, exist_ok=True)
    with (out / "gold_template.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([*GOLD_COLUMNS, "file", "double_annotate"])
        for document in documents:
            for spec in specs:
                flag = "yes" if document.paper_id in double else ""
                writer.writerow([document.paper_id, spec.name, "", document.filename, flag])
    typer.echo(
        f"Wrote {len(documents) * len(specs)} rows for {len(documents)} papers; "
        f"{len(double)} papers (seed {seed}) are marked for a second annotator. "
        'Write "NR" where a paper does not report a field.'
    )


@app.command("check-gold")
def check_gold_file(
    gold: Annotated[Path, typer.Option(help="Gold file (CSV) to validate.")],
    fields: Annotated[Path, typer.Option(help="Field list (YAML).")],
    second: Annotated[
        Path | None, typer.Option(help="A second annotator's gold file, to measure agreement.")
    ] = None,
    env_file: Annotated[Path | None, typer.Option(help="Settings file (.env format).")] = None,
) -> None:
    """Validate a gold file and report per-field counts and, given two, agreement."""
    try:
        settings = load_settings(env_file)
        specs = load_fields(fields)
        values = load_gold(gold, specs)
        other = load_gold(second, specs) if second is not None else None
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    papers = {paper_id for paper_id, _ in values}
    typer.echo(f"{gold.name} is valid: {len(values)} values for {len(papers)} papers.")
    for spec in specs:
        labelled = [value for (_, field), value in values.items() if field == spec.name]
        not_reported = sum(value is None for value in labelled)
        typer.echo(f"  {spec.name}: {len(labelled)} values, {not_reported} not reported")
    if other is None:
        return
    typer.echo(f"Agreement with {second.name if second else ''} on papers both labelled:")
    for result in agreement(values, other, specs, settings.matching):
        rate = "no shared items" if result.rate is None else percent(result.rate)
        typer.echo(f"  {result.field}: {rate} ({result.agreed} of {result.compared})")


@app.command("app")
def open_app(
    env_file: Annotated[Path | None, typer.Option(help="Settings file (.env format).")] = None,
) -> None:
    """Open the exga app in the browser; stop it with Ctrl+C."""
    try:
        load_settings(env_file)
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    # privacy (spec 0A.5): Streamlit sends usage statistics, listens on every network
    # interface and looks up the machine's public address unless told otherwise; on
    # localhost only this computer reaches the papers, and no outside service is contacted
    args = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_MAIN),
        "--browser.gatherUsageStats=false",
        "--server.address=localhost",
        # no Deploy button, which invites publishing the app, papers included, to a cloud
        "--client.toolbarMode=minimal",
        # on a computer that never ran Streamlit, it would stop and ask for an email address
        "--server.showEmailPrompt=false",
        # a neutral accent (white text on it: 5.2:1), so "Accepted" filter chips are not red
        "--theme.primaryColor=#2563eb",
    ]
    if env_file is not None:
        args += ["--", "--env-file", str(env_file)]
    try:
        code = subprocess.call(args)
    except KeyboardInterrupt:
        code = 0
    raise typer.Exit(code)
