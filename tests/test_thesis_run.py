"""experiments/thesis.py end to end (ADR 0013): every table and figure whose results exist.

the simulation results are the committed, real ones; the experiment and study results here are
invented for the test and are not results.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from exga.evaluate import LabelledItem
from exga.experiment import ExperimentConfig, evaluate, write_tables
from exga.schemas import Signals
from exga.study import (
    Accuracy,
    Assignment,
    ParticipantResult,
    Responses,
    Session,
    summary_rows,
    trust_rows,
)
from exga.tables import write_rows

REPOSITORY = Path(__file__).parents[1]
EXPORT = REPOSITORY / "experiments" / "thesis.py"


def run_export(*args: object) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("EXGA_")}
    return subprocess.run(
        [sys.executable, str(EXPORT), *map(str, args)],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def write_config(tmp_path: Path) -> tuple[Path, ExperimentConfig]:
    content = {
        "name": "e2e",
        "models": [{"name": "mock"}],
        "alphas": [0.1, 0.2],
        "repetitions": 2,
        "bootstrap": 20,
        "audit_batch": 20,
        "variants": {"combined": {}},
        "runs": str(tmp_path / "runs"),
        "results": str(tmp_path / "results"),
    }
    path = tmp_path / "e2e.yaml"
    path.write_text(json.dumps(content), encoding="utf-8")  # JSON is valid YAML
    return path, ExperimentConfig.model_validate(content)


def labelled_items(papers: int) -> list[LabelledItem]:
    """two fields per paper; one paper in five is wrong in both, with low agreement."""
    return [
        LabelledItem(
            paper_id=f"{index:064x}",
            field=field,
            group="numeric",
            signals=Signals(
                agreement=0.4 if index % 5 == 0 else 0.9 + index % 10 / 100,
                logprob=0.8,
                source_match=0.5 if index % 5 == 0 else 1.0,
            ),
            wrong=index % 5 == 0,
        )
        for index in range(papers)
        for field in ("n", "events")
    ]


def write_study(folder: Path) -> None:
    results = [
        ParticipantResult(
            assignment=Assignment(
                f"P0{number}", first="manual" if number % 2 else "tool", first_set="A"
            ),
            manual=Session(20.0 + number, Accuracy(items=18, correct=15, unanswered=1)),
            tool=Session(10.0 + number, Accuracy(items=18, correct=17, unanswered=0)),
            corrected=3,
            responses=Responses("student", "some", sus=(4, 2) * 5, trust=(4, 4, 3, 5)),
        )
        for number in range(1, 5)
    ]
    write_rows([result.row() for result in results], folder / "participants.csv")
    write_rows(summary_rows(results), folder / "summary.csv")
    write_rows(trust_rows(results), folder / "trust.csv")


def test_the_export_writes_every_table_and_figure_whose_results_exist(tmp_path: Path) -> None:
    config_path, config = write_config(tmp_path)
    write_tables(evaluate(config, {"mock": labelled_items(60)}), config.results_folder() / "tables")
    write_study(tmp_path / "study")
    out = tmp_path / "thesis"

    result = run_export(
        "--config", config_path, "--results", REPOSITORY / "results", "--study",
        tmp_path / "study", "--out", out,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr
    names = [
        "audit_simulation",
        "calibration_sizes",
        "e2e_baselines",
        "e2e_fields_mock",
        "e2e_results",
        "guarantee_simulation",
        "trust",
        "user_study",
    ]
    assert sorted(path.name for path in (out / "tables").iterdir()) == sorted(
        f"{name}.{extension}" for name in names for extension in ("csv", "tex")
    )
    assert (
        (out / "tables" / "e2e_results.tex")
        .read_text(encoding="utf-8")
        .startswith(r"\begin{table}")
    )
    figures = {path.relative_to(out / "figures").as_posix() for path in out.rglob("*.pdf")}
    assert figures == {
        "guarantee_validity.pdf",
        "study_times.pdf",
        "e2e/acceptance_vs_alpha.pdf",
        "e2e/realised_vs_target_error.pdf",
        "e2e/updating_mock.pdf",
    }
    assert "skipped" not in result.stdout


def test_missing_results_are_named_and_never_filled_in(tmp_path: Path) -> None:
    config_path, _ = write_config(tmp_path)
    out = tmp_path / "thesis"

    result = run_export(
        "--config", config_path, "--results", tmp_path / "none", "--study",
        tmp_path / "no-study", "--out", out,
    )  # fmt: skip

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (out / "tables").iterdir()) == [
        "calibration_sizes.csv",
        "calibration_sizes.tex",
    ]
    skipped = [line for line in result.stdout.splitlines() if line.startswith("skipped")]
    assert len(skipped) == 4
    assert any("make verify-guarantee" in line for line in skipped)
    assert any("make experiments" in line for line in skipped)
    assert any("study.py analyse" in line for line in skipped)
