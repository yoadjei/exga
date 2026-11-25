"""the experiment pipeline on a small synthetic benchmark and a mock model (ADR 0011).

the numbers these tests produce are not results: they only show that each table is built,
from the right items, the same way every time.
"""

import json
import re
from pathlib import Path

import pytest

from exga.benchmark import BenchmarkItem
from exga.document import text_document
from exga.errors import ConfigError
from exga.experiment import (
    ExperimentConfig,
    ModelConfig,
    Tables,
    evaluate,
    extract,
    label,
    load_benchmark,
    load_config,
    load_samples,
    write_tables,
)
from exga.llm.mock import MockCall, MockLLMClient
from exga.schemas import FieldSpec
from exga.settings import ExtractionSettings, HostedSettings, Settings

SETTINGS = Settings(extraction=ExtractionSettings(samples=3, workers=2))
SIZE = FieldSpec(name="intervention_group_size", description="participants", group="numeric")
EVENTS = FieldSpec(name="intervention_events", description="events", group="numeric")
RAW = Path(__file__).parents[1] / "data" / "benchmark" / "raw"


def synthetic_items(papers: int) -> list[BenchmarkItem]:
    items = []
    for index in range(papers):
        size, events = 100 + index, 10 + index % 7
        document = text_document(
            f"Trial {index}. A total of {size} participants were randomised. "
            f"There were {events} events in the intervention group.",
            f"trial{index}.md",
        )
        items.append(BenchmarkItem(document, SIZE, str(size), index))
        items.append(BenchmarkItem(document, EVENTS, str(events), index))
    return items


def mock_model(call: MockCall, index: int) -> str:
    """right on three papers in four; on the fourth, a wrong greedy answer and samples that
    disagree, so low agreement marks the wrong values."""
    paper = int(re.search(r"Trial (\d+)\.", call.prompt).group(1))  # type: ignore[union-attr]
    if "intervention_group_size" in call.prompt:
        right = re.search(r"A total of (\d+) participants", call.prompt).group(1)  # type: ignore[union-attr]
        quote = f"A total of {right} participants were randomised"
    else:
        right = re.search(r"There were (\d+) events", call.prompt).group(1)  # type: ignore[union-attr]
        quote = f"There were {right} events in the intervention group"
    if paper % 4 == 0:
        value = str(int(right) + 1 + (index if call.temperature > 0 else 0))
        return json.dumps({"value": value, "evidence": None, "page": None})
    return json.dumps({"value": right, "evidence": quote, "page": 1})


def config(tmp_path: Path, **update: object) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        {
            "name": "test",
            "models": [{"name": "mock", "hosted": {"model": "mock-1"}}],
            "alphas": [0.2],
            "repetitions": 3,
            "bootstrap": 50,
            "audit_batch": 20,
            "runs": tmp_path / "runs",
            "results": tmp_path / "results",
            **update,
        }
    )


@pytest.fixture
def extracted(tmp_path: Path) -> tuple[ExperimentConfig, list[BenchmarkItem]]:
    experiment = config(tmp_path)
    items = synthetic_items(80)
    extract(experiment, experiment.models[0], items, MockLLMClient(mock_model), SETTINGS)
    return experiment, items


def test_a_config_file_is_validated_and_keeps_secrets_out(tmp_path: Path) -> None:
    path = tmp_path / "main.yaml"
    path.write_text(
        "name: main\nmodels:\n  - name: gpt\n    hosted: {model: gpt-x}\n", encoding="utf-8"
    )

    loaded = load_config(path)

    assert (loaded.alphas, loaded.repetitions, loaded.primary_variant) == (
        (0.05, 0.1, 0.2),
        50,
        "combined",
    )
    assert set(loaded.variants) == {
        "agreement",
        "agreement+logprob",
        "agreement+source",
        "combined",
    }
    path.write_text(
        "name: main\nmodels:\n  - name: gpt\n    hosted: {api_key: sk-1}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="EXGA_HOSTED__API_KEY"):
        load_config(path)


@pytest.mark.parametrize(
    ("update", "problem"),
    [
        ({"alphas": [0.0]}, "between 0 and 1"),
        ({"primary_variant": "none"}, "not in variants"),
        ({"models": [{"name": "a"}, {"name": "a"}]}, "distinct"),
        ({"surprise": 1}, "Extra inputs"),
    ],
)
def test_bad_configs_say_what_is_wrong(
    tmp_path: Path, update: dict[str, object], problem: str
) -> None:
    path = tmp_path / "bad.yaml"
    content = {"name": "bad", "models": [{"name": "m"}], **update}
    path.write_text(json.dumps(content), encoding="utf-8")  # JSON is valid YAML

    with pytest.raises(ConfigError, match=problem):
        load_config(path)


def test_a_model_overrides_the_environment_endpoint() -> None:
    model = ModelConfig(name="local", hosted={"base_url": "http://localhost:8000/v1", "model": "q"})

    settings = model.settings(HostedSettings(model="from-env", requests_per_minute=30))

    assert (settings.base_url, settings.model, settings.requests_per_minute) == (
        "http://localhost:8000/v1",
        "q",
        30,
    )


def test_extraction_saves_samples_and_a_summary_and_reruns_from_cache(
    extracted: tuple[ExperimentConfig, list[BenchmarkItem]],
) -> None:
    experiment, items = extracted
    summary = json.loads(
        (experiment.samples_path(experiment.models[0]).parent / "run.json").read_text()
    )
    again = MockLLMClient(mock_model)

    rerun = extract(experiment, experiment.models[0], items, again, SETTINGS)

    assert (summary["items"], summary["failed_requests"], summary["model_id"]) == (160, 0, "mock")
    assert len(load_samples(experiment, experiment.models[0])) == 160
    assert (again.calls, rerun.requests_sent) == ([], 0)


def test_labels_follow_the_gold_values(
    extracted: tuple[ExperimentConfig, list[BenchmarkItem]],
) -> None:
    experiment, items = extracted

    labelled = label(items, load_samples(experiment, experiment.models[0]), SETTINGS)

    assert len(labelled) == 160
    assert sum(item.wrong for item in labelled) == 40  # papers 0, 4, 8, ... in both fields
    wrong = [item for item in labelled if item.wrong]
    right = [item for item in labelled if not item.wrong]
    assert max(item.signals.agreement for item in wrong) < min(
        item.signals.agreement for item in right
    )


def test_labelling_refuses_samples_from_another_run(
    extracted: tuple[ExperimentConfig, list[BenchmarkItem]],
) -> None:
    experiment, items = extracted
    samples = load_samples(experiment, experiment.models[0])

    with pytest.raises(ConfigError, match="2 items have no samples"):
        label(items, samples[:-2], SETTINGS)


def test_missing_samples_point_to_the_extract_step(tmp_path: Path) -> None:
    experiment = config(tmp_path)

    with pytest.raises(ConfigError, match=r"run experiments/run\.py extract first"):
        load_samples(experiment, experiment.models[0])


def test_evaluation_builds_every_table_the_same_way_twice(
    extracted: tuple[ExperimentConfig, list[BenchmarkItem]],
) -> None:
    experiment, items = extracted
    labelled = {"mock": label(items, load_samples(experiment, experiment.models[0]), SETTINGS)}

    tables = evaluate(experiment, labelled)

    assert tables == evaluate(experiment, labelled)
    variants = len(experiment.variants)
    assert len(tables.by_group) == variants * 2  # all fields, and the numeric group
    assert len(tables.by_field) == variants * 2
    assert len(tables.baselines) == variants * 3
    assert {row["variant"] for row in tables.updating} == {"combined"}
    combined = next(
        r for r in tables.by_group if r["variant"] == "combined" and r["group"] == "all"
    )
    assert combined["test_items"] == 48  # 24 test papers, 2 fields each
    assert combined["raw_accuracy"] is not None
    assert combined["splits"] == 3
    accept_all = next(r for r in tables.baselines if r["baseline"] == "accept_all")
    assert accept_all["acceptance_rate"] == 1.0
    records = [int(str(row["audit_records"])) for row in tables.updating]
    assert records == sorted(records)


def test_the_results_folder_changes_with_the_config(tmp_path: Path) -> None:
    first = config(tmp_path)
    second = config(tmp_path, alphas=[0.1])

    assert first.results_folder() != second.results_folder()
    assert first.results_folder() == config(tmp_path).results_folder()
    assert first.results_folder().name.startswith("test-")


@pytest.mark.skipif(
    not (RAW / "annotated_rct_dataset.csv").is_file(), reason="benchmark not downloaded"
)
def test_the_downloaded_benchmark_loads_as_550_test_items(tmp_path: Path) -> None:
    items = load_benchmark(config(tmp_path, benchmark=RAW))

    assert len(items) == 550


def test_a_missing_benchmark_says_how_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"download_benchmark\.py"):
        load_benchmark(config(tmp_path, benchmark=tmp_path / "none"))


def test_tables_are_written_as_csv_files(tmp_path: Path) -> None:
    tables = Tables(
        by_group=[{"model": "m", "alpha": 0.1, "realised_error": 0.0412345678, "certified": True}],
        baselines=[{"model": "m", "cutoff": None}],
    )

    paths = write_tables(tables, tmp_path / "tables")

    assert [path.name for path in paths] == [
        "by_group.csv",
        "by_field.csv",
        "baselines.csv",
        "updating.csv",
    ]
    assert (tmp_path / "tables" / "by_group.csv").read_text(encoding="utf-8") == (
        "model,alpha,realised_error,certified\nm,0.1,0.0412346,true\n"
    )
    assert (tmp_path / "tables" / "baselines.csv").read_text(
        encoding="utf-8"
    ) == "model,cutoff\nm,\n"
    assert (tmp_path / "tables" / "updating.csv").read_text(encoding="utf-8") == ""


def test_paths_hash_the_same_on_every_operating_system(tmp_path: Path) -> None:
    experiment = config(tmp_path, benchmark=Path("data") / "benchmark" / "raw")

    dumped = experiment.model_dump(mode="json")

    assert dumped["benchmark"] == "data/benchmark/raw"  # not data\benchmark\raw on Windows
