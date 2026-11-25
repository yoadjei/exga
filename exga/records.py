"""JSON-lines files of typed records: one pydantic model as JSON per line.

experiments write extraction samples (samples.jsonl) and benchmark calibration records
(records.jsonl) this way, and a project can import the records as calibration data
(spec 5.3). random-audit records are never imported; see `exga.project`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from exga.errors import ConfigError
from exga.schemas import CalibrationRecord

Model = TypeVar("Model", bound=BaseModel)


def save_jsonl(items: Sequence[BaseModel], path: Path) -> None:
    """write items as UTF-8 JSON lines, replacing path."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(item.model_dump_json() + "\n" for item in items)


def load_jsonl(path: Path, kind: type[Model]) -> list[Model]:
    """read a JSON-lines file of kind; blank lines are ignored.

    raises ConfigError when the file cannot be read or a line is not a valid kind, naming the
    line.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    items = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            items.append(kind.model_validate_json(line))
        except ValidationError as exc:
            raise ConfigError(f"{path}, line {number}: not a valid {kind.__name__}: {exc}") from exc
    return items


def save_records(records: Sequence[CalibrationRecord], path: Path) -> None:
    """write calibration records to a records file."""
    save_jsonl(records, path)


def load_records(path: Path) -> list[CalibrationRecord]:
    """read a records file of calibration records (see `load_jsonl`)."""
    return load_jsonl(path, CalibrationRecord)
