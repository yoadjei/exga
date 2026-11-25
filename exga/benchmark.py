"""the Yun et al. (2024) benchmark of RCT reports with numeric outcome data (spec 10.1).

ADR 0008 records how annotated triplets become exga items. `scripts/download_benchmark.py`
fetches the pinned files; this module reads them and builds items. nothing here touches the
network.
"""

import csv
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Literal

import yaml

from exga.document import text_document
from exga.errors import ConfigError
from exga.schemas import Document, FieldSpec

SOURCE_REPOSITORY = "https://github.com/hyesunyun/llm-meta-analysis"
SOURCE_COMMIT = "1bc768d4d098c727c9866eeff909297c38a3e84c"
ANNOTATIONS_PATH = "evaluation/data/annotated_rct_dataset.csv"
ANNOTATIONS_SHA256 = "5e5f660fa770ab647fa44424f002c7b9e1a2b6a3feb783ee2dc4f2438c1017f6"
TEXT_FOLDER = "evaluation/data/no_attributes_markdown_files"
TEMPLATES_PATH = Path(__file__).parent / "prompts" / "benchmark_fields_v1.yaml"

OutcomeType = Literal["binary", "continuous"]
Split = Literal["DEV", "TEST"]
FIELDS: dict[OutcomeType, tuple[str, ...]] = {
    "binary": (
        "intervention_events",
        "intervention_group_size",
        "comparator_events",
        "comparator_group_size",
    ),
    "continuous": (
        "intervention_group_size",
        "comparator_group_size",
        "intervention_mean",
        "intervention_standard_deviation",
        "comparator_mean",
        "comparator_standard_deviation",
    ),
}
ALL_FIELDS = tuple(dict.fromkeys(field for fields in FIELDS.values() for field in fields))
_TRUE = "TRUE"
# the CSV's strings mapped to their literal types
_OUTCOME_TYPES: dict[str, OutcomeType] = {"binary": "binary", "continuous": "continuous"}
_SPLITS: dict[str, Split] = {"DEV": "DEV", "TEST": "TEST"}


@dataclass(frozen=True)
class Triplet:
    """one annotated intervention-comparator-outcome comparison in one paper."""

    id: int
    pmcid: int
    outcome: str
    intervention: str
    comparator: str
    outcome_type: OutcomeType
    values: Mapping[str, str | None]
    """gold per applicable field; None where the annotators found no usable number."""
    in_graphics: bool
    """data flagged as being in figures or in tables stored as images."""
    split: Split

    @property
    def text_file(self) -> str:
        """name of the paper's markdown file."""
        return f"PMC{self.pmcid}.md"


@dataclass(frozen=True)
class BenchmarkItem:
    """one question to the model: a field of one triplet, with its gold value."""

    document: Document
    spec: FieldSpec
    gold: str | None
    triplet_id: int


def read_annotations(path: Path) -> list[Triplet]:
    """read the annotation CSV; raises ConfigError for a missing file or unexpected content."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ConfigError(f"cannot read benchmark annotations {path}: {exc}") from exc
    try:
        return [_triplet(row) for row in rows]
    except (KeyError, ValueError) as exc:
        raise ConfigError(f"unexpected content in {path}: {exc!r}") from exc


def load_templates(path: Path = TEMPLATES_PATH) -> dict[str, Template]:
    """the question template of every benchmark field; raises ConfigError if one is missing."""
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [field for field in ALL_FIELDS if not isinstance(content.get(field), str)]
    if missing:
        raise ConfigError(f"{path} has no question for: {', '.join(missing)}")
    return {field: Template(" ".join(content[field].split())) for field in ALL_FIELDS}


def load_texts(folder: Path, triplets: Sequence[Triplet]) -> dict[int, Document]:
    """the paper text of every pmcid in triplets; raises ConfigError naming missing files."""
    names = sorted({triplet.text_file for triplet in triplets})
    missing = [name for name in names if not (folder / name).is_file()]
    if missing:
        raise ConfigError(
            f"{len(missing)} benchmark texts missing from {folder}, e.g. {missing[0]}"
        )
    texts = {}
    for triplet in triplets:
        if triplet.pmcid not in texts:
            text = (folder / triplet.text_file).read_text(encoding="utf-8")
            texts[triplet.pmcid] = text_document(text, triplet.text_file)
    return texts


def benchmark_items(
    triplets: Sequence[Triplet],
    texts: Mapping[int, Document],
    templates: Mapping[str, Template],
    *,
    split: Split,
    seed: int,
) -> list[BenchmarkItem]:
    """one item per (paper, field) of split, from a randomly chosen eligible triplet.

    triplets with data in graphics are not eligible. the choice for each (paper, field) uses
    its own seed derived from (seed, pmcid, field), so it does not depend on input order.
    items are ordered by paper, then field.
    """
    eligible: dict[tuple[int, str], list[Triplet]] = {}
    for triplet in triplets:
        if triplet.split != split or triplet.in_graphics:
            continue
        for field in FIELDS[triplet.outcome_type]:
            eligible.setdefault((triplet.pmcid, field), []).append(triplet)
    items = []
    for pmcid, field in sorted(eligible, key=lambda key: (key[0], ALL_FIELDS.index(key[1]))):
        candidates = sorted(eligible[pmcid, field], key=lambda triplet: triplet.id)
        chosen = random.Random(f"{seed}:{pmcid}:{field}").choice(candidates)
        description = templates[field].substitute(
            intervention=chosen.intervention, comparator=chosen.comparator, outcome=chosen.outcome
        )
        items.append(
            BenchmarkItem(
                document=texts[pmcid],
                spec=FieldSpec(name=field, description=description, group="numeric"),
                gold=chosen.values[field],
                triplet_id=chosen.id,
            )
        )
    return items


def _triplet(row: Mapping[str, str]) -> Triplet:
    if row["outcome_type"] not in _OUTCOME_TYPES or row["split"] not in _SPLITS:
        raise ValueError(
            f"row {row['id']}: outcome_type {row['outcome_type']!r}, split {row['split']!r}"
        )
    outcome_type = _OUTCOME_TYPES[row["outcome_type"]]
    return Triplet(
        id=int(row["id"]),
        pmcid=int(row["pmcid"]),
        outcome=row["outcome"].strip(),
        intervention=row["intervention"].strip(),
        comparator=row["comparator"].strip(),
        outcome_type=outcome_type,
        values={field: row[field].strip() or None for field in FIELDS[outcome_type]},
        in_graphics=_TRUE in (row["is_data_in_figure_graphics"], row["is_table_in_graphic_format"]),
        split=_SPLITS[row["split"]],
    )
