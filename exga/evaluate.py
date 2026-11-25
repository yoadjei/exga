"""how well the method does on labelled items: metrics, baselines, intervals, splits and the
updating curve (spec 7.8, 11; ADR 0011). pure functions.

calibration goes through `calibrate_fields`, the function the app uses, so experiments
measure exactly the deployed method.
"""

import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import numpy.typing as npt

from exga.calibrate import calibrate_fields
from exga.schemas import CalibrationRecord, FieldGroup, FieldSpec, Signals, ThresholdResult
from exga.score import combine
from exga.settings import CalibrationSettings, ScoreSettings
from exga.splits import PaperSplit

Metric = Literal["raw_accuracy", "acceptance_rate", "realised_error", "coverage"]
BoolArray = npt.NDArray[np.bool_]
FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BASELINES = ("accept_all", "fixed_cutoff", "verify_all")
# records need a creation time; a fixed one keeps experiment runs byte-for-byte reproducible
_RECORD_TIME = datetime(2000, 1, 1, tzinfo=UTC)
# numerator and denominator of each metric, from the counts (items, wrong, accepted,
# wrong_accepted); a metric is undefined when its denominator is 0
_RATIOS: dict[
    Metric, Callable[[IntArray, IntArray, IntArray, IntArray], tuple[IntArray, IntArray]]
] = {
    "raw_accuracy": lambda items, wrong, _accepted, _wrong_accepted: (items - wrong, items),
    "acceptance_rate": lambda items, _wrong, accepted, _wrong_accepted: (accepted, items),
    "realised_error": lambda _items, _wrong, accepted, wrong_accepted: (wrong_accepted, accepted),
    "coverage": lambda items, wrong, accepted, wrong_accepted: (
        accepted - wrong_accepted,
        items - wrong,
    ),
}


@dataclass(frozen=True)
class LabelledItem:
    """one extracted value with its signals and whether it was wrong against gold."""

    paper_id: str
    field: str
    group: FieldGroup
    signals: Signals
    wrong: bool
    failed: bool = False
    """the model gave no usable answer; such items score 0 under every score (ADR 0007)."""


def variant_scores(items: Sequence[LabelledItem], weights: ScoreSettings) -> FloatArray:
    """each item's score under one weighting of its stored signals (the ablation, ADR 0011)."""
    return np.array(
        [0.0 if item.failed else combine(item.signals, weights) for item in items],
        dtype=np.float64,
    )


@dataclass(frozen=True)
class Outcome:
    """what a method did on a set of items, as counts; the rates are derived from them."""

    items: int
    wrong: int
    accepted: int
    wrong_accepted: int

    def __add__(self, other: "Outcome") -> "Outcome":
        return Outcome(
            self.items + other.items,
            self.wrong + other.wrong,
            self.accepted + other.accepted,
            self.wrong_accepted + other.wrong_accepted,
        )

    def metric(self, name: Metric) -> float | None:
        """the named rate, or None when its denominator is 0."""
        counts = np.array([[self.items, self.wrong, self.accepted, self.wrong_accepted]])
        value = float(_metric_values(counts, name)[0])
        return None if np.isnan(value) else value

    @property
    def raw_accuracy(self) -> float | None:
        """share of all values that are right."""
        return self.metric("raw_accuracy")

    @property
    def acceptance_rate(self) -> float | None:
        """share of values accepted: the verification saved."""
        return self.metric("acceptance_rate")

    @property
    def realised_error(self) -> float | None:
        """share of accepted values that are wrong; None when nothing was accepted."""
        return self.metric("realised_error")

    @property
    def coverage(self) -> float | None:
        """share of right values that were accepted."""
        return self.metric("coverage")


EMPTY = Outcome(0, 0, 0, 0)


def outcome(accepted: Sequence[bool] | BoolArray, wrong: Sequence[bool] | BoolArray) -> Outcome:
    """the counts of a method's decisions on items; raises ValueError for unequal lengths."""
    accepted_array = np.asarray(accepted, dtype=bool)
    wrong_array = np.asarray(wrong, dtype=bool)
    if accepted_array.shape != wrong_array.shape:
        raise ValueError(f"{accepted_array.size} decisions for {wrong_array.size} items")
    return Outcome(
        items=int(accepted_array.size),
        wrong=int(wrong_array.sum()),
        accepted=int(accepted_array.sum()),
        wrong_accepted=int((accepted_array & wrong_array).sum()),
    )


def bootstrap_interval(
    papers: Sequence[str],
    accepted: Sequence[bool] | BoolArray,
    wrong: Sequence[bool] | BoolArray,
    metric: Metric,
    resamples: int,
    seed: int,
    level: float = 0.95,
) -> tuple[float, float] | None:
    """percentile interval of metric over resamples of papers, with all of each paper's items.

    resamples where the metric is undefined (e.g. nothing accepted) are left out; None when
    it is never defined.
    """
    ids = np.asarray(papers)
    accepted_array = np.asarray(accepted, dtype=bool)
    wrong_array = np.asarray(wrong, dtype=bool)
    unique, inverse = np.unique(ids, return_inverse=True)
    per_item = np.stack(
        [
            np.ones(ids.size, dtype=np.int64),
            wrong_array.astype(np.int64),
            accepted_array.astype(np.int64),
            (accepted_array & wrong_array).astype(np.int64),
        ],
        axis=1,
    )
    per_paper = np.zeros((unique.size, 4), dtype=np.int64)
    np.add.at(per_paper, inverse, per_item)
    draws = np.random.default_rng(seed).integers(0, unique.size, size=(resamples, unique.size))
    values = _metric_values(per_paper[draws].sum(axis=1), metric)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return None
    tail = (1 - level) / 2 * 100
    low, high = np.percentile(values, [tail, 100 - tail])
    return float(low), float(high)


@dataclass(frozen=True)
class FieldRun:
    """one field in one split: what calibration certified and how it did on test papers."""

    field: str
    group: FieldGroup
    result: ThresholdResult
    outcome: Outcome

    @property
    def certified(self) -> bool:
        """whether the field had a certified threshold."""
        return self.result.certified

    @property
    def pooled(self) -> bool:
        """whether its threshold came from its group's pooled records."""
        return self.result.pooled

    @property
    def threshold(self) -> float | None:
        """the certified threshold, or None."""
        return self.result.lambda_hat

    def with_outcome(self, new: Outcome) -> "FieldRun":
        """a copy with another test outcome."""
        return replace(self, outcome=new)


@dataclass(frozen=True, eq=False)
class SplitRun:
    """one random split: per-field results, the baselines, and the item-level decisions."""

    fields: dict[str, FieldRun]
    baselines: dict[str, Outcome]
    test: BoolArray
    """which items are on test papers (and of a known field)."""
    accepted: BoolArray
    """the method's decisions; False for items not on test papers."""

    def overall(self) -> Outcome:
        """the method's outcome on all test items."""
        return sum((run.outcome for run in self.fields.values()), EMPTY)

    def group(self, group: FieldGroup) -> Outcome:
        """the method's outcome on the test items of one field group."""
        return sum((run.outcome for run in self.fields.values() if run.group == group), EMPTY)


def run_split(
    items: Sequence[LabelledItem],
    scores: FloatArray,
    specs: Sequence[FieldSpec],
    split: PaperSplit,
    settings: CalibrationSettings,
    cutoff: float,
) -> SplitRun:
    """calibrate on the calibration papers' items, then decide and measure on the test papers'.

    the baselines are measured on the same test items: accept all, accept scores >= cutoff
    without calibration, and verify all (accept none).
    """
    columns = _columns(items, specs)
    calibration = columns.known & np.isin(columns.papers, list(split.calibration))
    test = columns.known & np.isin(columns.papers, list(split.test))
    thresholds = calibrate_fields(_records(items, scores, calibration), specs, settings)
    accepted, fields = _decide(columns, scores, specs, thresholds, test)
    wrong = columns.wrong[test]
    baselines = {
        "accept_all": outcome(np.ones(wrong.size, dtype=bool), wrong),
        "fixed_cutoff": outcome(scores[test] >= cutoff, wrong),
        "verify_all": outcome(np.zeros(wrong.size, dtype=bool), wrong),
    }
    return SplitRun(fields=fields, baselines=baselines, test=test, accepted=accepted)


def alpha_exceedances(runs: Iterable[FieldRun], alpha: float) -> tuple[int, int]:
    """(field runs with realised test error above alpha, certified field runs that accepted
    anything). the ratio overstates true violations, because test sets are small (ADR 0011)."""
    measured = [run.outcome for run in runs if run.certified and run.outcome.accepted > 0]
    above = sum((result.realised_error or 0.0) > alpha for result in measured)
    return above, len(measured)


@dataclass(frozen=True)
class CurvePoint:
    """the method on test papers after a number of audit records."""

    records: int
    outcome: Outcome


def updating_curve(
    items: Sequence[LabelledItem],
    scores: FloatArray,
    specs: Sequence[FieldSpec],
    split: PaperSplit,
    settings: CalibrationSettings,
    batch_size: int,
    seed: int,
) -> list[CurvePoint]:
    """audit batches drawn uniformly without replacement from the calibration papers' items,
    recalibrating on all audits so far after each batch (spec 11.1.6, ADR 0011)."""
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, got {batch_size}")
    columns = _columns(items, specs)
    test = columns.known & np.isin(columns.papers, list(split.test))
    pool: list[int] = np.flatnonzero(
        columns.known & np.isin(columns.papers, list(split.calibration))
    ).tolist()
    random.Random(seed).shuffle(pool)
    points = []
    for end in range(batch_size, len(pool) + batch_size, batch_size):
        audited = np.zeros(len(items), dtype=bool)
        audited[pool[:end]] = True
        thresholds = calibrate_fields(_records(items, scores, audited), specs, settings)
        _, fields = _decide(columns, scores, specs, thresholds, test)
        overall = sum((run.outcome for run in fields.values()), EMPTY)
        points.append(CurvePoint(records=min(end, len(pool)), outcome=overall))
    return points


@dataclass(frozen=True, eq=False)
class _Columns:
    papers: npt.NDArray[np.str_]
    fields: npt.NDArray[np.str_]
    wrong: BoolArray
    known: BoolArray


def _columns(items: Sequence[LabelledItem], specs: Sequence[FieldSpec]) -> _Columns:
    fields = np.array([item.field for item in items], dtype=str)
    return _Columns(
        papers=np.array([item.paper_id for item in items], dtype=str),
        fields=fields,
        wrong=np.array([item.wrong for item in items], dtype=bool),
        known=np.isin(fields, [spec.name for spec in specs]),
    )


def _decide(
    columns: _Columns,
    scores: FloatArray,
    specs: Sequence[FieldSpec],
    thresholds: dict[str, ThresholdResult],
    test: BoolArray,
) -> tuple[BoolArray, dict[str, FieldRun]]:
    # the deployed rule (exga.decide): accept when certified and score >= the threshold
    accepted = np.zeros(test.size, dtype=bool)
    runs = {}
    for spec in specs:
        result = thresholds[spec.name]
        mask = test & (columns.fields == spec.name)
        if result.lambda_hat is not None:
            accepted[mask] = scores[mask] >= result.lambda_hat
        runs[spec.name] = FieldRun(
            spec.name, spec.group, result, outcome(accepted[mask], columns.wrong[mask])
        )
    return accepted, runs


def _records(
    items: Sequence[LabelledItem], scores: FloatArray, chosen: BoolArray
) -> list[CalibrationRecord]:
    return [
        CalibrationRecord(
            paper_id=items[index].paper_id,
            field=items[index].field,
            group=items[index].group,
            score=float(scores[index]),
            wrong=items[index].wrong,
            source="benchmark",
            created_at=_RECORD_TIME,
        )
        for index in np.flatnonzero(chosen).tolist()
    ]


def _metric_values(counts: IntArray, metric: Metric) -> FloatArray:
    numerator, denominator = _RATIOS[metric](*counts.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = numerator / np.where(denominator > 0, denominator, 1)
    return np.where(denominator > 0, values, np.nan).astype(np.float64)
