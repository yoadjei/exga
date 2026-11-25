import pytest
from hypothesis import given
from hypothesis import strategies as st

from exga.settings import SplitSettings
from exga.splits import double_annotation_sample, split_papers

SETTINGS = SplitSettings()
PAPERS = [f"paper{i:03d}" for i in range(110)]


def test_splits_follow_the_configured_shares() -> None:
    split = split_papers(PAPERS, seed=0, settings=SETTINGS)

    assert (len(split.train), len(split.calibration), len(split.test)) == (33, 44, 33)


@given(
    papers=st.sets(st.text(min_size=1, max_size=8), min_size=3, max_size=60),
    seed=st.integers(min_value=0, max_value=2**32),
)
def test_splits_are_disjoint_and_cover_every_paper(papers: set[str], seed: int) -> None:
    split = split_papers(papers, seed=seed, settings=SETTINGS)

    assert split.train | split.calibration | split.test == papers
    assert not split.train & split.calibration
    assert not split.calibration & split.test
    assert not split.train & split.test


def test_a_split_depends_only_on_the_paper_set_and_the_seed() -> None:
    forwards = split_papers(PAPERS, seed=7, settings=SETTINGS)
    backwards = split_papers([*reversed(PAPERS), PAPERS[0]], seed=7, settings=SETTINGS)

    assert forwards == backwards
    assert forwards != split_papers(PAPERS, seed=8, settings=SETTINGS)


def test_the_shuffle_is_pinned() -> None:
    # golden: fails if a Python release changes random.Random's shuffle, which would change
    # every published split
    split = split_papers("abcdefghij", seed=0, settings=SETTINGS)

    assert (sorted(split.train), sorted(split.calibration), sorted(split.test)) == (
        ["b", "h", "i"],
        ["c", "d", "e", "f"],
        ["a", "g", "j"],
    )


def test_too_few_papers_cannot_be_split() -> None:
    with pytest.raises(ValueError, match="at least 3 papers"):
        split_papers(["a", "b"], seed=0, settings=SETTINGS)


def test_shares_must_leave_a_test_split() -> None:
    with pytest.raises(ValueError, match="leave a share for the test split"):
        SplitSettings(train=0.5, calibration=0.5)


def test_a_fifth_of_papers_rounded_up_is_double_annotated() -> None:
    sample = double_annotation_sample(PAPERS, seed=0, settings=SETTINGS)

    assert len(sample) == 22
    assert sample <= set(PAPERS)
    assert len(double_annotation_sample(PAPERS[:11], seed=0, settings=SETTINGS)) == 3


def test_the_double_annotation_sample_is_reproducible() -> None:
    first = double_annotation_sample(PAPERS, seed=3, settings=SETTINGS)

    assert first == double_annotation_sample(reversed(PAPERS), seed=3, settings=SETTINGS)
    assert first != double_annotation_sample(PAPERS, seed=4, settings=SETTINGS)


def test_float_noise_does_not_add_a_paper() -> None:
    settings = SplitSettings(double_annotation=0.07)

    assert len(double_annotation_sample(PAPERS[:100], seed=0, settings=settings)) == 7
