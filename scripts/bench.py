"""benchmarks of the budgets in spec 0A.5. run with: make bench

- scoring, calibration and decision for 10,000 items in under one second. scoring here is
  agreement and the combined score; source matching searches a paper and is timed on its
  own, per item, against a 20-page paper.
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
from exga.decide import decide
from exga.pdf import load_pdf
from exga.schemas import Document, FieldSamples, FieldSpec, SampleAnswer, Signals
from exga.score import agreement, combine, logprob_signal, source_match
from exga.settings import DocumentSettings, Settings

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


def bench_core() -> bool:
    """time agreement, combined score, calibration and decision for N_ITEMS items."""
    rng = np.random.default_rng(0)
    spec = FieldSpec(name="sample_size", description="participants", group="numeric")
    settings = Settings()
    values = rng.integers(100, 103, size=(N_ITEMS, 6)).astype(str)
    items = [
        FieldSamples(
            paper_id=f"{index:064x}",
            field="sample_size",
            greedy=SampleAnswer(value=row[0], evidence=None, mean_logprob=-0.1),
            samples=tuple(SampleAnswer(value=value, evidence=None) for value in row[1:]),
            failed_samples=0,
            model_id="bench",
            prompt_version="extract_v1",
        )
        for index, row in enumerate(values)
    ]
    grid = threshold_grid(settings.calibration.grid_step)

    def run() -> None:
        scores = np.array(
            [
                combine(
                    Signals(
                        agreement=agreement(item, spec, settings.matching),
                        logprob=logprob_signal(item.greedy),
                    ),
                    settings.score,
                )
                for item in items
            ]
        )
        wrong = rng.random(N_ITEMS) < 1.0 - scores
        result = fit_threshold(
            scores, wrong, grid=grid, alpha=0.1, delta=0.1, min_accepted=10, group="bench"
        )
        [decide(float(score), result) for score in scores]

    return _report(f"scoring, calibration and decision of {N_ITEMS:,} items", _median_seconds(run))


def bench_source_matching(document: Document) -> bool:
    """time source_match for one item whose quote sits at the end of a long paper."""
    spec = FieldSpec(name="count", description="a count", group="numeric")
    last_page = document.pages[-1].text.split()
    quote = " ".join(last_page[-8:])
    greedy = SampleAnswer(value="7", evidence=quote)
    settings = Settings()
    median_s = _median_seconds(lambda: source_match(document, greedy, spec, settings))
    return _report(f"source matching one quote in a {N_PAGES}-page PDF", median_s)


def bench_pdf_loading() -> tuple[bool, Document]:
    """time load_pdf on a synthetic N_PAGES-page paper; also return the loaded paper."""
    line = " ".join(f"word{i}" for i in range(WORDS_PER_LINE))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "bench.pdf"
        pdf = pymupdf.open()
        for page_index in range(N_PAGES):
            page = pdf.new_page(width=595, height=842)
            for index in range(LINES_PER_PAGE):
                text = f"{line} p{page_index}l{index}"
                page.insert_text((50, 40 + 12.5 * index), text, fontsize=9)
        pdf.save(path)
        pdf.close()
        settings = DocumentSettings()
        median_s = _median_seconds(lambda: load_pdf(path, settings))
        document = load_pdf(path, settings)
    return _report(f"loading a {N_PAGES}-page PDF", median_s), document


def main() -> int:
    """run every benchmark and return 1 if any misses its budget."""
    loaded, document = bench_pdf_loading()
    results = [bench_core(), loaded, bench_source_matching(document)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
