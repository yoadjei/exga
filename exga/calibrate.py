"""certify a score threshold per field with fixed-sequence binomial testing (spec 5.3, 5.4).

pure: arrays or records in, `ThresholdResult` out. the method is in ADR 0001; the starting
floor that keeps it usable at small alpha is in ADR 0004; per-field calibration with a pooled
fallback is in ADR 0005.
"""

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy import stats

from exga.errors import ConfigError
from exga.schemas import CalibrationRecord, FieldGroup, FieldSpec, ThresholdResult
from exga.settings import CalibrationSettings

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.int64]

# grid values are rounded so a threshold such as 0.7 equals the float a score of 0.7 parses to
_GRID_DECIMALS = 12
# first chunk of sample sizes searched by required_n; doubles until a size passes
_REQUIRED_N_CHUNK = 256


def threshold_grid(step: float) -> FloatArray:
    """return the fixed grid 1, 1 - step, ..., 0, strictest first.

    built from settings alone, never from data: a data-dependent grid breaks the
    fixed-sequence argument (spec 5.3). step must divide 1, as `CalibrationSettings` checks.
    """
    n_steps = round(1.0 / step)
    return np.round(np.linspace(1.0, 0.0, n_steps + 1), _GRID_DECIMALS)


def required_n(alpha: float, delta: float, errors: int) -> int:
    """return the fewest accepted items, `errors` of them wrong, that can certify alpha at delta.

    the smallest n with BinomCDF(errors; n, alpha) <= delta (spec 5.4a). raises ValueError
    unless 0 < alpha < 1, 0 < delta < 1 and errors >= 0.
    """
    if not (0 < alpha < 1 and 0 < delta < 1 and errors >= 0):
        raise ValueError(
            f"required_n needs 0 < alpha, delta < 1 and errors >= 0; got {alpha}, {delta}, {errors}"
        )
    start, size = errors + 1, _REQUIRED_N_CHUNK
    while True:
        sizes = np.arange(start, start + size)
        # the cdf falls as n grows, so the first passing size is the smallest
        passing = np.flatnonzero(stats.binom.cdf(errors, sizes, alpha) <= delta)
        if passing.size:
            return int(sizes[passing[0]])
        start, size = start + size, size * 2


def start_floor(alpha: float, delta: float, min_accepted: int) -> int:
    """return the fewest accepted calibration items at which a threshold is tested (ADR 0004).

    a threshold accepting fewer than required_n(alpha, delta, 0) items cannot be certified
    whatever its labels, so testing it could only end the sequence early; it is skipped.
    """
    return max(min_accepted, required_n(alpha, delta, 0))


def clopper_pearson_upper(errors: int, n: int, delta: float) -> float:
    """return the one-sided (1 - delta) clopper-pearson upper bound on an error rate.

    for display: computed at a threshold chosen from the same data, it describes the
    calibration set and is not a second guarantee (ADR 0001).
    """
    if errors >= n:
        return 1.0
    return float(stats.beta.ppf(1.0 - delta, errors + 1, n - errors))


def fit_threshold(
    scores: FloatArray,
    wrong: BoolArray,
    *,
    grid: FloatArray,
    alpha: float,
    delta: float,
    min_accepted: int,
    group: str,
    pooled: bool = False,
) -> ThresholdResult:
    """return the lowest grid threshold certified to keep selective error at most alpha.

    scores and wrong are aligned 1-d arrays, one entry per calibration item; grid comes from
    `threshold_grid`. an uncertified result is a normal outcome, not an error. raises
    ValueError on malformed input.
    """
    _check_inputs(scores, wrong, grid)
    n_accepted, errors_accepted = _accepted_counts(scores, wrong, grid)
    floor = start_floor(alpha, delta, min_accepted)
    index = _last_certified(n_accepted, errors_accepted, alpha, delta, floor)
    certified = index is not None
    n = int(n_accepted[index]) if index is not None else 0
    errors = int(errors_accepted[index]) if index is not None else 0
    return ThresholdResult(
        group=group,
        method="fixed_sequence",
        pooled=pooled,
        alpha=alpha,
        delta=delta,
        n_cal=int(scores.size),
        errors_cal=int(wrong.sum()),
        certified=certified,
        lambda_hat=float(grid[index]) if index is not None else None,
        n_accepted_cal=n,
        errors_accepted_cal=errors,
        upper_bound=clopper_pearson_upper(errors, n, delta) if certified else None,
    )


def _check_inputs(scores: FloatArray, wrong: BoolArray, grid: FloatArray) -> None:
    if scores.ndim != 1 or scores.shape != wrong.shape:
        raise ValueError(
            f"fit_threshold needs aligned 1-d arrays, got {scores.shape} and {wrong.shape}"
        )
    if scores.size and not (np.all(scores >= 0.0) and np.all(scores <= 1.0)):
        raise ValueError("fit_threshold needs scores in [0, 1] with no NaN")
    if grid.ndim != 1 or not np.all(np.diff(grid) < 0):
        raise ValueError("fit_threshold needs a strictly descending grid")


def _accepted_counts(
    scores: FloatArray, wrong: BoolArray, grid: FloatArray
) -> tuple[IntArray, IntArray]:
    # sort once, strictest first: every threshold accepts a prefix of that order, so the
    # error counts for all thresholds come from one cumulative sum, o(n log n + g log n)
    order = np.argsort(-scores, kind="stable")
    errors_in_prefix = np.concatenate(([0], np.cumsum(wrong[order], dtype=np.int64)))
    n_accepted = scores.size - np.searchsorted(np.sort(scores), grid, side="left")
    return n_accepted.astype(np.int64), errors_in_prefix[n_accepted]


def _last_certified(
    n_accepted: IntArray, errors_accepted: IntArray, alpha: float, delta: float, floor: int
) -> int | None:
    # fixed-sequence testing, angelopoulos et al. (2025): walk the grid strictest first, skip
    # thresholds below the floor, certify while p <= delta and stop at the first failure.
    # p = BinomCDF(e; n, alpha) tests H0: selective error > alpha (spec 5.3).
    is_tested = n_accepted >= floor
    p_values = stats.binom.cdf(errors_accepted, n_accepted, alpha)
    fails = is_tested & (p_values > delta)
    stop = int(np.argmax(fails)) if fails.any() else fails.size
    certified = np.flatnonzero(is_tested[:stop])
    return int(certified[-1]) if certified.size else None


def calibrate_fields(
    records: Sequence[CalibrationRecord],
    specs: Sequence[FieldSpec],
    settings: CalibrationSettings,
) -> dict[str, ThresholdResult]:
    """return a ThresholdResult for every field in specs (spec 5.4, ADR 0005).

    a field with at least the starting floor of records is calibrated on its own records;
    otherwise on all records of its field group, labelled pooled. the choice depends only on
    record counts, never on labels. records of fields not in specs are ignored. raises
    ConfigError when a record's group disagrees with its field's spec.
    """
    by_field = _records_by_field(records, specs)
    floor = start_floor(settings.alpha, settings.delta, settings.min_accepted)
    pooled_results: dict[FieldGroup, ThresholdResult] = {}
    results: dict[str, ThresholdResult] = {}
    for spec in specs:
        own = by_field[spec.name]
        group_records = [
            r for other in specs if other.group == spec.group for r in by_field[other.name]
        ]
        if len(own) >= floor or len(group_records) == len(own):
            results[spec.name] = _fit_records(own, spec.name, pooled=False, settings=settings)
            continue
        if spec.group not in pooled_results:
            pooled_results[spec.group] = _fit_records(
                group_records, spec.group, pooled=True, settings=settings
            )
        results[spec.name] = pooled_results[spec.group]
    return results


def _records_by_field(
    records: Sequence[CalibrationRecord], specs: Sequence[FieldSpec]
) -> dict[str, list[CalibrationRecord]]:
    groups = {spec.name: spec.group for spec in specs}
    by_field: dict[str, list[CalibrationRecord]] = defaultdict(list)
    for record in records:
        if record.field not in groups:
            continue
        if record.group != groups[record.field]:
            raise ConfigError(
                f"record for field {record.field} has group {record.group}, "
                f"but the field spec says {groups[record.field]}"
            )
        by_field[record.field].append(record)
    return by_field


def _fit_records(
    records: Sequence[CalibrationRecord], name: str, *, pooled: bool, settings: CalibrationSettings
) -> ThresholdResult:
    return fit_threshold(
        np.array([record.score for record in records], dtype=np.float64),
        np.array([record.wrong for record in records], dtype=np.bool_),
        grid=threshold_grid(settings.grid_step),
        alpha=settings.alpha,
        delta=settings.delta,
        min_accepted=settings.min_accepted,
        group=name,
        pooled=pooled,
    )
