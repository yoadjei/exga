"""synthetic calibration data with a known selective-error curve, to check the guarantee.

used by the guarantee simulation (spec 9.2) and `make verify-guarantee`. pure: callers pass a
numpy Generator, so every run is reproducible. each population can both sample (score, wrong)
pairs and report its true selective error r(t) = P(wrong | s >= t).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy import integrate, special, stats

from exga.calibrate import BoolArray, FloatArray, fit_threshold


class Population(Protocol):
    """a distribution of (score, wrong) pairs whose selective error is known exactly."""

    def sample(self, rng: np.random.Generator, n: int) -> tuple[FloatArray, BoolArray]:
        """return n independent (score, wrong) pairs."""

    def selective_error(self, threshold: float) -> float:
        """return P(wrong | score >= threshold); 0.0 when no score reaches threshold."""


@dataclass(frozen=True)
class PowerBetaPopulation:
    """scores ~ Beta(a, b) and P(wrong | s) = 1 - s**gamma, so errors fall as scores rise.

    the population shape named in spec 9.2.
    """

    a: float
    b: float
    gamma: float

    def sample(self, rng: np.random.Generator, n: int) -> tuple[FloatArray, BoolArray]:
        """return n independent (score, wrong) pairs."""
        scores = rng.beta(self.a, self.b, size=n)
        return scores, rng.random(n) < 1.0 - scores**self.gamma

    def selective_error(self, threshold: float) -> float:
        """return the exact selective error at threshold."""
        tail = float(stats.beta.sf(threshold, self.a, self.b))
        if tail == 0.0:
            return 0.0
        # E[s^g 1{s >= t}] = B(a + g, b) / B(a, b) * P(Beta(a + g, b) >= t)
        log_moment = special.betaln(self.a + self.gamma, self.b) - special.betaln(self.a, self.b)
        moment = float(np.exp(log_moment))
        tail_moment = moment * float(stats.beta.sf(threshold, self.a + self.gamma, self.b))
        return 1.0 - tail_moment / tail


@dataclass(frozen=True)
class CurvePopulation:
    """scores ~ Beta(a, b) with any P(wrong | s), e.g. a non-monotone one; r(t) by integration.

    breakpoints lists where p_wrong jumps, so the integrator does not step over them.
    """

    a: float
    b: float
    p_wrong: Callable[[float], float]
    breakpoints: tuple[float, ...] = ()

    def sample(self, rng: np.random.Generator, n: int) -> tuple[FloatArray, BoolArray]:
        """return n independent (score, wrong) pairs."""
        scores = rng.beta(self.a, self.b, size=n)
        p = np.array([self.p_wrong(float(score)) for score in scores], dtype=np.float64)
        return scores, rng.random(n) < p

    def selective_error(self, threshold: float) -> float:
        """return the selective error at threshold, integrated numerically."""
        tail = float(stats.beta.sf(threshold, self.a, self.b))
        if tail == 0.0:
            return 0.0
        points = [point for point in self.breakpoints if threshold < point < 1.0]
        errors, _ = integrate.quad(
            lambda s: self.p_wrong(s) * stats.beta.pdf(s, self.a, self.b),
            threshold,
            1.0,
            points=points or None,
            limit=200,
        )
        return float(errors) / tail


@dataclass(frozen=True)
class DiscretePopulation:
    """scores take a few fixed levels, as agreement scores do, so ties are the norm."""

    levels: tuple[float, ...]
    weights: tuple[float, ...]
    p_wrong: tuple[float, ...]

    def sample(self, rng: np.random.Generator, n: int) -> tuple[FloatArray, BoolArray]:
        """return n independent (score, wrong) pairs."""
        index = rng.choice(len(self.levels), size=n, p=np.asarray(self.weights) / sum(self.weights))
        return np.asarray(self.levels)[index], rng.random(n) < np.asarray(self.p_wrong)[index]

    def selective_error(self, threshold: float) -> float:
        """return the exact selective error at threshold."""
        mask = np.asarray(self.levels) >= threshold
        weights = np.asarray(self.weights)[mask]
        if weights.sum() == 0:
            return 0.0
        return float(np.dot(weights, np.asarray(self.p_wrong)[mask]) / weights.sum())


# reference scenarios for the guarantee simulation. two are deliberately adversarial, with
# P(wrong | s) not monotone in s, so validity is not checked only where the argument in
# ADR 0004 applies: errors concentrated in a band of middling scores, and a few
# overconfident errors at the very top
_BASE_ERROR = 0.02
_MID_BAND = (0.8, 0.9)
_MID_BAND_ERROR = 0.25
_TOP_BAND = 0.995
_TOP_BAND_ERROR = 0.3


def _mid_band_errors(score: float) -> float:
    return _MID_BAND_ERROR if _MID_BAND[0] < score <= _MID_BAND[1] else _BASE_ERROR


def _top_band_errors(score: float) -> float:
    return _TOP_BAND_ERROR if score > _TOP_BAND else _BASE_ERROR


def reference_populations() -> dict[str, Population]:
    """return the named populations used by the guarantee tests and `make verify-guarantee`."""
    return {
        "power_beta_4_1_g1": PowerBetaPopulation(4.0, 1.0, 1.0),
        "power_beta_8_1_g3": PowerBetaPopulation(8.0, 1.0, 3.0),
        "discrete_ties": DiscretePopulation(
            levels=(0.2, 0.4, 0.6, 0.8, 1.0),
            weights=(0.05, 0.05, 0.1, 0.2, 0.6),
            p_wrong=(0.7, 0.5, 0.3, 0.12, 0.04),
        ),
        "non_monotone_mid_band": CurvePopulation(4.0, 1.0, _mid_band_errors, _MID_BAND),
        "non_monotone_top_band": CurvePopulation(5.0, 1.0, _top_band_errors, (_TOP_BAND,)),
    }


@dataclass(frozen=True)
class SimulationSummary:
    """how often certification happened, and how often a certified threshold broke the bound."""

    repetitions: int
    certified: int
    violations: int

    @property
    def violation_rate(self) -> float:
        """share of repetitions whose certified threshold has true selective error above alpha."""
        return self.violations / self.repetitions

    @property
    def certified_rate(self) -> float:
        """share of repetitions that certified any threshold."""
        return self.certified / self.repetitions


def simulate_guarantee(
    population: Population,
    *,
    n_cal: int,
    repetitions: int,
    alpha: float,
    delta: float,
    grid: FloatArray,
    min_accepted: int,
    rng: np.random.Generator,
    keep_wrong: float = 1.0,
) -> SimulationSummary:
    """estimate P(r(lambda_hat) > alpha) by repeated calibration on fresh samples (spec 9.2).

    an uncertified run makes no claim, so it is not a violation. keep_wrong < 1 simulates biased
    calibration data: each wrong item is kept only with that probability, as when people record
    the values they happened to check and found right (spec 5.6).
    """
    certified = violations = 0
    for _ in range(repetitions):
        scores, wrong = population.sample(rng, n_cal)
        if keep_wrong < 1.0:
            kept = ~wrong | (rng.random(n_cal) < keep_wrong)
            scores, wrong = scores[kept], wrong[kept]
        result = fit_threshold(
            scores,
            wrong,
            grid=grid,
            alpha=alpha,
            delta=delta,
            min_accepted=min_accepted,
            group="sim",
        )
        if result.lambda_hat is not None:
            certified += 1
            violations += population.selective_error(result.lambda_hat) > alpha
    return SimulationSummary(repetitions=repetitions, certified=certified, violations=violations)
