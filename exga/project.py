"""project workflows: the store plus the pure modules, in the order the method needs.

the app and the command line call these, so the audit-and-recalibrate loop (spec 5.6) exists
once. every function takes the time as an argument; none reads the clock.
"""

from collections.abc import Sequence
from datetime import datetime

from exga.audit import audit_record, draw_audit, recalibrate
from exga.decide import apply_thresholds
from exga.errors import ConfigError
from exga.schemas import CalibrationRecord, Extraction, ThresholdResult
from exga.settings import Settings
from exga.store import ProjectStore, ThresholdVersion


def current_thresholds(store: ProjectStore) -> dict[str, ThresholdResult]:
    """the newest logged threshold of every field; empty before the first calibration."""
    log = store.threshold_log()
    return log[-1].results if log else {}


def save_scored(store: ProjectStore, extractions: Sequence[Extraction], at: datetime) -> None:
    """store new extractions with decisions under the current thresholds."""
    store.save_extractions(apply_thresholds(extractions, current_thresholds(store)), at)


def import_records(
    store: ProjectStore, records: Sequence[CalibrationRecord], settings: Settings, at: datetime
) -> ThresholdVersion:
    """append benchmark or annotation records, then recalibrate.

    raises ConfigError for random-audit records, which only `finish_audit` may add.
    """
    if any(record.source == "random_audit" for record in records):
        raise ConfigError("random-audit records come only from completed audit batches")
    store.add_records(records)
    return recalibrate_project(store, settings, at)


def recalibrate_project(store: ProjectStore, settings: Settings, at: datetime) -> ThresholdVersion:
    """recompute every field's threshold from all records, log it, and re-decide every item."""
    records = store.records()
    results = recalibrate(records, store.fields(), settings.calibration)
    version = store.log_thresholds(results, len(records), at)
    store.save_extractions(apply_thresholds(store.extractions(), results), at)
    return store.threshold_log()[version - 1]


def draw_next_audit(store: ProjectStore, settings: Settings, at: datetime) -> int | None:
    """the open audit batch, or a new one drawn from items not yet audited; None if none remain.

    batch k is drawn with seed settings.audit.seed + k, so the draws can be replayed.
    """
    open_batch = store.open_audit()
    if open_batch is not None:
        return open_batch
    audited = store.audited()
    candidates = [e for e in store.extractions() if (e.paper_id, e.field) not in audited]
    if not candidates:
        return None
    seed = settings.audit.seed + store.audit_batch_count()
    return store.start_audit(draw_audit(candidates, settings.audit, seed), seed, at)


def finish_audit(
    store: ProjectStore, batch_id: int, settings: Settings, at: datetime
) -> ThresholdVersion:
    """turn a fully checked batch into records, close it, and recalibrate.

    skipped items give no record. raises ConfigError while items are unchecked.
    """
    specs = {spec.name: spec for spec in store.fields()}
    extractions = {(e.paper_id, e.field): e for e in store.extractions()}
    records = [
        audit_record(
            extractions[item.paper_id, item.field],
            item.checked_value,
            specs[item.field],
            settings.matching,
            at,
        )
        for item in store.audit_items(batch_id)
        if item.status == "checked"
    ]
    store.complete_audit(batch_id, records, at)
    return recalibrate_project(store, settings, at)
