"""benchmarks of the budgets in spec 0A.5. run with: make bench

- scoring, calibration and decision for 10,000 items in under one second. P1 measures
  calibration; later phases add scoring and decision to the same timing.
- loading a typical 20-page paper in under one second. the paper is synthetic: 20 pages of
  about 600 words each, a dense two-column article's worth of text.
"""

import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pymupdf

from exga.calibrate import fit_threshold, threshold_grid
from exga.pdf import load_pdf
from exga.settings import DocumentSettings

N_ITEMS = 10_000
N_PAGES = 20
LINES_PER_PAGE = 60
WORDS_PER_LINE = 10
RUNS = 20
BUDGET_S = 1.0


def _median_seconds(task: Callable[[], object]) -> float:
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        task()
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


def _report(label: str, median_s: float) -> bool:
    met = median_s < BUDGET_S
    print(f"{label}: median {median_s * 1000:.1f} ms over {RUNS} runs")
    print(f"  budget {BUDGET_S:.1f} s: {'met' if met else 'MISSED'}")
    return met


def bench_calibration() -> bool:
    """time fit_threshold on N_ITEMS synthetic scores."""
    rng = np.random.default_rng(0)
    scores = rng.beta(4.0, 1.0, size=N_ITEMS)
    wrong = rng.random(N_ITEMS) < 1.0 - scores
    grid = threshold_grid(0.005)
    median_s = _median_seconds(
        lambda: fit_threshold(
            scores, wrong, grid=grid, alpha=0.1, delta=0.1, min_accepted=10, group="bench"
        )
    )
    return _report(f"calibration of {N_ITEMS:,} items", median_s)


def bench_pdf_loading() -> bool:
    """time load_pdf on a synthetic N_PAGES-page paper."""
    line = " ".join(f"word{i}" for i in range(WORDS_PER_LINE))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "bench.pdf"
        pdf = pymupdf.open()
        for _ in range(N_PAGES):
            page = pdf.new_page(width=595, height=842)
            for index in range(LINES_PER_PAGE):
                page.insert_text((50, 40 + 12.5 * index), line, fontsize=9)
        pdf.save(path)
        pdf.close()
        settings = DocumentSettings()
        median_s = _median_seconds(lambda: load_pdf(path, settings))
    return _report(f"loading a {N_PAGES}-page PDF", median_s)


def main() -> int:
    """run every benchmark and return 1 if any misses its budget."""
    results = [bench_calibration(), bench_pdf_loading()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
