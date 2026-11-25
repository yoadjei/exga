"""ADR 0009 in CI: random audits keep each threshold version's guarantee; label-dependent
logging breaks it. the full run is scripts/verify_audit.py (make verify-guarantee)."""

import numpy as np
import pytest

from exga.calibrate import threshold_grid
from exga.settings import AuditSettings
from exga.simulation import (
    AuditSimulationSummary,
    PowerBetaPopulation,
    simulate_audit_loop,
)

GRID = threshold_grid(0.005)
POPULATION = PowerBetaPopulation(a=4.0, b=1.0, gamma=1.0)


def run(keep_wrong: float, seed: int) -> AuditSimulationSummary:
    return simulate_audit_loop(
        POPULATION,
        rounds=8,
        items_per_round=400,
        audit_settings=AuditSettings(),
        repetitions=250,
        alpha=0.1,
        delta=0.1,
        grid=GRID,
        min_accepted=10,
        rng=np.random.default_rng(seed),
        keep_wrong=keep_wrong,
    )


def test_random_audits_keep_each_version_within_delta() -> None:
    summary = run(keep_wrong=1.0, seed=11)

    assert summary.certified_versions > 0
    assert summary.version_violation_rate <= 0.1 + 0.02


def test_logging_errors_less_often_breaks_the_guarantee() -> None:
    random_audit = run(keep_wrong=1.0, seed=12)
    biased = run(keep_wrong=0.5, seed=12)

    assert biased.version_violation_rate > 0.1 + 0.05
    assert biased.version_violation_rate > 3 * random_audit.version_violation_rate


def test_a_long_log_is_more_often_violated_somewhere_than_any_one_version() -> None:
    summary = run(keep_wrong=1.0, seed=13)

    assert summary.ever_violated_rate >= summary.version_violation_rate
    assert summary.versions == 8 * 250


def test_the_rates_are_shares_of_versions_and_of_repetitions() -> None:
    summary = AuditSimulationSummary(
        repetitions=10,
        versions=40,
        certified_versions=30,
        violated_versions=4,
        repetitions_ever_violated=3,
    )

    assert (summary.version_violation_rate, summary.ever_violated_rate) == pytest.approx((0.1, 0.3))
