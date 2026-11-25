import csv
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import settings

from exga.benchmark import FIELDS
from exga.experiment import ANNOTATIONS_FILE

# derandomised so every run checks the same examples (CLAUDE.md 6: tests are deterministic);
# no example database, so nothing is written outside the repository's ignored caches
settings.register_profile("exga", derandomize=True, database=None, deadline=None, max_examples=200)
settings.load_profile("exga")

BENCHMARK_COLUMNS = (
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


def _write_benchmark(folder: Path, papers: int) -> None:
    """a benchmark in the downloaded layout: binary-outcome trials stating every value."""
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
        row = dict.fromkeys(BENCHMARK_COLUMNS, "")
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
    with (folder / ANNOTATIONS_FILE).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BENCHMARK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def write_benchmark() -> Callable[[Path, int], None]:
    """writes a tiny benchmark of the given number of papers into a folder."""
    return _write_benchmark
