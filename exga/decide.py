"""accept, flag or mark not certifiable, using certified thresholds (spec 7.6). pure functions."""

from collections.abc import Mapping, Sequence

from exga.schemas import Decision, Extraction, ThresholdResult


def decide(score: float, threshold: ThresholdResult | None) -> Decision:
    """ACCEPT when score >= the certified threshold, FLAG below it, NOT_CERTIFIABLE without one.

    this is the same rule calibration certified, so the guarantee applies to what it accepts.
    """
    if threshold is None or not threshold.certified or threshold.lambda_hat is None:
        return "NOT_CERTIFIABLE"
    return "ACCEPT" if score >= threshold.lambda_hat else "FLAG"


def apply_thresholds(
    extractions: Sequence[Extraction], thresholds: Mapping[str, ThresholdResult]
) -> list[Extraction]:
    """return the extractions with their decisions, using each field's threshold result.

    a field missing from thresholds has no certified threshold, so it is NOT_CERTIFIABLE.
    """
    # model_copy skips validation; the only change is a Decision literal produced by decide
    return [
        extraction.model_copy(
            update={"decision": decide(extraction.score, thresholds.get(extraction.field))}
        )
        for extraction in extractions
    ]
