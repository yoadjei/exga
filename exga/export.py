"""the review table as CSV (spec 7.9).

cells come from model output, which comes from arbitrary PDFs, so any cell a spreadsheet
could run as a formula is prefixed with an apostrophe (CSV injection).
"""

import csv
import io
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from exga.labels import NOT_REPORTED
from exga.messages import STATUS_LABELS
from exga.schemas import Extraction

COLUMNS = ("paper", "field", "value", "decision", "score", "evidence", "page", "checked_value")
_FORMULA_STARTS = ("=", "+", "@", "\t", "\r")
_NEGATIVE_NUMBER = re.compile(r"-[\d.]")


def export_rows(
    extractions: Sequence[Extraction],
    filenames: Mapping[str, str],
    checked: Mapping[tuple[str, str], str | None] | None = None,
) -> list[dict[str, str]]:
    """one row per extraction, as strings ready for a CSV writer.

    value is the model's: "NR" for "not reported", empty when it gave no usable answer. page
    is the first page where the evidence was found, or empty. paper is the file name when
    known, else the paper id. checked_value is the value a person gave in an audit or a
    correction ("NR" for not reported), or empty when nobody checked the item.
    """
    checked = {} if checked is None else checked
    return [
        {
            "paper": _safe(filenames.get(item.paper_id, item.paper_id)),
            "field": item.field,
            "value": "" if item.failed else _safe(item.value or NOT_REPORTED),
            "decision": "" if item.decision is None else STATUS_LABELS[item.decision],
            "score": f"{item.score:.3f}",
            "evidence": _safe(item.evidence or ""),
            "page": str(item.location[0].page) if item.location else "",
            "checked_value": _checked_cell(checked, (item.paper_id, item.field)),
        }
        for item in extractions
    ]


def csv_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    """rows as a CSV file with a header, in UTF-8 with a byte-order mark so spreadsheets read
    accents."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def write_csv(rows: Sequence[Mapping[str, str]], path: Path) -> None:
    """write rows to path as `csv_bytes`."""
    path.write_bytes(csv_bytes(rows))


def _checked_cell(checked: Mapping[tuple[str, str], str | None], key: tuple[str, str]) -> str:
    if key not in checked:
        return ""
    return _safe(checked[key] or NOT_REPORTED)


def _safe(cell: str) -> str:
    # a leading minus is a formula too, unless the cell is a negative number such as -3.5
    starts_formula = cell.startswith(_FORMULA_STARTS) or (
        cell.startswith("-") and _NEGATIVE_NUMBER.match(cell) is None
    )
    return f"'{cell}" if starts_formula else cell
