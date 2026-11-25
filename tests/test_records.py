from datetime import UTC, datetime
from pathlib import Path

import pytest

from exga.errors import ConfigError
from exga.records import load_records, save_records
from exga.schemas import CalibrationRecord

NOW = datetime(2026, 11, 25, tzinfo=UTC)


def record(index: int, wrong: bool) -> CalibrationRecord:
    return CalibrationRecord(
        paper_id=f"{index:064x}",
        field="sample_size",
        group="numeric",
        score=0.5 + index / 10,
        wrong=wrong,
        source="benchmark",
        created_at=NOW,
    )


def test_records_round_trip_through_a_jsonl_file(tmp_path: Path) -> None:
    records = [record(1, False), record(2, True)]

    save_records(records, tmp_path / "records.jsonl")

    assert load_records(tmp_path / "records.jsonl") == records
    assert (tmp_path / "records.jsonl").read_bytes().count(b"\n") == 2


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text("\n" + record(1, False).model_dump_json() + "\n\n", encoding="utf-8")

    assert load_records(path) == [record(1, False)]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("not json", "line 2"),
        ('{"paper_id": "x"}', "line 2"),
    ],
)
def test_a_malformed_line_is_named(tmp_path: Path, line: str, message: str) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(record(1, False).model_dump_json() + "\n" + line + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_records(path)


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read records file"):
        load_records(tmp_path / "absent.jsonl")
