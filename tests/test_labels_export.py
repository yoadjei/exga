import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exga.errors import ConfigError
from exga.export import COLUMNS, export_rows, write_csv
from exga.labels import calibration_records, gold_value, is_wrong
from exga.schemas import Extraction, FieldSpec, Signals, SpanLocation
from exga.settings import MatchingSettings

RULES = MatchingSettings()
PAPER_ID = hashlib.sha256(b"paper").hexdigest()
SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants", group="numeric")
COUNTRY = FieldSpec(name="country", description="country", group="short_text")
NOW = datetime(2026, 11, 25, tzinfo=UTC)


def extraction(
    field: str = "sample_size",
    value: str | None = "120",
    *,
    failed: bool = False,
    evidence: str | None = None,
    score: float = 0.9,
) -> Extraction:
    return Extraction(
        paper_id=PAPER_ID,
        field=field,
        samples=(),
        value=value,
        failed=failed,
        evidence=evidence,
        signals=Signals(agreement=score),
        score=score,
        model_id="mock",
        prompt_version="extract_v1",
    )


@pytest.mark.parametrize(
    ("cell", "expected"), [("120", "120"), (" NR ", None), ("Ghana ", "Ghana")]
)
def test_gold_cells_read_nr_as_not_reported(cell: str, expected: str | None) -> None:
    assert gold_value(cell) == expected


def test_an_empty_gold_cell_is_ambiguous() -> None:
    with pytest.raises(ConfigError, match='write "NR"'):
        gold_value("  ")


@pytest.mark.parametrize(
    ("item", "gold", "wrong"),
    [
        (extraction(value="120"), "120", False),
        (extraction(value="121"), "120", True),
        (extraction(value=None), None, False),
        (extraction(value=None, failed=True), None, True),
    ],
)
def test_wrong_follows_the_correctness_rule_and_failed_items_are_wrong(
    item: Extraction, gold: str | None, wrong: bool
) -> None:
    assert is_wrong(item, gold, SAMPLE_SIZE, RULES) is wrong


def test_records_are_made_only_for_labelled_items_of_known_fields() -> None:
    items = [
        extraction("sample_size", "120", score=0.7),
        extraction("country", "Ghana"),
        extraction("year", "2020"),
    ]
    gold = {(PAPER_ID, "sample_size"): "100", (PAPER_ID, "year"): "2020"}

    [record] = calibration_records(
        items, gold, [SAMPLE_SIZE, COUNTRY], RULES, source="annotation", created_at=NOW
    )

    assert (record.field, record.group, record.score, record.wrong) == (
        "sample_size",
        "numeric",
        0.7,
        True,
    )
    assert (record.source, record.created_at) == ("annotation", NOW)


def test_export_rows_are_written_for_people() -> None:
    accepted = extraction(evidence="A total of 120").model_copy(
        update={"decision": "ACCEPT", "location": (SpanLocation(page=3, bbox=(0, 0, 1, 1)),)}
    )
    not_reported = extraction(field="country", value=None)
    failed = extraction(value=None, failed=True, score=0.0)

    rows = export_rows([accepted, not_reported, failed], {PAPER_ID: "trial.pdf"})

    assert rows[0] == {
        "paper": "trial.pdf",
        "field": "sample_size",
        "value": "120",
        "decision": "Accepted",
        "score": "0.900",
        "evidence": "A total of 120",
        "page": "3",
    }
    assert (rows[1]["value"], rows[1]["decision"], rows[1]["page"]) == ("NR", "", "")
    assert (rows[2]["value"], rows[2]["score"]) == ("", "0.000")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+1+1", "'+1+1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("-cmd", "'-cmd"),
        ("-3.5", "-3.5"),
        ("-.5", "-.5"),
        ("Ghana", "Ghana"),
    ],
)
def test_cells_that_spreadsheets_would_run_are_neutralised(value: str, expected: str) -> None:
    [row] = export_rows([extraction(field="country", value=value)], {})

    assert row["value"] == expected
    assert row["paper"] == PAPER_ID


def test_the_csv_has_a_header_and_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    rows = export_rows([extraction(field="country", value="Côte d'Ivoire")], {})

    write_csv(rows, path)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == COLUMNS
        assert [row["value"] for row in reader] == ["Côte d'Ivoire"]
