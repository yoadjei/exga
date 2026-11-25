"""export the thesis tables and figures from every result that exists (spec 15, ADR 0013).

    python experiments/thesis.py        (or: make thesis)

writes results/thesis/tables/<name>.tex and .csv (LaTeX that needs \\usepackage{booktabs,array},
and the same cells as CSV) and results/thesis/figures/<name>.pdf and .png, from:

- results/guarantee_simulation.csv and results/audit_simulation.csv (make verify-guarantee);
- each experiment config's results folder (make experiments); a config with several score
  variants gives the ablation table, any other the baselines table, a results and a field
  table per model, and the experiment figures;
- results/study/ (python study/study.py analyse);
- each config's dataset, for a table of its items per field (once per dataset).

a missing source is skipped and named; nothing is filled in. the calibration-size table is
computed and always written.
"""

import dataclasses
from pathlib import Path
from typing import Annotated

import figures
import typer

from exga import thesis
from exga.errors import ConfigError
from exga.experiment import Data, ExperimentConfig, load_config, load_items, read_tables
from exga.settings import Settings, load_settings
from exga.tables import read_rows, write_rows

CONFIGS = [Path("experiments/main.yaml"), Path("experiments/ablations.yaml"),
           Path("experiments/annotated.yaml")]  # fmt: skip
FORMATS = ("pdf", "png")
DATASETS = {"benchmark": "the benchmark", "annotated": "the annotated set"}
EXCLUSIONS = {
    "benchmark": "Comparisons whose data are only in figures or image tables are left out "
    "(ADR 0008); each paper gives one comparison per field, drawn at random."
}
EXIT_CONFIG = 2
app = typer.Typer(add_completion=False)


@app.command()
def export(
    config: Annotated[
        list[Path] | None, typer.Option(help="Experiment config; repeat for several.")
    ] = None,
    results: Annotated[Path, typer.Option(help="Folder of the simulation results.")] = Path(
        "results"
    ),
    study: Annotated[Path, typer.Option(help="Folder of the user-study results.")] = Path(
        "results/study"
    ),
    out: Annotated[Path, typer.Option(help="Folder for the thesis tables and figures.")] = Path(
        "results/thesis"
    ),
    env_file: Annotated[
        Path | None, typer.Option(help="Settings file (.env format), as given to run.py.")
    ] = None,
) -> None:
    """Write the thesis tables and figures from every result that exists."""
    written: list[Path] = []
    skipped: list[str] = []
    datasets: set[Data] = set()
    try:
        settings = load_settings(env_file)
        configs = [load_config(path) for path in config or CONFIGS]
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_CONFIG) from exc
    written += _table(thesis.calibration_sizes_table(), out)
    _simulations(results, out, written, skipped)
    for experiment in configs:
        if experiment.data not in datasets:
            datasets.add(experiment.data)
            _data(experiment, settings, out, written, skipped)
        _experiment(experiment, out, written, skipped)
    _study(study, out, written, skipped)
    typer.echo(f"Wrote {len(written)} files to {out}.")
    for reason in skipped:
        typer.echo(f"skipped {reason}")


def _simulations(results: Path, out: Path, written: list[Path], skipped: list[str]) -> None:
    guarantee = results / "guarantee_simulation.csv"
    if guarantee.is_file():
        rows = read_rows(guarantee)
        written += _table(thesis.guarantee_table(rows), out)
        written += figures.validity(rows, out / "figures", FORMATS)
    else:
        skipped.append(f"the guarantee simulation: no {guarantee}; run make verify-guarantee")
    audit = results / "audit_simulation.csv"
    if audit.is_file():
        written += _table(thesis.audit_table(read_rows(audit)), out)
    else:
        skipped.append(f"the audit simulation: no {audit}; run make verify-guarantee")


def _data(
    config: ExperimentConfig, settings: Settings, out: Path, written: list[Path], skipped: list[str]
) -> None:
    """the items of the config's dataset per field, named after the first config that uses it."""
    try:
        items = load_items(config, settings.document)
    except ConfigError as exc:
        skipped.append(f"the data of experiment {config.name}: {exc}")
        return
    table = thesis.data_table(
        [(item.document.paper_id, item.spec, item.gold) for item in items],
        name="data",
        dataset=DATASETS[config.data.kind],
        note=EXCLUSIONS.get(config.data.kind),
    )
    written += _table(table, out, prefix=config.name)


def _experiment(
    config: ExperimentConfig, out: Path, written: list[Path], skipped: list[str]
) -> None:
    folder = config.results_folder() / "tables"
    if not folder.is_dir():
        skipped.append(
            f"experiment {config.name}: no results in {folder.parent}; run make experiments"
        )
        return
    tables = read_tables(folder)
    variant = config.primary_variant
    if len(config.variants) > 1:
        written += _table(thesis.ablation_table(tables.by_group), out, prefix=config.name)
        return
    dataset = DATASETS[config.data.kind]
    written += _table(thesis.baselines_table(tables.baselines, variant), out, prefix=config.name)
    for model in config.models:
        for table in (
            thesis.main_table(tables.by_group, variant, model.name, dataset=dataset),
            thesis.fields_table(tables.by_field, variant, model.name),
        ):
            written += _table(table, out, prefix=config.name)
    written += figures.draw(tables, variant, out / "figures" / config.name, FORMATS)


def _study(study: Path, out: Path, written: list[Path], skipped: list[str]) -> None:
    files = {name: study / f"{name}.csv" for name in ("participants", "summary", "trust")}
    missing = [path for path in files.values() if not path.is_file()]
    if missing:
        skipped.append(f"the user study: no {missing[0]}; run python study/study.py analyse")
        return
    written += _table(thesis.study_table(read_rows(files["summary"])), out)
    written += _table(thesis.trust_table(read_rows(files["trust"])), out)
    written += figures.study_times(read_rows(files["participants"]), out / "figures", FORMATS)


def _table(table: thesis.ThesisTable, out: Path, prefix: str | None = None) -> list[Path]:
    """write a table as <name>.tex and <name>.csv; prefix names it after its experiment."""
    if prefix is not None:
        table = dataclasses.replace(table, name=f"{prefix}_{table.name}")
    folder = out / "tables"
    folder.mkdir(parents=True, exist_ok=True)
    latex = folder / f"{table.name}.tex"
    latex.write_text(table.latex(), encoding="utf-8")
    return [latex, write_rows(table.rows, folder / f"{table.name}.csv")]


if __name__ == "__main__":
    app()
