"""random audits: drawing items to check and turning checks into records (spec 5.6, 7.7).

pure functions; `store.py` persists batches, records and the threshold log. only items drawn
here may become calibration records (ADR 0009).
"""

import math
import random
from collections.abc import Sequence
from datetime import datetime

from exga.calibrate import calibrate_fields
from exga.labels import is_wrong
from exga.schemas import CalibrationRecord, Extraction, FieldSpec, ThresholdResult
from exga.settings import AuditSettings, CalibrationSettings, MatchingSettings


def audit_size(n_items: int, settings: AuditSettings) -> int:
    """how many of n_items to draw: rate * n_items rounded up, at least min_items, at most all."""
    # rounding first stops float noise (0.07 * 100 = 7.000000000000001) adding an item
    wanted = max(settings.min_items, math.ceil(round(settings.rate * n_items, 9)))
    return min(n_items, wanted)


def draw_audit(
    extractions: Sequence[Extraction], settings: AuditSettings, seed: int
) -> list[Extraction]:
    """a uniform random sample of all items, accepted and flagged alike.

    every item is equally likely, whatever its score or decision, which is what makes the
    resulting records exchangeable with future items. the order is that of extractions,
    so the sample depends only on the items and the seed.
    """
    chosen = random.Random(seed).sample(
        range(len(extractions)), audit_size(len(extractions), settings)
    )
    return [extractions[index] for index in sorted(chosen)]


def audit_record(
    extraction: Extraction,
    checked_value: str | None,
    spec: FieldSpec,
    rules: MatchingSettings,
    created_at: datetime,
) -> CalibrationRecord:
    """the calibration record for one drawn item, given the value a person found in the paper.

    checked_value is the correct value (None when the paper does not report it); the record
    is wrong when the extracted value fails the field's rule against it.
    """
    return CalibrationRecord(
        paper_id=extraction.paper_id,
        field=extraction.field,
        group=spec.group,
        score=extraction.score,
        wrong=is_wrong(extraction, checked_value, spec, rules),
        source="random_audit",
        created_at=created_at,
    )


def recalibrate(
    records: Sequence[CalibrationRecord],
    specs: Sequence[FieldSpec],
    settings: CalibrationSettings,
) -> dict[str, ThresholdResult]:
    """thresholds for every field from all records so far (spec 7.7)."""
    return calibrate_fields(records, specs, settings)
