"""the guarantee simulation (spec 9.2) at CI size; `make verify-guarantee` runs the full grid."""

import numpy as np
import pytest

from exga.calibrate import threshold_grid
from exga.simulation import (
    CurvePopulation,
    Population,
    SimulationSummary,
    reference_populations,
    simulate_guarantee,
)

GRID = threshold_grid(0.005)
DELTA = 0.1
# allowance for monte carlo error over 1,000 repetitions (spec 9.2)
TOLERANCE = 0.02

POPULATIONS = reference_populations()
SPEC_POPULATION = POPULATIONS["power_beta_4_1_g1"]
TIED_POPULATION = POPULATIONS["discrete_ties"]
NON_MONOTONE_POPULATION = POPULATIONS["non_monotone_mid_band"]


def simulate(
    population: Population, *, n_cal: int, alpha: float, keep_wrong: float = 1.0
) -> SimulationSummary:
    return simulate_guarantee(
        population,
        n_cal=n_cal,
        repetitions=1000,
        alpha=alpha,
        delta=DELTA,
        grid=GRID,
        min_accepted=10,
        rng=np.random.default_rng(2026),
        keep_wrong=keep_wrong,
    )


@pytest.mark.parametrize("threshold", [0.0, 0.5, 0.8, 0.95, 0.999])
def test_closed_form_selective_error_matches_numerical_integration(threshold: float) -> None:
    integrated = CurvePopulation(a=4.0, b=1.0, p_wrong=lambda s: 1.0 - s)

    assert SPEC_POPULATION.selective_error(threshold) == pytest.approx(
        integrated.selective_error(threshold), abs=1e-8
    )


def test_selective_error_matches_a_large_sample() -> None:
    scores, wrong = SPEC_POPULATION.sample(np.random.default_rng(0), 400_000)

    empirical = wrong[scores >= 0.8].mean()

    assert empirical == pytest.approx(SPEC_POPULATION.selective_error(0.8), abs=0.003)


def test_discrete_selective_error_weights_levels_at_or_above_the_threshold() -> None:
    expected = (0.2 * 0.12 + 0.6 * 0.04) / 0.8

    assert TIED_POPULATION.selective_error(0.8) == pytest.approx(expected)
    assert TIED_POPULATION.selective_error(1.01) == 0.0


@pytest.mark.parametrize(
    ("population", "n_cal"),
    [(SPEC_POPULATION, 500), (TIED_POPULATION, 200), (NON_MONOTONE_POPULATION, 300)],
    ids=["spec-power-beta", "heavy-ties", "non-monotone"],
)
def test_certified_thresholds_break_the_bound_at_most_delta_of_the_time(
    population: Population, n_cal: int
) -> None:
    summary = simulate(population, n_cal=n_cal, alpha=0.1)

    assert summary.violation_rate <= DELTA + TOLERANCE
    # the check means something only if certification actually happens
    assert summary.certified_rate >= 0.5


def test_biased_calibration_data_breaks_the_guarantee() -> None:
    # spec 5.6: values people chose to check are not a random sample. dropping half of the
    # wrong ones makes the model look better than it is, and the bound fails far beyond delta
    summary = simulate(SPEC_POPULATION, n_cal=500, alpha=0.1, keep_wrong=0.5)

    assert summary.violation_rate > 0.5


@pytest.mark.parametrize("name", ["power_beta_4_1_g1", "non_monotone_mid_band"])
def test_selective_error_is_zero_where_no_score_can_reach(name: str) -> None:
    assert POPULATIONS[name].selective_error(1.0) == 0.0


@pytest.mark.parametrize("name", sorted(POPULATIONS))
def test_reference_populations_sample_valid_scores_and_some_errors(name: str) -> None:
    scores, wrong = POPULATIONS[name].sample(np.random.default_rng(1), 2000)

    assert scores.min() >= 0.0
    assert scores.max() <= 1.0
    assert 0.0 < wrong.mean() < 1.0
