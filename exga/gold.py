"""the owner's gold file: human-checked values for the annotated set (spec 10.2).

gold.csv has the columns paper_id, field and value; "NR" means the paper does not report
the field. a paper id is the sha256 of the PDF, as `exga extract` records it.
"""

import csv
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from exga.errors import ConfigError
from exga.labels import gold_value
from exga.matching import check_gold, values_match
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings

GOLD_COLUMNS = ("paper_id", "field", "value")
_PAPER_ID = re.compile(r"^[0-9a-f]{64}$")

Gold = dict[tuple[str, str], str | None]


@dataclass(frozen=True)
class Agreement:
    """how often two annotators agree on one field, under the field's correctness rule."""

    field: str
    agreed: int
    compared: int

    @property
    def rate(self) -> float | None:
        """share of doubly annotated items with the same value; None when none were compared."""
        return self.agreed / self.compared if self.compared else None


def load_gold(path: Path, specs: Sequence[FieldSpec]) -> Gold:
    """read and validate a gold file into {(paper_id, field): value or None}.

    raises ConfigError naming the line of the first problem: missing columns, a malformed
    paper id, an unknown field, an empty or malformed value, or a repeated (paper, field).
    """
    by_name = {spec.name: spec for spec in specs}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [column for column in GOLD_COLUMNS if column not in (reader.fieldnames or ())]
            if missing:
                raise ConfigError(f"{path} lacks columns: {', '.join(missing)}")
            rows = list(reader)
    except OSError as exc:
        raise ConfigError(f"cannot read gold file {path}: {exc}") from exc
    gold: Gold = {}
    for line, row in enumerate(rows, start=2):
        try:
            key, value = _read_row(row, by_name)
        except ConfigError as exc:
            raise ConfigError(f"{path}, line {line}: {exc}") from exc
        if key in gold:
            raise ConfigError(f"{path}, line {line}: {key[1]} for paper {key[0][:12]}… is repeated")
        gold[key] = value
    return gold


def agreement(
    first: Mapping[tuple[str, str], str | None],
    second: Mapping[tuple[str, str], str | None],
    specs: Sequence[FieldSpec],
    rules: MatchingSettings,
) -> list[Agreement]:
    """per field, how often two annotators' values match on the items both annotated."""
    results = []
    for spec in specs:
        shared = [key for key in first if key[1] == spec.name and key in second]
        agreed = sum(values_match(first[key], second[key], spec, rules) for key in shared)
        results.append(Agreement(field=spec.name, agreed=agreed, compared=len(shared)))
    return results


def _read_row(
    row: Mapping[str, str | None], specs: Mapping[str, FieldSpec]
) -> tuple[tuple[str, str], str | None]:
    paper_id = (row["paper_id"] or "").strip()
    field = (row["field"] or "").strip()
    if not _PAPER_ID.match(paper_id):
        raise ConfigError(f"paper_id {paper_id!r} is not a sha256 hex digest")
    if field not in specs:
        raise ConfigError(f"field {field!r} is not in the field list")
    value = gold_value(row["value"] or "")
    check_gold(value, specs[field])
    return (paper_id, field), value
