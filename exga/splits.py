"""reproducible splits of papers into training, calibration and test sets (spec 10.3).

splits are by paper, never by item, so no paper informs both a threshold and its test. the ids
are sorted, then shuffled by `random.Random` seeded with an int, so a split depends only on
the set of papers and the seed. a golden test fails if a Python release changes the shuffle.
"""

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass

from exga.settings import SplitSettings

_SPLITS = 3


@dataclass(frozen=True)
class PaperSplit:
    """disjoint sets of paper ids; together they hold every paper given."""

    train: frozenset[str]
    """for fitting a score model (spec 7.4); never used for thresholds or evaluation."""
    calibration: frozenset[str]
    test: frozenset[str]


def split_papers(paper_ids: Iterable[str], seed: int, settings: SplitSettings) -> PaperSplit:
    """shuffle the distinct paper ids with seed and cut them by the configured fractions.

    the training and calibration sizes are rounded to the nearest paper and the test set takes
    the rest. raises ValueError when there are fewer papers than splits.
    """
    papers = sorted(set(paper_ids))
    if len(papers) < _SPLITS:
        raise ValueError(f"need at least {_SPLITS} papers to split, got {len(papers)}")
    random.Random(seed).shuffle(papers)
    n_train = round(settings.train * len(papers))
    n_calibration = round(settings.calibration * len(papers))
    return PaperSplit(
        train=frozenset(papers[:n_train]),
        calibration=frozenset(papers[n_train : n_train + n_calibration]),
        test=frozenset(papers[n_train + n_calibration :]),
    )


def double_annotation_sample(
    paper_ids: Iterable[str], seed: int, settings: SplitSettings
) -> frozenset[str]:
    """the papers to label twice, to measure agreement (spec 10.2).

    a share settings.double_annotation of the distinct papers, rounded up, chosen at random
    with seed after sorting, so the sample depends only on the papers and the seed.
    """
    papers = sorted(set(paper_ids))
    # rounding first stops float noise (0.07 * 100 = 7.000000000000001) adding a paper
    size = math.ceil(round(settings.double_annotation * len(papers), 9))
    return frozenset(random.Random(seed).sample(papers, size))
