import hashlib
import math

import pytest

from exga.document import text_document
from exga.schemas import (
    Document,
    FieldSamples,
    FieldSpec,
    Page,
    SampleAnswer,
    Signals,
)
from exga.score import agreement, combine, logprob_signal, score_item, source_match
from exga.settings import MatchingSettings, ScoreSettings, Settings

SETTINGS = Settings()
RULES = MatchingSettings()
SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants randomised", group="numeric")
PAPER = text_document(
    "A total of 120 participants were randomised. The trial ran in Ghana.", "paper.md"
)


def answer(
    value: str | None, evidence: str | None = None, logprob: float | None = None
) -> SampleAnswer:
    return SampleAnswer(value=value, evidence=evidence, mean_logprob=logprob)


def item(greedy: SampleAnswer | None, samples: list[SampleAnswer], failed: int = 0) -> FieldSamples:
    return FieldSamples(
        paper_id=PAPER.paper_id,
        field="sample_size",
        greedy=greedy,
        samples=tuple(samples),
        failed_samples=failed,
        model_id="mock",
        prompt_version="extract_v1",
    )


def test_agreement_is_the_share_of_samples_matching_the_greedy_value() -> None:
    samples = [answer("120"), answer("120.0"), answer("1.2e2"), answer("90"), answer(None)]

    assert agreement(item(answer("120"), samples), SAMPLE_SIZE, RULES) == pytest.approx(3 / 5)


def test_failed_samples_count_against_agreement() -> None:
    assert agreement(item(answer("120"), [answer("120")], failed=3), SAMPLE_SIZE, RULES) == 0.25


def test_not_reported_answers_agree_with_each_other() -> None:
    assert agreement(item(answer(None), [answer(None), answer("5")]), SAMPLE_SIZE, RULES) == 0.5


def test_nothing_agrees_with_a_failed_greedy_answer() -> None:
    assert agreement(item(None, [answer("120")]), SAMPLE_SIZE, RULES) == 0.0


def test_the_logprob_signal_is_the_geometric_mean_token_probability() -> None:
    assert logprob_signal(answer("120", logprob=math.log(0.8))) == pytest.approx(0.8)
    assert logprob_signal(answer("120")) is None
    assert logprob_signal(None) is None


@pytest.mark.parametrize(
    ("greedy", "expected"),
    [
        (answer("120", "A total of 120 participants"), 1.0),
        (answer("120", "a total of 120 Participants!"), 1.0),
        (answer("90", "A total of 120 participants"), 0.5),
        (answer("120", "One hundred and twenty people took part"), 0.0),
        (answer("120", None), 0.0),
        (None, 0.0),
        (answer(None, None), None),
    ],
)
def test_source_match_levels(greedy: SampleAnswer | None, expected: float | None) -> None:
    level, _ = source_match(PAPER, greedy, SAMPLE_SIZE, SETTINGS)

    assert level == expected


def test_a_fuzzy_quote_is_judged_on_the_text_in_the_paper() -> None:
    # the quote says 120, but the paper text it fuzzily matches says 129
    paper = text_document("A total of 129 participants were randomised in Ghana.", "p.md")
    greedy = answer("120", "A total of 120 participants were randomised in Ghana.")

    level, _ = source_match(paper, greedy, SAMPLE_SIZE, SETTINGS)

    assert level == 0.5


def laid_out(words: list[str]) -> Document:
    boxes = tuple((10.0 * i, 0.0, 10.0 * i + 8.0, 10.0) for i in range(len(words)))
    page = Page(
        number=1, text=" ".join(words), words=tuple(words), boxes=boxes, lines=(0,) * len(words)
    )
    paper_id = hashlib.sha256(b"laid out").hexdigest()
    return Document(paper_id=paper_id, filename="p.pdf", source="pdf", pages=(page,))


def test_a_found_quote_is_highlighted() -> None:
    document = laid_out(["In", "all,", "120", "participants", "joined."])

    _, locations = source_match(document, answer("120", "120 participants"), SAMPLE_SIZE, SETTINGS)

    [location] = locations
    assert location.bbox == (20.0, 0.0, 38.0, 10.0)


def test_the_score_averages_available_signals_by_weight() -> None:
    weights = ScoreSettings(agreement_weight=2.0, logprob_weight=1.0, source_weight=1.0)

    full = combine(Signals(agreement=1.0, logprob=0.5, source_match=0.0), weights)
    partial = combine(Signals(agreement=1.0, logprob=None, source_match=0.5), weights)

    assert full == pytest.approx(2.5 / 4)
    assert partial == pytest.approx(2.5 / 3)


def test_a_zero_weight_ignores_its_signal() -> None:
    weights = ScoreSettings(logprob_weight=0.0)

    assert combine(Signals(agreement=0.6, logprob=0.0, source_match=1.0), weights) == 0.8


def test_score_item_builds_a_scored_extraction() -> None:
    greedy = answer("120", "A total of 120 participants", logprob=math.log(0.5))

    extraction = score_item(item(greedy, [answer("120")] * 4), PAPER, SAMPLE_SIZE, SETTINGS)

    assert (extraction.value, extraction.evidence, extraction.failed) == (
        "120",
        "A total of 120 participants",
        False,
    )
    assert (extraction.signals.agreement, extraction.signals.source_match) == (1.0, 1.0)
    assert extraction.signals.logprob == pytest.approx(0.5)
    assert extraction.score == pytest.approx(2.5 / 3)
    assert extraction.decision is None


def test_an_item_without_a_usable_answer_scores_zero() -> None:
    extraction = score_item(item(None, [answer("120")] * 4), PAPER, SAMPLE_SIZE, SETTINGS)

    assert (extraction.value, extraction.failed, extraction.score) == (None, True, 0.0)
