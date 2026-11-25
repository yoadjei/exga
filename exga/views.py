"""the tables the app shows, built as plain rows so they are tested without Streamlit.

status is never colour alone (spec 0A.6): every row states it with a symbol and a word, and
the colours behind it keep dark text at WCAG AA contrast or better.
"""

from collections.abc import Mapping, Sequence

from exga.calibrate import required_n
from exga.messages import guarantee, percent, status
from exga.schemas import CalibrationRecord, Decision, Extraction, FieldSpec, ThresholdResult

TEXT_COLOUR = "#1a1a1a"
STATUS_STYLES: dict[Decision, str] = {
    "ACCEPT": "#d3f0da",
    "FLAG": "#fbe3b5",
    "NOT_CERTIFIABLE": "#e4e4e4",
}
"""cell backgrounds: green, amber and grey, each with TEXT_COLOUR on top."""
DISPLAY_ALPHAS = (0.05, 0.1, 0.2)
NOT_CALIBRATED = "No checked values yet: import some, or run an audit"
# sRGB channels at or below this are linear in WCAG 2's relative luminance formula
_SRGB_LINEAR_LIMIT = 0.04045


def status_css(decision: Decision | None) -> str:
    """the CSS for a status cell; empty before an item has a decision."""
    if decision is None:
        return ""
    return f"background-color: {STATUS_STYLES[decision]}; color: {TEXT_COLOUR}"


def review_rows(
    extractions: Sequence[Extraction],
    filenames: Mapping[str, str],
    checked: Mapping[tuple[str, str], str | None],
) -> list[dict[str, object]]:
    """one row per extraction for the Review table, in the order given."""
    return [
        {
            "Paper": filenames.get(item.paper_id, item.paper_id[:12] + "…"),
            "Field": item.field,
            "Value": _shown_value(item),
            "Status": "" if item.decision is None else status(item.decision),
            "Score": round(item.score, 2),
            "Checked value": _checked_text(checked, (item.paper_id, item.field)),
        }
        for item in extractions
    ]


def required_n_rows(delta: float, max_errors: int = 2) -> list[dict[str, object]]:
    """the spec 5.4a table: fewest accepted checked values that certify each error level."""
    rows: list[dict[str, object]] = []
    for alpha in DISPLAY_ALPHAS:
        row: dict[str, object] = {"Error level": f"≤ {percent(alpha)}"}
        for errors in range(max_errors + 1):
            row[f"{errors} error{'' if errors == 1 else 's'}"] = required_n(alpha, delta, errors)
        rows.append(row)
    return rows


def field_status_rows(
    specs: Sequence[FieldSpec],
    thresholds: Mapping[str, ThresholdResult],
    records: Sequence[CalibrationRecord],
) -> list[dict[str, object]]:
    """one row per field for the Calibrate page: status, counts, bound and guarantee (5.6)."""
    rows: list[dict[str, object]] = []
    for spec in specs:
        result = thresholds.get(spec.name)
        if result is None:
            mine = [record for record in records if record.field == spec.name]
            rows.append(
                {
                    "Field": spec.name,
                    "Status": "— Not calibrated",
                    "Checked values": len(mine),
                    "From audits": _audit_count(mine),
                    "Wrong": sum(record.wrong for record in mine),
                    "Threshold": "—",
                    "Upper bound": "—",
                    "Guarantee": NOT_CALIBRATED,
                }
            )
            continue
        unit = [
            record
            for record in records
            if (record.group == result.group if result.pooled else record.field == spec.name)
        ]
        rows.append(
            {
                "Field": spec.name,
                "Status": _certification(result),
                "Checked values": result.n_cal,
                "From audits": _audit_count(unit),
                "Wrong": result.errors_cal,
                "Threshold": "—" if result.lambda_hat is None else f"{result.lambda_hat:.3f}",
                "Upper bound": "—" if result.upper_bound is None else percent(result.upper_bound),
                "Guarantee": guarantee(result),
            }
        )
    return rows


def contrast_ratio(first: str, second: str) -> float:
    """the WCAG 2 contrast ratio of two #rrggbb colours, from 1 (none) to 21."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= _SRGB_LINEAR_LIMIT else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _certification(result: ThresholdResult) -> str:
    if not result.certified:
        return "— Not certifiable"
    return "✓ Certified (pooled)" if result.pooled else "✓ Certified"


def _audit_count(records: Sequence[CalibrationRecord]) -> int:
    return sum(record.source == "random_audit" for record in records)


def _shown_value(item: Extraction) -> str:
    if item.failed:
        return "No usable answer"
    return "Not reported" if item.value is None else item.value


def _checked_text(checked: Mapping[tuple[str, str], str | None], key: tuple[str, str]) -> str:
    if key not in checked:
        return ""
    value = checked[key]
    return "Not reported" if value is None else value
