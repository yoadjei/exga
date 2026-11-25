"""experiments/run.py end to end: a tiny benchmark in the downloaded layout, a mock model for
the extraction, then the real script for the evaluation (ADR 0011).

the numbers are not results; the test checks that the script writes every table, figure and
the manifest, and fails cleanly without a model.
"""

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from exga import experiment
from exga.benchmark import FIELDS
from exga.llm.mock import MockCall, MockLLMClient
from exga.settings import ExtractionSettings, Settings

REPOSITORY = Path(__file__).parents[1]
RUN = REPOSITORY / "experiments" / "run.py"
COLUMNS = (
    "id",
    "pmcid",
    "outcome",
    "intervention",
    "comparator",
    "outcome_type",
    "split",
    "is_data_in_figure_graphics",
    "is_table_in_graphic_format",
    *dict.fromkeys(field for fields in FIELDS.values() for field in fields),
)
PATTERNS = {
    "intervention_group_size": r"Drug group: (\d+) patients",
    "intervention_events": r"Drug group: \d+ patients, (\d+) events",
    "comparator_group_size": r"Placebo group: (\d+) patients",
    "comparator_events": r"Placebo group: \d+ patients, (\d+) events",
}


def write_benchmark(folder: Path, papers: int) -> None:
    (folder / "texts").mkdir(parents=True)
    rows = []
    for index in range(papers):
        pmcid = 1000 + index
        sizes, events = (50 + index, 60 + index), (5 + index % 4, 9 + index % 5)
        (folder / "texts" / f"PMC{pmcid}.md").write_text(
            f"Trial PMC{pmcid}. Drug group: {sizes[0]} patients, {events[0]} events. "
            f"Placebo group: {sizes[1]} patients, {events[1]} events.",
            encoding="utf-8",
        )
        row = dict.fromkeys(COLUMNS, "")
        row |= {
            "id": str(index),
            "pmcid": str(pmcid),
            "outcome": "events",
            "intervention": "drug",
            "comparator": "placebo",
            "outcome_type": "binary",
            "split": "TEST",
            "is_data_in_figure_graphics": "FALSE",
            "is_table_in_graphic_format": "FALSE",
            "intervention_group_size": str(sizes[0]),
            "comparator_group_size": str(sizes[1]),
            "intervention_events": str(events[0]),
            "comparator_events": str(events[1]),
        }
        rows.append(row)
    with (folder / experiment.ANNOTATIONS_FILE).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def mock_model(call: MockCall, index: int) -> str:
    """right on three papers in four; wrong, with disagreeing samples, on the fourth."""
    field = re.search(r"Item to extract: (\w+)", call.prompt).group(1)  # type: ignore[union-attr]
    pmcid = int(re.search(r"Trial PMC(\d+)\.", call.prompt).group(1))  # type: ignore[union-attr]
    right = int(re.search(PATTERNS[field], call.prompt).group(1))  # type: ignore[union-attr]
    if pmcid % 4 == 0:
        wrong = right + 1 + (index if call.temperature > 0 else 0)
        return json.dumps({"value": str(wrong), "evidence": None, "page": None})
    return json.dumps({"value": str(right), "evidence": None, "page": None})


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("EXGA_")}
    return subprocess.run(
        [sys.executable, str(RUN), *args],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    write_benchmark(tmp_path / "benchmark", papers=40)
    path = tmp_path / "e2e.yaml"
    content = {
        "name": "e2e",
        "benchmark": str(tmp_path / "benchmark"),
        "models": [{"name": "mock"}],
        "alphas": [0.1, 0.2],
        "repetitions": 2,
        "bootstrap": 20,
        "audit_batch": 20,
        "runs": str(tmp_path / "runs"),
        "results": str(tmp_path / "results"),
    }
    path.write_text(json.dumps(content), encoding="utf-8")  # JSON is valid YAML
    return path


def test_evaluate_writes_tables_figures_and_a_manifest(config_path: Path) -> None:
    config = experiment.load_config(config_path)
    items = experiment.load_benchmark(config)
    settings = Settings(extraction=ExtractionSettings(samples=3, workers=2))
    experiment.extract(config, config.models[0], items, MockLLMClient(mock_model), settings)

    result = run_script("evaluate", str(config_path))

    assert result.returncode == 0, result.stderr
    folder = config.results_folder()
    assert sorted(path.name for path in (folder / "tables").iterdir()) == [
        "baselines.csv",
        "by_field.csv",
        "by_group.csv",
        "updating.csv",
    ]
    figures = sorted((folder / "figures").iterdir())
    assert [path.name for path in figures] == [
        "acceptance_vs_alpha.png",
        "realised_vs_target_error.png",
        "updating_mock.png",
    ]
    assert all(path.read_bytes().startswith(b"\x89PNG") for path in figures)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["inputs"]) == {"annotations", "samples/mock"}
    assert manifest["benchmark"]["items"] == {"mock": 160}
    assert manifest["seeds"]["splits"] == [0, 1]
    assert manifest["models"]["mock"]["model_id"] == "mock"
    assert manifest["git"]["commit"] is not None


def test_extract_without_a_model_name_stops_with_a_configuration_error(config_path: Path) -> None:
    result = run_script("extract", str(config_path))

    assert result.returncode == 2
    assert "hosted.model is not set" in result.stderr
