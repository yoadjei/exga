"""the tables the app shows, built without Streamlit (spec 0A.6, 5.4a, 7.11)."""

from datetime import UTC, datetime

import pytest

from exga.schemas import CalibrationRecord, Extraction, FieldSpec, Signals, ThresholdResult
from exga.store import PaperRow
from exga.views import (
    STATUS_STYLES,
    TEXT_COLOUR,
    contrast_ratio,
    field_rows,
    field_status_rows,
    next_step,
    paper_rows,
    required_n_rows,
    review_rows,
)

NOW = datetime(2026, 11, 25, tzinfo=UTC)
PAPER = "a" * 64
SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants", group="numeric")
COUNTRY = FieldSpec(name="country", description="country", group="short_text")
DESIGN = FieldSpec(
    name="design", description="design", group="categorical", allowed_values=("rct", "cohort")
)


def extraction(field: str, value: str | None, **update: object) -> Extraction:
    item = Extraction(
        paper_id=PAPER,
        field=field,
        samples=(),
        value=value,
        evidence=None,
        signals=Signals(agreement=0.8),
        score=0.8125,
        model_id="mock",
        prompt_version="extract_v1",
    )
    return item.model_copy(update=update)


def result(group: str, *, certified: bool, pooled: bool = False) -> ThresholdResult:
    return ThresholdResult(
        group=group,
        method="fixed_sequence",
        pooled=pooled,
        alpha=0.1,
        delta=0.1,
        n_cal=60,
        errors_cal=3,
        certified=certified,
        lambda_hat=0.75 if certified else None,
        n_accepted_cal=40 if certified else 0,
        errors_accepted_cal=1 if certified else 0,
        upper_bound=0.0937 if certified else None,
    )


def test_required_sample_sizes_match_the_spec_table() -> None:
    rows = required_n_rows(delta=0.1)

    assert rows == [
        {"Error level": "≤ 5%", "0 errors": 45, "1 error": 77, "2 errors": 105},
        {"Error level": "≤ 10%", "0 errors": 22, "1 error": 38, "2 errors": 52},
        {"Error level": "≤ 20%", "0 errors": 11, "1 error": 18, "2 errors": 25},
    ]


def test_review_rows_state_status_in_words_and_symbols() -> None:
    items = [
        extraction("sample_size", "120", decision="ACCEPT"),
        extraction("country", None, decision="FLAG"),
        extraction("design", None, failed=True, decision="NOT_CERTIFIABLE"),
    ]

    rows = review_rows(items, {PAPER: "trial.pdf"}, {(PAPER, "country"): "Ghana"})

    assert rows[0] == {
        "Paper": "trial.pdf",
        "Field": "sample_size",
        "Value": "120",
        "Status": "✓ Accepted",
        "Score": 0.81,
        "Checked value": "",
    }
    assert (rows[1]["Value"], rows[1]["Status"], rows[1]["Checked value"]) == (
        "Not reported",
        "! Check",
        "Ghana",
    )
    assert (rows[2]["Value"], rows[2]["Status"]) == ("No usable answer", "— Not certifiable")


def test_an_item_checked_as_not_reported_says_so() -> None:
    [row] = review_rows([extraction("country", "Ghana")], {}, {(PAPER, "country"): None})

    assert (row["Paper"], row["Status"], row["Checked value"]) == (
        PAPER[:12] + "…",
        "",
        "Not reported",
    )


def records(field: str, group: str, audits: int, others: int) -> list[CalibrationRecord]:
    return [
        CalibrationRecord(
            paper_id=f"{index:064x}",
            field=field,
            group=group,  # type: ignore[arg-type]
            score=0.9,
            wrong=False,
            source="random_audit" if index < audits else "benchmark",
            created_at=NOW,
        )
        for index in range(audits + others)
    ]


def test_field_status_rows_give_counts_bounds_and_the_guarantee() -> None:
    thresholds = {
        "sample_size": result("sample_size", certified=True),
        "country": result("short_text", certified=True, pooled=True),
        "design": result("design", certified=False),
    }
    # audits of a field outside the project never count, even in its group's pooled unit
    history = [
        *records("sample_size", "numeric", audits=4, others=56),
        *records("country", "short_text", audits=1, others=0),
        *records("city", "short_text", audits=2, others=0),
    ]

    rows = field_status_rows([SAMPLE_SIZE, COUNTRY, DESIGN], thresholds, history)

    assert rows[0] == {
        "Field": "sample_size",
        "Status": "✓ Certified",
        "Checked values": 60,
        "From audits": 4,
        "Wrong": 3,
        "Threshold": "0.750",
        "Upper bound": "9.4%",
        "Guarantee": "Error ≤ 10% for this field (90% confidence) · 60 checked values",
    }
    assert (rows[1]["Status"], rows[1]["From audits"]) == ("✓ Certified (pooled)", 1)
    assert str(rows[1]["Guarantee"]).endswith("(assumes errors are independent across fields)")
    assert (rows[2]["Status"], rows[2]["Threshold"], rows[2]["Upper bound"]) == (
        "— Not certifiable",
        "—",
        "—",
    )


def test_fields_without_a_calibration_say_what_to_do_next() -> None:
    [row] = field_status_rows([SAMPLE_SIZE], {}, [])

    assert (row["Status"], row["Checked values"], row["From audits"]) == (
        "— Not calibrated",
        0,
        0,
    )
    assert row["Guarantee"] == "No checked values yet: import some, or run an audit"


@pytest.mark.parametrize("decision", list(STATUS_STYLES))
def test_status_colours_meet_wcag_aa_contrast(decision: str) -> None:
    background = STATUS_STYLES[decision]  # type: ignore[index]

    assert contrast_ratio(background, TEXT_COLOUR) >= 4.5


def test_contrast_ratio_matches_the_wcag_extremes() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("counts", "screen"),
    [
        ((0, 0, 0, 0), "fields"),
        ((2, 0, 0, 0), "run"),
        ((2, 3, 4, 0), "run"),
        ((2, 3, 6, 0), "calibrate"),
        ((2, 3, 6, 40), "review"),
    ],
)
def test_the_next_step_follows_the_workflow(counts: tuple[int, int, int, int], screen: str) -> None:
    fields, papers, extracted, records = counts

    message, target = next_step(fields=fields, papers=papers, extracted=extracted, records=records)

    assert target == screen
    assert message.endswith(".")


def test_field_rows_show_only_what_each_field_uses() -> None:
    weight = FieldSpec(
        name="weight", description="body weight", group="numeric", unit="kg", rel_tolerance=0.05
    )

    rows = field_rows([weight, DESIGN])

    assert rows == [
        {
            "Field": "weight",
            "Group": "numeric",
            "Description": "body weight",
            "Allowed values": "",
            "Unit": "kg",
            "Tolerance": "± 5%",
        },
        {
            "Field": "design",
            "Group": "categorical",
            "Description": "design",
            "Allowed values": "rct, cohort",
            "Unit": "",
            "Tolerance": "",
        },
    ]


def test_paper_rows_count_the_fields_extracted_per_paper() -> None:
    papers = [
        PaperRow(PAPER, "trial.pdf", "pdf", None),
        PaperRow("b" * 64, "notes.md", "text", None),
    ]
    items = [extraction("sample_size", "120"), extraction("country", "Ghana")]

    rows = paper_rows(papers, items, n_fields=3)

    assert rows == [
        {"Paper": "trial.pdf", "Type": "PDF", "Fields extracted": "2 of 3"},
        {"Paper": "notes.md", "Type": "Text", "Fields extracted": "0 of 3"},
    ]
