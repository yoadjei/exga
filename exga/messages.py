"""every sentence exga shows users about decisions and guarantees (spec 0A.6, 5.4, 5.7).

all claims are generated from a `ThresholdResult`, never written by hand, so what users read
always matches what was certified. status is never conveyed by colour alone: each decision
has a text label and a symbol.
"""

from exga.schemas import Decision, ThresholdResult

STATUS_LABELS: dict[Decision, str] = {
    "ACCEPT": "Accepted",
    "FLAG": "Check",
    "NOT_CERTIFIABLE": "Not certifiable",
}
STATUS_SYMBOLS: dict[Decision, str] = {
    "ACCEPT": "✓",
    "FLAG": "!",
    "NOT_CERTIFIABLE": "—",
}
POOLED_NOTE = "pooled across {group} fields (assumes errors are independent across fields)"
METHOD_LINK = "docs/method.md"


def percent(fraction: float) -> str:
    """a fraction as a percentage with at most one decimal: 0.05 -> "5%", 0.125 -> "12.5%"."""
    text = f"{fraction * 100:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def status(decision: Decision) -> str:
    """the decision as symbol and label, e.g. "✓ Accepted"."""
    return f"{STATUS_SYMBOLS[decision]} {STATUS_LABELS[decision]}"


def guarantee(result: ThresholdResult) -> str:
    """one line stating what is promised for a field, or that nothing is.

    e.g. "Error ≤ 5% (90% confidence) · 412 checked values". a pooled result names its
    group and the independence assumption (spec 5.4).
    """
    confidence = percent(1 - result.delta)
    checked = _count(result.n_cal, "checked value")
    if not result.certified:
        return f"Not certifiable at error ≤ {percent(result.alpha)} · {checked}"
    line = f"Error ≤ {percent(result.alpha)} ({confidence} confidence) · {checked}"
    if result.pooled:
        line += " · " + POOLED_NOTE.format(group=result.group.replace("_", " "))
    return line


def not_certifiable_warning(result: ThresholdResult) -> str:
    """the spec 5.7 warning, with the raw error rate measured on calibration records."""
    warning = (
        "The AI is not reliable enough on this field to promise an error rate of "
        f"{percent(result.alpha)}. All values are flagged for checking."
    )
    if result.n_cal == 0:
        return warning + " No checked values exist yet for this field."
    rate = result.errors_cal / result.n_cal
    return (
        warning + f" On {_count(result.n_cal, 'checked value')}, the AI was wrong "
        f"{percent(rate)} of the time ({result.errors_cal} of {result.n_cal})."
    )


def _count(number: int, noun: str) -> str:
    return f"{number:,} {noun}{'' if number == 1 else 's'}"
