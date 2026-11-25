"""audit-loop simulation (spec 5.6, ADR 0009): 1,000 repetitions of 10 audit rounds each.

each round brings 400 new items, audits 5% of them and recalibrates. random audits must keep
the per-version violation rate within delta + 0.02; logging wrong values half as often as
right ones (keep_wrong = 0.5) shows what biased records do. the share of repetitions in which
any version was ever violated is reported too: it measures repeated testing and is not
bounded by delta. writes results/audit_simulation.csv; exits with 1 if random audits fail.
run with: make verify-guarantee
"""

import csv
import sys
from pathlib import Path

import numpy as np

from exga.calibrate import threshold_grid
from exga.settings import AuditSettings
from exga.simulation import reference_populations, simulate_audit_loop

REPETITIONS = 1000
ROUNDS = 10
ITEMS_PER_ROUND = 400
ALPHA = 0.10
DELTA = 0.1
TOLERANCE = 0.02
SEED = 2027
KEEP_WRONG = (1.0, 0.5)
OUTPUT = Path("results/audit_simulation.csv")


def main() -> int:
    """run every configuration, write the csv, and return the process exit status."""
    grid = threshold_grid(0.005)
    rows = []
    failures = []
    for index, (name, population) in enumerate(reference_populations().items()):
        for keep_wrong in KEEP_WRONG:
            seed = SEED + 100 * index + int(keep_wrong * 10)
            summary = simulate_audit_loop(
                population,
                rounds=ROUNDS,
                items_per_round=ITEMS_PER_ROUND,
                audit_settings=AuditSettings(),
                repetitions=REPETITIONS,
                alpha=ALPHA,
                delta=DELTA,
                grid=grid,
                min_accepted=10,
                rng=np.random.default_rng(seed),
                keep_wrong=keep_wrong,
            )
            policy = "random audit" if keep_wrong == 1.0 else f"wrong logged at {keep_wrong}"
            rows.append(
                {
                    "population": name,
                    "policy": policy,
                    "alpha": ALPHA,
                    "delta": DELTA,
                    "rounds": ROUNDS,
                    "items_per_round": ITEMS_PER_ROUND,
                    "repetitions": REPETITIONS,
                    "seed": seed,
                    "certified_versions": summary.certified_versions,
                    "version_violation_rate": round(summary.version_violation_rate, 4),
                    "ever_violated_rate": round(summary.ever_violated_rate, 4),
                }
            )
            if keep_wrong == 1.0 and summary.version_violation_rate > DELTA + TOLERANCE:
                failures.append(name)
            print(
                f"{name:24} {policy:22} versions violated={summary.version_violation_rate:.3f} "
                f"ever violated={summary.ever_violated_rate:.3f}"
            )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUTPUT}; random audits within delta + {TOLERANCE}: {not failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
