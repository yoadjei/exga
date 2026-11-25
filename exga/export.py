"""the review table as CSV (spec 7.9).

cells come from model output, which comes from arbitrary PDFs, so any cell a spreadsheet
could run as a formula is prefixed with an apostrophe (CSV injection).
"""

import csv
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from exga.labels import NOT_REPORTED
from exga.messages import STATUS_LABELS
from exga.schemas import Extraction

COLUMNS = ("paper", "field", "value", "decision", "score", "evidence", "page")
_FORMULA_STARTS = ("=", "+", "@", "\t", "\r")
_NEGATIVE_NUMBER = re.compile(r"-[\d.]")


def export_rows(
    extractions: Sequence[Extraction], filenames: Mapping[str, str]
) -> list[dict[str, str]]:
    """one row per extraction, as strings ready for a CSV writer.

    value is "NR" for "not reported" and empty when the model gave no usable answer. page is
    the first page where the evidence was found, or empty. paper is the file name when known,
    else the paper id.
    """
    return [
        {
            "paper": _safe(filenames.get(item.paper_id, item.paper_id)),
            "field": item.field,
            "value": "" if item.failed else _safe(item.value or NOT_REPORTED),
            "decision": "" if item.decision is None else STATUS_LABELS[item.decision],
            "score": f"{item.score:.3f}",
            "evidence": _safe(item.evidence or ""),
            "page": str(item.location[0].page) if item.location else "",
        }
        for item in extractions
    ]


def write_csv(rows: Sequence[Mapping[str, str]], path: Path) -> None:
    """write rows with a header, UTF-8 with a byte-order mark so spreadsheets read accents."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _safe(cell: str) -> str:
    # a leading minus is a formula too, unless the cell is a negative number such as -3.5
    starts_formula = cell.startswith(_FORMULA_STARTS) or (
        cell.startswith("-") and _NEGATIVE_NUMBER.match(cell) is None
    )
    return f"'{cell}" if starts_formula else cell
