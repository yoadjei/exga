"""metrics, baselines, intervals, splits and updating curves for the experiments (ADR 0011)."""

import numpy as np
import pytest

from exga.evaluate import (
    LabelledItem,
    Outcome,
    alpha_exceedances,
    bootstrap_interval,
    outcome,
    run_split,
    updating_curve,
)
from exga.schemas import FieldSpec, Signals
from exga.settings import CalibrationSettings
from exga.splits import PaperSplit

SETTINGS = CalibrationSettings(alpha=0.2, delta=0.1)
SAMPLE_SIZE = FieldSpec(name="sample_size", description="n", group="numeric")
EVENTS = FieldSpec(name="events", description="events", group="numeric")


def test_outcome_counts_and_rates() -> None:
    result = outcome(
        accepted=[True, True, True, False, False], wrong=[False, False, True, True, False]
    )

    assert result == Outcome(items=5, wrong=2, accepted=3, wrong_accepted=1)
    assert result.raw_accuracy == pytest.approx(0.6)
    assert result.acceptance_rate == pytest.approx(0.6)
    assert result.realised_error == pytest.approx(1 / 3)
    assert result.coverage == pytest.approx(2 / 3)


def test_rates_without_a_denominator_are_undefined() -> None:
    nothing_accepted = outcome(accepted=[False, False], wrong=[True, True])
    empty = outcome(accepted=[], wrong=[])

    assert (nothing_accepted.realised_error, nothing_accepted.coverage) == (None, None)
    assert (empty.raw_accuracy, empty.acceptance_rate) == (None, None)


def test_outcomes_add_up() -> None:
    total = Outcome(4, 1, 2, 0) + Outcome(6, 2, 3, 1)

    assert total == Outcome(items=10, wrong=3, accepted=5, wrong_accepted=1)


def test_a_bootstrap_interval_contains_the_estimate_and_is_reproducible() -> None:
    rng = np.random.default_rng(1)
    papers = [f"p{index // 3}" for index in range(90)]  # 30 papers, 3 items each
    accepted = rng.random(90) < 0.7
    wrong = rng.random(90) < 0.2
    estimate = outcome(accepted, wrong).realised_error
    assert estimate is not None

    interval = bootstrap_interval(papers, accepted, wrong, "realised_error", resamples=500, seed=3)

    assert interval is not None
    low, high = interval
    assert low <= estimate <= high
    assert interval == bootstrap_interval(papers, accepted, wrong, "realised_error", 500, seed=3)


def test_resampling_papers_widens_intervals_when_errors_cluster_in_papers() -> None:
    # every item of a paper is wrong or every item is right: 10 papers, not 100 items, vary
    papers = [f"p{index // 10}" for index in range(100)]
    wrong = np.array([index // 10 < 3 for index in range(100)])
    accepted = np.ones(100, dtype=bool)
    by_paper = bootstrap_interval(papers, accepted, wrong, "realised_error", 2000, seed=0)
    by_item = bootstrap_interval(
        [str(i) for i in range(100)], accepted, wrong, "realised_error", 2000, seed=0
    )

    assert by_paper is not None
    assert by_item is not None
    assert by_paper[1] - by_paper[0] > 1.5 * (by_item[1] - by_item[0])


def test_an_interval_that_is_never_defined_is_none() -> None:
    interval = bootstrap_interval(
        ["a", "b"], [False, False], [True, False], "realised_error", 100, seed=0
    )

    assert interval is None


def labelled(n_papers: int, *, wrong_below: float) -> tuple[list[LabelledItem], np.ndarray]:
    """two fields per paper; scores spread over [0, 1]; items scoring below wrong_below are
    wrong, so a well-chosen threshold separates them."""
    items, scores = [], []
    for paper in range(n_papers):
        for field_index, spec in enumerate((SAMPLE_SIZE, EVENTS)):
            score = ((paper * 7 + field_index * 3) % 100) / 100
            items.append(
                LabelledItem(
                    paper_id=f"{paper:064x}",
                    field=spec.name,
                    group="numeric",
                    signals=Signals(agreement=score),
                    wrong=score < wrong_below,
                )
            )
            scores.append(score)
    return items, np.array(scores)


def split_of(items: list[LabelledItem], n_train: int, n_calibration: int) -> PaperSplit:
    papers = sorted({item.paper_id for item in items})
    return PaperSplit(
        train=frozenset(papers[:n_train]),
        calibration=frozenset(papers[n_train : n_train + n_calibration]),
        test=frozenset(papers[n_train + n_calibration :]),
    )


def test_a_split_certifies_on_calibration_papers_and_is_measured_on_test_papers() -> None:
    items, scores = labelled(300, wrong_below=0.3)
    split = split_of(items, 90, 120)

    run = run_split(items, scores, [SAMPLE_SIZE, EVENTS], split, SETTINGS, cutoff=0.8)

    result = run.fields["sample_size"]
    assert result.certified
    assert result.threshold is not None
    assert result.outcome.items == 90  # one item per test paper
    # the threshold may move below the clean scores while the test still passes, so some
    # errors are accepted, but no more than alpha on test papers like the calibration ones
    error = result.outcome.realised_error
    assert error is not None
    assert error <= SETTINGS.alpha
    assert run.overall().items == 180
    assert set(run.baselines) == {"accept_all", "fixed_cutoff", "verify_all"}
    assert run.baselines["accept_all"].acceptance_rate == 1.0
    assert run.baselines["verify_all"].accepted == 0
    assert run.baselines["fixed_cutoff"].accepted == int(np.sum(scores[run.test] >= 0.8))
    assert run.test.sum() == 180


def test_alpha_exceedances_count_certified_fields_that_accepted_something() -> None:
    clean, clean_scores = labelled(300, wrong_below=0.3)
    run = run_split(
        clean, clean_scores, [SAMPLE_SIZE, EVENTS], split_of(clean, 90, 120), SETTINGS, 0.8
    )
    run.fields["events"] = run.fields["events"].with_outcome(Outcome(10, 5, 10, 5))

    above, counted = alpha_exceedances([run], alpha=0.2)

    assert (above, counted) == (1, 2)


def test_the_updating_curve_adds_one_audit_batch_at_a_time() -> None:
    items, scores = labelled(300, wrong_below=0.3)
    split = split_of(items, 90, 120)

    curve = updating_curve(
        items, scores, [SAMPLE_SIZE, EVENTS], split, SETTINGS, batch_size=10, seed=0
    )

    assert [point.records for point in curve] == list(range(10, 241, 10))
    assert all(point.outcome.items == 180 for point in curve)
    # 10 records, even pooled, are fewer than the 11 that alpha 0.2 needs with no errors
    assert curve[0].outcome.accepted == 0
    assert curve[-1].outcome.accepted > 0
    error = curve[-1].outcome.realised_error
    assert error is not None
    assert error <= SETTINGS.alpha
