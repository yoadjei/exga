import csv
from pathlib import Path

import pytest

from exga.benchmark import (
    ALL_FIELDS,
    benchmark_items,
    load_templates,
    load_texts,
    read_annotations,
)
from exga.errors import ConfigError

COLUMNS = [
    "id", "evidence_inference_prompt_id", "pmcid", "outcome", "intervention", "comparator",
    "outcome_type", "intervention_events", "intervention_group_size", "comparator_events",
    "comparator_group_size", "intervention_mean", "intervention_standard_deviation",
    "comparator_mean", "comparator_standard_deviation", "notes", "is_data_in_figure_graphics",
    "is_relevant_data_in_table", "is_table_in_graphic_format", "is_data_complete", "split",
]  # fmt: skip


def row(
    id_: int, pmcid: int, outcome_type: str, split: str = "TEST", **values: str
) -> dict[str, str]:
    base = dict.fromkeys(COLUMNS, "")
    flags = {"is_data_in_figure_graphics": "FALSE", "is_table_in_graphic_format": "FALSE"}
    return base | flags | {
        "id": str(id_), "pmcid": str(pmcid), "outcome": f"outcome {id_}", "intervention": "drug",
        "comparator": "placebo", "outcome_type": outcome_type, "split": split,
    } | values  # fmt: skip


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def annotations(tmp_path: Path) -> Path:
    rows = [
        row(1, 10, "binary", intervention_events="12", intervention_group_size="1,525",
            comparator_events="", comparator_group_size="1,514"),
        row(2, 10, "binary", intervention_events="3", intervention_group_size="40"),
        row(3, 20, "continuous", intervention_mean="47.5", intervention_standard_deviation="38.9",
            intervention_group_size="30", comparator_events="20"),
        row(4, 20, "continuous", is_data_in_figure_graphics="TRUE", intervention_mean="1"),
        row(5, 30, "binary", split="DEV", intervention_events="1"),
    ]  # fmt: skip
    return write_csv(tmp_path / "annotations.csv", rows)


@pytest.fixture
def texts(tmp_path: Path) -> Path:
    folder = tmp_path / "texts"
    folder.mkdir()
    for pmcid in (10, 20, 30):
        (folder / f"PMC{pmcid}.md").write_text(f"# Abstract paper {pmcid}", encoding="utf-8")
    return folder


def test_annotations_keep_only_fields_that_apply(annotations: Path) -> None:
    first, _, continuous, graphics, dev = read_annotations(annotations)

    assert first.values == {
        "intervention_events": "12",
        "intervention_group_size": "1,525",
        "comparator_events": None,
        "comparator_group_size": "1,514",
    }
    assert "comparator_events" not in continuous.values
    assert continuous.values["comparator_mean"] is None
    assert (graphics.in_graphics, first.in_graphics) == (True, False)
    assert (dev.split, first.text_file) == ("DEV", "PMC10.md")


def test_unexpected_values_are_config_errors(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "bad.csv", [row(1, 10, "ordinal")])

    with pytest.raises(ConfigError, match="outcome_type 'ordinal'"):
        read_annotations(path)


def test_each_paper_gives_one_item_per_applicable_field(annotations: Path, texts: Path) -> None:
    triplets = read_annotations(annotations)
    documents = load_texts(texts, triplets)

    items = benchmark_items(triplets, documents, load_templates(), split="TEST", seed=0)

    assert [(item.document.filename, item.spec.name) for item in items] == [
        ("PMC10.md", "intervention_events"),
        ("PMC10.md", "intervention_group_size"),
        ("PMC10.md", "comparator_events"),
        ("PMC10.md", "comparator_group_size"),
        ("PMC20.md", "intervention_group_size"),
        ("PMC20.md", "comparator_group_size"),
        ("PMC20.md", "intervention_mean"),
        ("PMC20.md", "intervention_standard_deviation"),
        ("PMC20.md", "comparator_mean"),
        ("PMC20.md", "comparator_standard_deviation"),
    ]
    mean = items[6]
    assert (mean.triplet_id, mean.gold) == (3, "47.5")
    assert mean.spec.description == (
        'mean of the outcome "outcome 3" in the "drug" group, as reported for the comparison '
        'with "placebo"'
    )


def test_the_triplet_choice_is_seeded_and_independent_of_input_order(
    annotations: Path, texts: Path
) -> None:
    triplets = read_annotations(annotations)
    documents = load_texts(texts, triplets)
    templates = load_templates()

    def chosen(order: list[int], seed: int) -> list[int]:
        reordered = [triplets[i] for i in order]
        items = benchmark_items(reordered, documents, templates, split="TEST", seed=seed)
        return [item.triplet_id for item in items]

    assert chosen([0, 1, 2, 3, 4], seed=0) == chosen([4, 3, 2, 1, 0], seed=0)
    seeds = {tuple(chosen([0, 1, 2, 3, 4], seed)) for seed in range(20)}
    assert len(seeds) > 1


def test_dev_papers_are_kept_apart(annotations: Path, texts: Path) -> None:
    triplets = read_annotations(annotations)
    items = benchmark_items(
        triplets, load_texts(texts, triplets), load_templates(), split="DEV", seed=0
    )

    assert {item.document.filename for item in items} == {"PMC30.md"}


def test_missing_texts_are_named(annotations: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"3 benchmark texts missing.*PMC10.md"):
        load_texts(tmp_path, read_annotations(annotations))


def test_every_field_has_a_question() -> None:
    assert set(load_templates()) == set(ALL_FIELDS)


RAW = Path(__file__).parents[1] / "data" / "benchmark" / "raw"


@pytest.mark.skipif(
    not (RAW / "annotated_rct_dataset.csv").is_file(), reason="benchmark not downloaded"
)
def test_the_downloaded_benchmark_matches_adr_0008() -> None:
    triplets = read_annotations(RAW / "annotated_rct_dataset.csv")

    assert (len(triplets), len({t.pmcid for t in triplets})) == (699, 120)
    test_split = [t for t in triplets if t.split == "TEST"]
    assert (len(test_split), sum(t.in_graphics for t in test_split)) == (656, 167)
