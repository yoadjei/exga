import hashlib

import pytest

from exga.decide import apply_thresholds, decide
from exga.messages import guarantee, not_certifiable_warning, percent, status
from exga.schemas import Extraction, Signals, ThresholdResult

PAPER_ID = hashlib.sha256(b"paper").hexdigest()


def certified(
    lambda_hat: float, *, pooled: bool = False, group: str = "sample_size"
) -> ThresholdResult:
    return ThresholdResult(
        group=group,
        method="fixed_sequence",
        pooled=pooled,
        alpha=0.05,
        delta=0.1,
        n_cal=412,
        errors_cal=30,
        certified=True,
        lambda_hat=lambda_hat,
        n_accepted_cal=300,
        errors_accepted_cal=6,
        upper_bound=0.04,
    )


def uncertified(n_cal: int = 40, errors: int = 9) -> ThresholdResult:
    return ThresholdResult(
        group="country",
        method="fixed_sequence",
        pooled=False,
        alpha=0.1,
        delta=0.1,
        n_cal=n_cal,
        errors_cal=errors,
        certified=False,
        lambda_hat=None,
        n_accepted_cal=0,
        errors_accepted_cal=0,
        upper_bound=None,
    )


def extraction(field: str, score: float) -> Extraction:
    return Extraction(
        paper_id=PAPER_ID,
        field=field,
        samples=(),
        value="120",
        evidence=None,
        signals=Signals(agreement=score),
        score=score,
        model_id="mock",
        prompt_version="extract_v1",
    )


@pytest.mark.parametrize(
    ("score", "threshold", "expected"),
    [
        (0.9, certified(0.8), "ACCEPT"),
        (0.8, certified(0.8), "ACCEPT"),
        (0.79, certified(0.8), "FLAG"),
        (0.0, certified(0.0), "ACCEPT"),
        (1.0, uncertified(), "NOT_CERTIFIABLE"),
        (1.0, None, "NOT_CERTIFIABLE"),
    ],
)
def test_decide_compares_the_score_with_the_certified_threshold(
    score: float, threshold: ThresholdResult | None, expected: str
) -> None:
    assert decide(score, threshold) == expected


def test_each_field_uses_its_own_threshold() -> None:
    items = [extraction("sample_size", 0.85), extraction("country", 0.85), extraction("year", 0.85)]
    thresholds = {"sample_size": certified(0.8), "country": certified(0.9)}

    decided = apply_thresholds(items, thresholds)

    assert [item.decision for item in decided] == ["ACCEPT", "FLAG", "NOT_CERTIFIABLE"]
    assert [item.decision for item in items] == [None, None, None]


@pytest.mark.parametrize(
    ("fraction", "text"),
    [(0.05, "5%"), (0.125, "12.5%"), (0.9, "90%"), (0.0, "0%"), (1 / 3, "33.3%")],
)
def test_percentages_are_written_for_people(fraction: float, text: str) -> None:
    assert percent(fraction) == text


def test_status_pairs_a_symbol_with_a_label() -> None:
    assert [status(d) for d in ("ACCEPT", "FLAG", "NOT_CERTIFIABLE")] == [
        "✓ Accepted",
        "! Check",
        "— Not certifiable",
    ]


def test_the_guarantee_line_states_bound_confidence_and_evidence() -> None:
    assert guarantee(certified(0.8)) == "Error ≤ 5% (90% confidence) · 412 checked values"


def test_a_pooled_guarantee_names_its_group_and_assumption() -> None:
    line = guarantee(certified(0.8, pooled=True, group="short_text"))

    assert line.endswith(
        "pooled across short text fields (assumes errors are independent across fields)"
    )


def test_an_uncertified_field_promises_nothing() -> None:
    assert guarantee(uncertified()) == "Not certifiable at error ≤ 10% · 40 checked values"


def test_the_warning_reports_the_raw_error_rate() -> None:
    warning = not_certifiable_warning(uncertified(n_cal=40, errors=9))

    assert warning.startswith(
        "The AI is not reliable enough on this field to promise an error rate of 10%. "
        "All values are flagged for checking."
    )
    assert warning.endswith("On 40 checked values, the AI was wrong 22.5% of the time (9 of 40).")


def test_the_warning_without_records_says_so() -> None:
    assert not_certifiable_warning(uncertified(n_cal=0, errors=0)).endswith(
        "No checked values exist yet for this field."
    )
