import hashlib
from datetime import UTC, datetime
from random import Random

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy import stats

from exga.calibrate import (
    calibrate_fields,
    clopper_pearson_upper,
    fit_threshold,
    required_n,
    start_floor,
    threshold_grid,
)
from exga.errors import ConfigError
from exga.schemas import CalibrationRecord, FieldGroup, FieldSpec, ThresholdResult
from exga.settings import CalibrationSettings

GRID = threshold_grid(0.005)


def fit(
    scores: list[float] | np.ndarray,
    wrong: list[bool] | np.ndarray,
    *,
    alpha: float = 0.1,
    delta: float = 0.1,
    min_accepted: int = 10,
) -> ThresholdResult:
    return fit_threshold(
        np.asarray(scores, dtype=np.float64),
        np.asarray(wrong, dtype=np.bool_),
        grid=GRID,
        alpha=alpha,
        delta=delta,
        min_accepted=min_accepted,
        group="sample_size",
    )


def reference_fit(
    scores: list[float], wrong: list[bool], alpha: float, delta: float, floor: int
) -> tuple[float, int, int] | None:
    # spec 5.3 written as plainly as possible, one pass over the data per threshold
    certified = None
    for threshold in GRID:
        accepted = [
            is_wrong for score, is_wrong in zip(scores, wrong, strict=True) if score >= threshold
        ]
        n, errors = len(accepted), sum(accepted)
        if n < floor:
            continue
        if stats.binom.cdf(errors, n, alpha) > delta:
            break
        certified = (float(threshold), n, errors)
    return certified


def test_grid_runs_from_one_to_zero_in_fixed_steps() -> None:
    assert GRID.size == 201
    assert (GRID[0], GRID[-1]) == (1.0, 0.0)
    assert np.all(np.diff(GRID) < 0)
    assert 0.7 in GRID


@pytest.mark.parametrize(
    ("alpha", "errors", "expected"),
    [
        (0.05, 0, 45), (0.05, 1, 77), (0.05, 2, 105),
        (0.10, 0, 22), (0.10, 1, 38), (0.10, 2, 52),
        (0.20, 0, 11), (0.20, 1, 18), (0.20, 2, 25),
    ],
)  # fmt: skip
def test_required_n_reproduces_the_spec_table(alpha: float, errors: int, expected: int) -> None:
    assert required_n(alpha, 0.1, errors) == expected


@pytest.mark.parametrize(
    ("alpha", "delta", "errors"), [(0.0, 0.1, 0), (0.1, 1.0, 0), (0.1, 0.1, -1)]
)
def test_required_n_rejects_invalid_arguments(alpha: float, delta: float, errors: int) -> None:
    with pytest.raises(ValueError, match="required_n"):
        required_n(alpha, delta, errors)


def test_start_floor_is_the_larger_of_min_accepted_and_the_zero_error_minimum() -> None:
    assert start_floor(0.05, 0.1, 10) == 45
    assert start_floor(0.05, 0.1, 100) == 100


def test_clopper_pearson_upper_bound_has_the_closed_form_for_zero_errors() -> None:
    assert clopper_pearson_upper(0, 50, 0.1) == pytest.approx(1 - 0.1 ** (1 / 50))
    assert clopper_pearson_upper(50, 50, 0.1) == 1.0
    assert clopper_pearson_upper(1, 50, 0.1) < clopper_pearson_upper(2, 50, 0.1)


def test_all_correct_calibration_certifies_accepting_everything() -> None:
    scores = np.random.default_rng(0).uniform(size=200)

    result = fit(scores, np.zeros(200, dtype=bool), alpha=0.05)

    assert result.certified
    assert result.lambda_hat == 0.0
    assert (result.n_accepted_cal, result.errors_accepted_cal) == (200, 0)


def test_thresholds_too_small_to_certify_are_skipped_rather_than_ending_the_sequence() -> None:
    # spec 5.3 read literally (skip only below m_min = 10) would test the first threshold with
    # about 10 accepted items, which cannot pass at alpha = 0.05 (45 needed even with no
    # errors), and stop there: all-correct data would come out NOT_CERTIFIABLE. ADR 0004.
    scores = np.linspace(0.5, 1.0, 100)

    result = fit(scores, np.zeros(100, dtype=bool), alpha=0.05, min_accepted=10)

    assert result.certified
    assert result.n_accepted_cal >= required_n(0.05, 0.1, 0)


def test_all_wrong_calibration_is_not_certifiable_and_reports_the_raw_error_rate() -> None:
    result = fit(np.linspace(0, 1, 200), np.ones(200, dtype=bool))

    assert not result.certified
    assert (result.n_cal, result.errors_cal) == (200, 200)
    assert (result.lambda_hat, result.upper_bound, result.n_accepted_cal) == (None, None, 0)


def test_tied_scores_are_all_accepted_together() -> None:
    result = fit([0.9] * 100, [False] * 100)

    assert result.lambda_hat == 0.0
    assert result.n_accepted_cal == 100


def test_fewer_records_than_the_floor_cannot_certify() -> None:
    result = fit(np.linspace(0, 1, 30), np.zeros(30, dtype=bool), alpha=0.05)

    assert not result.certified
    assert result.n_cal == 30


def test_no_records_gives_an_uncertified_result() -> None:
    result = fit([], [])

    assert not result.certified
    assert (result.n_cal, result.errors_cal) == (0, 0)


def test_an_error_among_the_top_scores_can_end_the_sequence_early() -> None:
    # the power cost of fixed-sequence testing (ADR 0001): the first tested threshold accepts
    # the top 45 items and one of them is wrong, so the sequence stops before any certification
    scores = np.linspace(0.0, 1.0, 400)
    wrong = np.zeros(400, dtype=bool)
    wrong[-1] = True

    assert not fit(scores, wrong, alpha=0.05).certified


def test_errors_at_low_scores_set_the_threshold_above_them() -> None:
    scores = np.linspace(0.0, 1.0, 1000)
    wrong = scores < 0.3

    result = fit(scores, wrong, alpha=0.1)

    assert result.certified
    assert result.lambda_hat is not None
    assert 0.2 < result.lambda_hat <= 0.3
    assert result.upper_bound is not None
    assert result.upper_bound <= 0.1


def test_adding_a_correct_top_record_can_remove_certification() -> None:
    # documents why spec 0A.4's "adding a correct high-score record never removes
    # certification" does not hold once small thresholds are skipped (ADR 0004): the new record
    # lifts a skipped threshold to the floor, where its one error fails the first test.
    scores = [0.99] * 44 + [0.90] * 36
    wrong = [True] + [False] * 79
    before = fit(scores, wrong, alpha=0.05)

    after = fit([1.0, *scores], [False, *wrong], alpha=0.05)

    assert before.certified
    assert not after.certified


@pytest.mark.parametrize(
    ("scores", "wrong", "grid"),
    [
        ([0.5, 0.6], [False], GRID),
        ([[0.5]], [[False]], GRID),
        ([0.5, 1.2], [False, False], GRID),
        ([0.5, float("nan")], [False, False], GRID),
        ([0.5], [False], GRID[::-1]),
    ],
    ids=["length-mismatch", "two-dimensional", "out-of-range", "nan", "ascending-grid"],
)
def test_malformed_input_is_rejected(
    scores: list[float], wrong: list[bool], grid: np.ndarray
) -> None:
    with pytest.raises(ValueError, match="fit_threshold"):
        fit_threshold(
            np.asarray(scores, dtype=np.float64),
            np.asarray(wrong, dtype=np.bool_),
            grid=grid,
            alpha=0.1,
            delta=0.1,
            min_accepted=10,
            group="x",
        )


any_score = st.one_of(st.floats(0.0, 1.0), st.sampled_from([0.0, 0.5, 0.9, 0.995, 1.0]))


@st.composite
def calibration_sets(draw: st.DrawFn) -> tuple[list[float], list[bool]]:
    # half the examples are arbitrary small sets (edge cases, ties, all wrong); half are
    # realistic sets whose errors concentrate at low scores, so that many of them certify
    # and the properties about certified results are actually exercised
    if draw(st.booleans()):
        items = draw(st.lists(st.tuples(any_score, st.booleans()), max_size=60))
        return [score for score, _ in items], [is_wrong for _, is_wrong in items]
    rng = np.random.default_rng(draw(st.integers(0, 2**32 - 1)))
    n = draw(st.integers(50, 400))
    scores = rng.beta(draw(st.sampled_from([1.0, 3.0, 6.0])), 1.0, size=n)
    if draw(st.booleans()):
        scores = np.round(scores, 1)
    error_scale = draw(st.sampled_from([0.0, 0.05, 0.2]))
    wrong = rng.random(n) < error_scale * 2 * (1 - scores)
    return scores.tolist(), wrong.tolist()


alphas = st.sampled_from([0.05, 0.1, 0.2, 0.3])
deltas = st.sampled_from([0.05, 0.1, 0.2])


@given(calibration_sets(), alphas, deltas)
def test_matches_a_plain_reference_implementation(
    data: tuple[list[float], list[bool]], alpha: float, delta: float
) -> None:
    scores, wrong = data

    result = fit(scores, wrong, alpha=alpha, delta=delta)

    expected = reference_fit(scores, wrong, alpha, delta, start_floor(alpha, delta, 10))
    actual = (
        None
        if result.lambda_hat is None
        else (result.lambda_hat, result.n_accepted_cal, result.errors_accepted_cal)
    )
    assert actual == expected


@given(calibration_sets(), alphas, deltas)
def test_certified_results_respect_the_bound_and_lie_on_the_grid(
    data: tuple[list[float], list[bool]], alpha: float, delta: float
) -> None:
    result = fit(*data, alpha=alpha, delta=delta)

    if result.lambda_hat is None:
        return
    assert result.lambda_hat in GRID
    assert result.upper_bound is not None
    # binomial test and clopper-pearson bound are dual: certified <=> upper bound <= alpha
    assert result.upper_bound <= alpha + 1e-9
    assert result.errors_accepted_cal / result.n_accepted_cal <= result.upper_bound
    assert result.n_accepted_cal >= start_floor(alpha, delta, 10)


@given(calibration_sets(), alphas, st.randoms(use_true_random=False))
def test_result_does_not_depend_on_record_order(
    data: tuple[list[float], list[bool]], alpha: float, rng: Random
) -> None:
    pairs = list(zip(*data, strict=True))
    rng.shuffle(pairs)

    original = fit(*data, alpha=alpha)
    reordered = fit([s for s, _ in pairs], [w for _, w in pairs], alpha=alpha)

    assert original == reordered


@given(calibration_sets(), alphas, st.data())
def test_correcting_a_wrong_label_never_removes_certification(
    data: tuple[list[float], list[bool]], alpha: float, draw: st.DataObject
) -> None:
    scores, wrong = data
    wrong_positions = [i for i, is_wrong in enumerate(wrong) if is_wrong]
    if not wrong_positions:
        return
    flip = draw.draw(st.sampled_from(wrong_positions))
    corrected = [is_wrong and i != flip for i, is_wrong in enumerate(wrong)]

    before = fit(scores, wrong, alpha=alpha)
    after = fit(scores, corrected, alpha=alpha)

    if before.lambda_hat is not None:
        assert after.lambda_hat is not None
        assert after.lambda_hat <= before.lambda_hat


def paper_id(index: int) -> str:
    return hashlib.sha256(str(index).encode()).hexdigest()


def records(field: str, group: FieldGroup, n: int, *, start: int = 0) -> list[CalibrationRecord]:
    return [
        CalibrationRecord(
            paper_id=paper_id(start + i),
            field=field,
            group=group,
            score=(i + 1) / n,
            wrong=False,
            source="annotation",
            created_at=datetime(2026, 11, 25, tzinfo=UTC),
        )
        for i in range(n)
    ]


SPECS = [
    FieldSpec(name="sample_size", description="participants randomised", group="numeric"),
    FieldSpec(name="mean_age", description="mean age in years", group="numeric"),
    FieldSpec(name="country", description="country of data collection", group="short_text"),
]
SETTINGS = CalibrationSettings(alpha=0.1)


def test_a_field_with_enough_records_is_calibrated_on_its_own() -> None:
    results = calibrate_fields(records("sample_size", "numeric", 60), SPECS, SETTINGS)

    assert results["sample_size"].group == "sample_size"
    assert not results["sample_size"].pooled
    assert results["sample_size"].certified


def test_a_short_field_falls_back_to_its_pooled_group() -> None:
    pool = records("sample_size", "numeric", 60) + records("mean_age", "numeric", 5, start=100)

    results = calibrate_fields(pool, SPECS, SETTINGS)

    assert results["mean_age"].pooled
    assert results["mean_age"].group == "numeric"
    assert results["mean_age"].n_cal == 65
    assert not results["sample_size"].pooled


def test_a_short_field_alone_in_its_group_is_not_pooled() -> None:
    results = calibrate_fields(records("country", "short_text", 5), SPECS, SETTINGS)

    assert not results["country"].pooled
    assert not results["country"].certified
    assert results["country"].n_cal == 5


def test_every_specified_field_gets_a_result_and_unknown_fields_are_ignored() -> None:
    results = calibrate_fields(records("retired_field", "numeric", 60), SPECS, SETTINGS)

    assert set(results) == {"sample_size", "mean_age", "country"}
    assert results["mean_age"].n_cal == 0


def test_a_record_whose_group_disagrees_with_its_field_is_rejected() -> None:
    with pytest.raises(ConfigError, match="country"):
        calibrate_fields(records("country", "numeric", 5), SPECS, SETTINGS)


def test_required_n_is_the_smallest_passing_size_beyond_the_first_search_chunk() -> None:
    n = required_n(0.01, 0.1, 2)

    assert n > 256
    assert stats.binom.cdf(2, n, 0.01) <= 0.1 < stats.binom.cdf(2, n - 1, 0.01)


def test_short_fields_in_one_group_share_one_pooled_result() -> None:
    specs = [*SPECS, FieldSpec(name="year", description="publication year", group="numeric")]
    pool = (
        records("sample_size", "numeric", 60)
        + records("mean_age", "numeric", 5, start=100)
        + records("year", "numeric", 5, start=200)
    )

    results = calibrate_fields(pool, specs, SETTINGS)

    assert results["mean_age"] is results["year"]
    assert results["year"].n_cal == 70
