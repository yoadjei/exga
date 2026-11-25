"""benchmark of the core path against the budget in spec 0A.5.

budget: scoring, calibration and decision for 10,000 items in under one second. P1 measures
calibration; later phases add scoring and decision to the same timing. run with: make bench
"""

import statistics
import sys
import time

import numpy as np

from exga.calibrate import fit_threshold, threshold_grid

N_ITEMS = 10_000
RUNS = 20
BUDGET_S = 1.0


def main() -> int:
    """time the core path, print the median, and return 1 if it misses the budget."""
    rng = np.random.default_rng(0)
    scores = rng.beta(4.0, 1.0, size=N_ITEMS)
    wrong = rng.random(N_ITEMS) < 1.0 - scores
    grid = threshold_grid(0.005)
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        fit_threshold(
            scores, wrong, grid=grid, alpha=0.1, delta=0.1, min_accepted=10, group="bench"
        )
        timings.append(time.perf_counter() - start)
    median_s = statistics.median(timings)
    print(f"calibration of {N_ITEMS:,} items: median {median_s * 1000:.2f} ms over {RUNS} runs")
    print(f"budget {BUDGET_S:.1f} s: {'met' if median_s < BUDGET_S else 'MISSED'}")
    return 0 if median_s < BUDGET_S else 1


if __name__ == "__main__":
    sys.exit(main())
