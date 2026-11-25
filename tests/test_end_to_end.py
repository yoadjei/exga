"""spec 9.3: two fixture PDFs, two fields, a mocked model; extract, score, calibrate, decide,
export, and check the outputs."""

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exga.calibrate import calibrate_fields
from exga.decide import apply_thresholds
from exga.export import export_rows, write_csv
from exga.extract import extract_all, load_prompts
from exga.labels import calibration_records
from exga.llm.mock import MockCall, MockLLMClient
from exga.papers import load_folder
from exga.schemas import CalibrationRecord, Extraction, FieldSpec
from exga.score import score_item
from exga.settings import CalibrationSettings, Settings

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = Settings(calibration=CalibrationSettings(alpha=0.1, delta=0.1))
NOW = datetime(2026, 11, 25, tzinfo=UTC)
SPECS = [
    FieldSpec(name="sample_size", description="participants randomised", group="numeric"),
    FieldSpec(
        name="study_design",
        description="design of the study",
        group="categorical",
        allowed_values=("rct", "cohort"),
        synonyms={"rct": ("randomised controlled trial",)},
    ),
]
TRIAL_ANSWERS = {
    "sample_size": {"value": "120", "evidence": "A total of 120 participants were randomised"},
    "study_design": {
        "value": "rct",
        "evidence": "The study design was a randomised controlled trial",
    },
}


def canned_model(call: MockCall, index: int) -> str:
    """the trial report gets supported answers; the two-column page reports neither field,
    and one of its sampled sample-size answers disagrees."""
    field = "sample_size" if "Item to extract: sample_size" in call.prompt else "study_design"
    if "120 participants" in call.prompt:
        return json.dumps({**TRIAL_ANSWERS[field], "page": 1})
    if field == "sample_size" and call.temperature > 0 and index == 0:
        return json.dumps({"value": "40", "evidence": None, "page": None})
    return json.dumps({"value": None, "evidence": None, "page": None})


@pytest.fixture(scope="module")
def scored(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[Extraction], dict[str, str]]:
    folder = tmp_path_factory.mktemp("papers")
    for name in ("trial_report.pdf", "two_column.pdf"):
        shutil.copy(FIXTURES / name, folder / name)
    documents, skipped = load_folder(folder, SETTINGS.document)
    assert skipped == []
    items = extract_all(
        documents, SPECS, MockLLMClient(canned_model), load_prompts("extract_v1"), SETTINGS
    )
    by_id = {document.paper_id: document for document in documents}
    specs = {spec.name: spec for spec in SPECS}
    extractions = [
        score_item(item, by_id[item.paper_id], specs[item.field], SETTINGS) for item in items
    ]
    return extractions, {document.paper_id: document.filename for document in documents}


def test_supported_answers_score_high_and_unreported_ones_lower(
    scored: tuple[list[Extraction], dict[str, str]],
) -> None:
    extractions, filenames = scored
    by_key = {(filenames[e.paper_id], e.field): e for e in extractions}

    trial_size = by_key["trial_report.pdf", "sample_size"]
    assert (trial_size.value, trial_size.signals.agreement, trial_size.signals.source_match) == (
        "120",
        1.0,
        1.0,
    )
    assert trial_size.location[0].page == 1
    assert by_key["trial_report.pdf", "study_design"].value == "rct"
    other_size = by_key["two_column.pdf", "sample_size"]
    assert (other_size.value, other_size.signals.source_match) == (None, None)
    assert other_size.signals.agreement == pytest.approx(0.8)
    assert other_size.score < trial_size.score


def test_too_few_checked_values_make_every_field_not_certifiable(
    scored: tuple[list[Extraction], dict[str, str]], tmp_path: Path
) -> None:
    extractions, filenames = scored
    gold = {(e.paper_id, e.field): e.value for e in extractions}
    records = calibration_records(
        extractions, gold, SPECS, SETTINGS.matching, source="annotation", created_at=NOW
    )

    thresholds = calibrate_fields(records, SPECS, SETTINGS.calibration)
    decided = apply_thresholds(extractions, thresholds)
    write_csv(export_rows(decided, filenames), tmp_path / "results.csv")

    assert {result.certified for result in thresholds.values()} == {False}
    with (tmp_path / "results.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["decision"] for row in rows] == ["Not certifiable"] * 4
    assert {row["paper"] for row in rows} == {"trial_report.pdf", "two_column.pdf"}


def test_with_enough_checked_values_confident_answers_are_accepted(
    scored: tuple[list[Extraction], dict[str, str]], tmp_path: Path
) -> None:
    extractions, filenames = scored
    # benchmark records: scores of 0.95 are always right, 0.85 wrong half the time, so the
    # certified threshold falls between them: 1.0 is accepted, 0.8 is flagged
    records = [
        CalibrationRecord(
            paper_id=f"{index:064x}",
            field=spec.name,
            group=spec.group,
            score=0.95 if index < 60 else 0.85,
            wrong=index >= 60 and index % 2 == 0,
            source="benchmark",
            created_at=NOW,
        )
        for spec in SPECS
        for index in range(100)
    ]

    thresholds = calibrate_fields(records, SPECS, SETTINGS.calibration)
    decided = apply_thresholds(extractions, thresholds)
    write_csv(export_rows(decided, filenames), tmp_path / "results.csv")

    assert all(result.certified for result in thresholds.values())
    with (tmp_path / "results.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {(row["paper"], row["field"]): row for row in csv.DictReader(handle)}
    assert rows["trial_report.pdf", "sample_size"]["decision"] == "Accepted"
    assert rows["trial_report.pdf", "sample_size"]["value"] == "120"
    assert rows["two_column.pdf", "sample_size"]["decision"] == "Check"
    assert rows["two_column.pdf", "sample_size"]["value"] == "NR"
