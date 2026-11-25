"""calibration records files: one `CalibrationRecord` as JSON per line (records.jsonl).

experiments write the benchmark's records this way, and a project can import them as
calibration data (spec 5.3). random-audit records are never imported; see `exga.project`.
"""

from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from exga.errors import ConfigError
from exga.schemas import CalibrationRecord


def save_records(records: Sequence[CalibrationRecord], path: Path) -> None:
    """write records as UTF-8 JSON lines, replacing path."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")


def load_records(path: Path) -> list[CalibrationRecord]:
    """read a records file; blank lines are ignored.

    raises ConfigError when the file cannot be read or a line is not a valid record, naming
    the line.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read records file {path}: {exc}") from exc
    records = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(CalibrationRecord.model_validate_json(line))
        except ValidationError as exc:
            raise ConfigError(f"{path}, line {number}: not a calibration record: {exc}") from exc
    return records
