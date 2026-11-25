"""run the experiments (spec 11, ADR 0011).

    python experiments/run.py extract experiments/main.yaml    # asks each model; costs money
    python experiments/run.py evaluate experiments/main.yaml   # tables, figures, manifest

extract saves each model's samples under runs/<name>/<model>/ through a shared response cache,
so a rerun after an interruption sends only the missing requests. evaluate reads the samples
and writes results/<name>-<config hash>/ (manifest.json, tables/, figures/, and records/ for
the Calibrate page), sending nothing.
exit codes: 0 success, 2 configuration error, 3 budget spent.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import figures
import typer

from exga import experiment
from exga.errors import BudgetExceededError, ConfigError
from exga.llm.hosted import HostedLLMClient
from exga.manifest import build_manifest
from exga.messages import percent
from exga.records import save_records
from exga.settings import load_settings

REPOSITORY = Path(__file__).resolve().parents[1]
EXIT_CONFIG = 2
EXIT_BUDGET = 3
app = typer.Typer(no_args_is_help=True, add_completion=False)
ConfigPath = Annotated[Path, typer.Argument(help="Experiment config (YAML).")]
EnvFile = Annotated[Path | None, typer.Option(help="Settings file (.env format).")]


@app.command()
def extract(
    config_path: ConfigPath,
    model: Annotated[str | None, typer.Option(help="Only this model.")] = None,
    env_file: EnvFile = None,
) -> None:
    """Ask each model about every item of the dataset and save its answers."""
    try:
        config = experiment.load_config(config_path)
        settings = load_settings(env_file)
        items = experiment.load_items(config, settings.document)
        models = [spec for spec in config.models if model in (None, spec.name)]
        if not models:
            raise ConfigError(f"no model named {model} in {config_path}")
        for spec in models:
            hosted = spec.settings(settings.hosted)
            typer.echo(f"{spec.name}: paper text is sent to {hosted.base_url} for {hosted.model}.")
            with HostedLLMClient(hosted) as client:
                run = experiment.extract(
                    config,
                    spec,
                    items,
                    client,
                    settings.model_copy(update={"hosted": hosted}),
                    progress=_progress,
                )
                usage = client.meter.summary()
            rate = "n/a" if run.parse_failure_rate is None else percent(run.parse_failure_rate)
            typer.echo(
                f"{spec.name}: {run.items} items, {run.failed_requests} failed requests, "
                f"parse failures {rate}, {run.requests_sent} requests sent, "
                f"{run.requests_from_cache} from cache, usage {usage}"
            )
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    except BudgetExceededError as exc:
        typer.echo(f"stopped: {exc}. Rerun to continue; answers so far are cached.", err=True)
        raise typer.Exit(EXIT_BUDGET) from exc


@app.command()
def evaluate(config_path: ConfigPath, env_file: EnvFile = None) -> None:
    """Build the tables, figures and records files from saved answers, with a manifest."""
    try:
        config = experiment.load_config(config_path)
        settings = load_settings(env_file)
        items = experiment.load_items(config, settings.document)
        labelled = {
            spec.name: experiment.label(items, experiment.load_samples(config, spec), settings)
            for spec in config.models
        }
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    tables = experiment.evaluate(config, labelled, progress=typer.echo)
    folder = config.results_folder()
    experiment.write_tables(tables, folder / "tables")
    figures.draw(tables, config.primary_variant, folder / "figures")
    at = datetime.now(UTC)
    (folder / "records").mkdir(exist_ok=True)
    for name, rows in labelled.items():
        records = experiment.item_records(rows, settings.score, config.data.record_source, at)
        save_records(records, folder / "records" / f"{name}.jsonl")
    manifest = build_manifest(
        config=config.model_dump(mode="json"),
        settings=settings,
        inputs={
            **config.data.inputs(),
            **{f"samples/{spec.name}": config.samples_path(spec) for spec in config.models},
        },
        extra={
            "models": {spec.name: _run_summary(config, spec) for spec in config.models},
            "data": config.data.provenance(),
            "items": {name: len(rows) for name, rows in labelled.items()},
            "seeds": {
                "splits": [config.seed + r for r in range(config.repetitions)],
                "bootstrap": config.seed,
            },
        },
        repo=REPOSITORY,
        at=at,
    )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"results in {folder}")


def _run_summary(config: experiment.ExperimentConfig, spec: experiment.ModelConfig) -> object:
    path = config.samples_path(spec).parent / "run.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _progress(done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        typer.echo(f"  {done} of {total} items")


if __name__ == "__main__":
    app()
