"""export the thesis tables and figures from every result that exists (spec 15, ADR 0013).

    python experiments/thesis.py        (or: make thesis)

writes results/thesis/tables/<name>.tex and .csv (booktabs LaTeX, and the same cells as CSV)
and results/thesis/figures/<name>.pdf and .png, from:

- results/guarantee_simulation.csv and results/audit_simulation.csv (make verify-guarantee);
- each experiment config's results folder (make experiments); a config with several score
  variants gives the ablation table, any other the results, baselines and field tables and
  the experiment figures;
- results/study/ (python study/study.py analyse).

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
from exga.experiment import ExperimentConfig, load_config, read_tables
from exga.tables import read_rows, write_rows

CONFIGS = [Path("experiments/main.yaml"), Path("experiments/ablations.yaml"),
           Path("experiments/annotated.yaml")]  # fmt: skip
FORMATS = ("pdf", "png")
DATASETS = {"benchmark": "the benchmark", "annotated": "the annotated set"}
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
) -> None:
    """Write the thesis tables and figures from every result that exists."""
    written: list[Path] = []
    skipped: list[str] = []
    written += _table(thesis.calibration_sizes_table(), out)
    _simulations(results, out, written, skipped)
    for path in config if config is not None else CONFIGS:
        try:
            _experiment(load_config(path), out, written, skipped)
        except ConfigError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(EXIT_CONFIG) from exc
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
    written += _table(
        thesis.main_table(tables.by_group, variant, name="results", dataset=dataset),
        out,
        prefix=config.name,
    )
    written += _table(thesis.baselines_table(tables.baselines, variant), out, prefix=config.name)
    for model in config.models:
        written += _table(
            thesis.fields_table(tables.by_field, variant, model.name), out, prefix=config.name
        )
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
