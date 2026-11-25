"""turning human-checked values into calibration records (spec 5.6, 6, 10). pure functions."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from exga.errors import ConfigError
from exga.matching import is_correct
from exga.schemas import CalibrationRecord, Extraction, FieldSpec, RecordSource
from exga.settings import MatchingSettings

# how gold files and audit forms write "the paper does not report this" (spec 10.2)
NOT_REPORTED = "NR"


def gold_value(text: str) -> str | None:
    """read one gold cell: "NR" means not reported (None); anything else is the value."""
    value = text.strip()
    if not value:
        raise ConfigError('an empty gold value is ambiguous; write "NR" for "not reported"')
    return None if value == NOT_REPORTED else value


def is_wrong(
    extraction: Extraction, gold: str | None, spec: FieldSpec, rules: MatchingSettings
) -> bool:
    """whether an extracted value fails its field's correctness rule against gold.

    an item without a usable answer (`failed`) is always wrong: it claims nothing, so even
    a gold "not reported" is not something it found.
    """
    return extraction.failed or not is_correct(extraction.value, gold, spec, rules)


def calibration_records(
    extractions: Sequence[Extraction],
    gold: Mapping[tuple[str, str], str | None],
    specs: Sequence[FieldSpec],
    rules: MatchingSettings,
    *,
    source: RecordSource,
    created_at: datetime,
) -> list[CalibrationRecord]:
    """one record per extraction that has a gold value, keyed by (paper_id, field).

    extractions without gold, or of fields not in specs, are skipped. raises ConfigError
    when a gold value is malformed for its field (see `matching.is_correct`).
    """
    by_name = {spec.name: spec for spec in specs}
    records = []
    for extraction in extractions:
        key = (extraction.paper_id, extraction.field)
        spec = by_name.get(extraction.field)
        if spec is None or key not in gold:
            continue
        records.append(
            CalibrationRecord(
                paper_id=extraction.paper_id,
                field=extraction.field,
                group=spec.group,
                score=extraction.score,
                wrong=is_wrong(extraction, gold[key], spec, rules),
                source=source,
                created_at=created_at,
            )
        )
    return records
