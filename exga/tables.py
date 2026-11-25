"""result tables as CSV files, shared by the experiments and the user study.

a table is a list of rows; each row maps a column name to a cell. numbers keep 6 significant
digits, None is an empty cell and booleans are true/false, so files diff cleanly.
"""

import csv
from collections.abc import Sequence
from pathlib import Path

Row = dict[str, object]


def write_rows(rows: Sequence[Row], path: Path) -> Path:
    """write rows as a CSV file with the first row's columns; no rows give an empty file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: _cell(value) for key, value in row.items()} for row in rows)
    return path


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
