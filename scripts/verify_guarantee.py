"""full guarantee simulation (spec 9.2): 1,000 repetitions per configuration.

writes results/guarantee_simulation.csv and prints a table. exits with status 1 if any
configuration's violation rate exceeds delta + 0.02. run with: make verify-guarantee
"""

import csv
import sys
from pathlib import Path

import numpy as np

from exga.calibrate import threshold_grid
from exga.simulation import reference_populations, simulate_guarantee

REPETITIONS = 1000
DELTA = 0.1
TOLERANCE = 0.02
SEED = 2026
ALPHAS = (0.05, 0.10, 0.20)
CALIBRATION_SIZES = (200, 1000)
OUTPUT = Path("results/guarantee_simulation.csv")


def main() -> int:
    """run every configuration, write the csv, and return the process exit status."""
    grid = threshold_grid(0.005)
    rows = []
    for config_index, (name, population) in enumerate(reference_populations().items()):
        for alpha in ALPHAS:
            for n_cal in CALIBRATION_SIZES:
                seed = SEED + 1000 * config_index + int(alpha * 100) + n_cal
                summary = simulate_guarantee(
                    population,
                    n_cal=n_cal,
                    repetitions=REPETITIONS,
                    alpha=alpha,
                    delta=DELTA,
                    grid=grid,
                    min_accepted=10,
                    rng=np.random.default_rng(seed),
                )
                rows.append(
                    {
                        "population": name,
                        "alpha": alpha,
                        "delta": DELTA,
                        "n_cal": n_cal,
                        "repetitions": REPETITIONS,
                        "seed": seed,
                        "certified_rate": round(summary.certified_rate, 4),
                        "violation_rate": round(summary.violation_rate, 4),
                        "passes": summary.violation_rate <= DELTA + TOLERANCE,
                    }
                )
                print(
                    f"{name:24} alpha={alpha:.2f} n={n_cal:5d} "
                    f"certified={summary.certified_rate:.3f} "
                    f"violations={summary.violation_rate:.3f}"
                )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if not row["passes"]]
    passed = len(rows) - len(failures)
    print(f"wrote {OUTPUT}; {passed}/{len(rows)} configurations within delta + {TOLERANCE}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
