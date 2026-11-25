import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from exga.schemas import (
    CalibrationRecord,
    Extraction,
    FieldSpec,
    Paper,
    RawResponse,
    SampleAnswer,
    SpanLocation,
    ThresholdResult,
)

PAPER_ID = hashlib.sha256(b"fixture paper").hexdigest()


def make_extraction(**overrides: object) -> Extraction:
    fields: dict[str, object] = {
        "paper_id": PAPER_ID,
        "field": "sample_size",
        "samples": [{"value": "120", "evidence": "120 were randomised", "page_hint": 2}],
        "value": "120",
        "evidence": "120 were randomised",
        "signals": {"agreement": 1.0, "logprob": 0.95, "source_match": 1.0},
        "score": 0.98,
        "model_id": "mock",
        "prompt_version": "extract_v1",
    }
    return Extraction.model_validate(fields | overrides)


def make_record(**overrides: object) -> CalibrationRecord:
    fields: dict[str, object] = {
        "paper_id": PAPER_ID,
        "field": "sample_size",
        "group": "numeric",
        "score": 0.9,
        "wrong": False,
        "source": "random_audit",
        "created_at": datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
    }
    return CalibrationRecord.model_validate(fields | overrides)


def certified_result(**overrides: object) -> ThresholdResult:
    fields: dict[str, object] = {
        "group": "sample_size",
        "method": "fixed_sequence",
        "pooled": False,
        "alpha": 0.1,
        "delta": 0.1,
        "n_cal": 60,
        "errors_cal": 9,
        "certified": True,
        "lambda_hat": 0.85,
        "n_accepted_cal": 40,
        "errors_accepted_cal": 1,
        "upper_bound": 0.095,
    }
    return ThresholdResult.model_validate(fields | overrides)


def uncertified_result(**overrides: object) -> ThresholdResult:
    fields: dict[str, object] = {
        "certified": False,
        "lambda_hat": None,
        "n_accepted_cal": 0,
        "errors_accepted_cal": 0,
        "upper_bound": None,
    }
    return certified_result(**(fields | overrides))


def test_numeric_field_accepts_unit_and_tolerances() -> None:
    spec = FieldSpec(
        name="sample_size",
        description="total number of participants randomised",
        group="numeric",
        unit="participants",
        rel_tolerance=0.01,
    )

    assert spec.rel_tolerance == 0.01


@pytest.mark.parametrize("name", ["Sample Size", "1st_author", "sample-size", ""])
def test_field_name_must_be_a_snake_case_identifier(name: str) -> None:
    with pytest.raises(ValidationError, match="name"):
        FieldSpec(name=name, description="country of data collection", group="short_text")


def test_blank_field_description_is_rejected() -> None:
    with pytest.raises(ValidationError, match="description"):
        FieldSpec(name="country", description="   ", group="short_text")


def test_unknown_field_spec_option_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        FieldSpec.model_validate(
            {"name": "year", "description": "publication year", "group": "numeric", "tol": 1}
        )


def test_categorical_field_with_distinct_allowed_values_is_accepted() -> None:
    spec = FieldSpec(
        name="study_design",
        description="design of the study as reported by the authors",
        group="categorical",
        allowed_values=("rct", "cohort", "case_control"),
    )

    assert spec.allowed_values == ("rct", "cohort", "case_control")


@pytest.mark.parametrize("allowed", [None, ["rct"], ["rct", "rct"]])
def test_categorical_field_needs_two_distinct_allowed_values(allowed: list[str] | None) -> None:
    with pytest.raises(ValidationError, match="allowed_values"):
        FieldSpec.model_validate(
            {"name": "study_design", "description": "design", "group": "categorical"}
            | {"allowed_values": allowed}
        )


def test_allowed_values_on_a_non_categorical_field_are_rejected() -> None:
    with pytest.raises(ValidationError, match="allowed_values"):
        FieldSpec(name="country", description="d", group="short_text", allowed_values=("a", "b"))


@pytest.mark.parametrize(
    "option", [{"unit": "years"}, {"numeric_tolerance": 1.0}, {"rel_tolerance": 0.1}]
)
def test_numeric_options_on_a_text_field_are_rejected(option: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="numeric"):
        FieldSpec.model_validate(
            {"name": "country", "description": "d", "group": "short_text"} | option
        )


def test_negative_tolerance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="numeric_tolerance"):
        FieldSpec(name="year", description="d", group="numeric", numeric_tolerance=-1.0)


@pytest.mark.parametrize("paper_id", [PAPER_ID.upper(), PAPER_ID[:-1], "not-a-hash"])
def test_paper_id_must_be_a_lowercase_sha256_hex_digest(paper_id: str) -> None:
    with pytest.raises(ValidationError, match="paper_id"):
        Paper(paper_id=paper_id, filename="trial.pdf", n_pages=12)


def test_span_pages_are_one_based() -> None:
    with pytest.raises(ValidationError, match="page"):
        SpanLocation(page=0, bbox=(0.0, 0.0, 10.0, 10.0))


@pytest.mark.parametrize(
    "bbox", [(100.0, 50.0, 90.0, 60.0), (10.0, 60.0, 90.0, 50.0)], ids=["x-reversed", "y-reversed"]
)
def test_span_bbox_corners_must_be_ordered(bbox: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValidationError, match="bbox"):
        SpanLocation(page=1, bbox=bbox)


def test_new_extraction_is_undecided_and_unlocated() -> None:
    extraction = make_extraction()

    assert extraction.decision is None
    assert extraction.location == ()


def test_extraction_keeps_every_location_where_the_evidence_was_found() -> None:
    boxes = [{"page": 2, "bbox": (72.0, 100.0, 300.0, 112.0)}, {"page": 5, "bbox": (0, 0, 0, 0)}]

    extraction = make_extraction(location=boxes)

    assert [span.page for span in extraction.location] == [2, 5]
    assert extraction.location[0] == SpanLocation(page=2, bbox=(72.0, 100.0, 300.0, 112.0))


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_extraction_score_must_lie_in_the_unit_interval(score: float) -> None:
    with pytest.raises(ValidationError, match="score"):
        make_extraction(score=score)


def test_signal_outside_the_unit_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="agreement"):
        make_extraction(signals={"agreement": 1.2})


def test_records_cannot_be_modified_after_creation() -> None:
    extraction = make_extraction()

    with pytest.raises(ValidationError, match="frozen"):
        extraction.decision = "ACCEPT"  # type: ignore[misc]


def test_calibration_record_survives_a_json_round_trip() -> None:
    record = make_record()

    assert CalibrationRecord.model_validate_json(record.model_dump_json()) == record


def test_calibration_record_rejects_a_timestamp_without_timezone() -> None:
    with pytest.raises(ValidationError, match="created_at"):
        make_record(created_at=datetime(2026, 11, 25, 12, 0))


def test_certified_and_uncertified_results_are_both_valid() -> None:
    assert certified_result().certified
    assert not uncertified_result().certified


@pytest.mark.parametrize(
    "overrides",
    [
        {"lambda_hat": None},
        {"upper_bound": None},
        {"n_accepted_cal": 0, "errors_accepted_cal": 0},
    ],
)
def test_certified_result_needs_threshold_bound_and_accepted_items(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="a certified result"):
        certified_result(**overrides)


@pytest.mark.parametrize(
    "overrides", [{"lambda_hat": 0.9}, {"upper_bound": 0.2}, {"n_accepted_cal": 5}]
)
def test_uncertified_result_carries_no_threshold_bound_or_accepted_counts(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="an uncertified result"):
        uncertified_result(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"errors_cal": 61},
        {"n_accepted_cal": 61},
        {"errors_accepted_cal": 41},
        {"errors_cal": 0},
    ],
    ids=[
        "errors>records",
        "accepted>records",
        "accepted_errors>accepted",
        "accepted_errors>errors",
    ],
)
def test_counts_must_be_mutually_consistent(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="exceed"):
        certified_result(**overrides)


def test_pooled_result_must_name_a_field_group() -> None:
    with pytest.raises(ValidationError, match="field group"):
        certified_result(pooled=True)

    assert certified_result(pooled=True, group="numeric").pooled


def test_log_probabilities_cannot_be_positive() -> None:
    with pytest.raises(ValidationError, match="logprob"):
        SampleAnswer(value="120", evidence=None, mean_logprob=0.2)
    with pytest.raises(ValidationError, match="logprob"):
        RawResponse.model_validate(
            {
                "text": "120",
                "token_logprobs": [{"token": "120", "logprob": 0.1}],
                "input_tokens": 10,
                "output_tokens": 1,
            }
        )


def test_token_counts_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="input_tokens"):
        RawResponse(text="120", token_logprobs=None, input_tokens=-1, output_tokens=1)
