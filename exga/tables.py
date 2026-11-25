"""result tables as CSV files and LaTeX, shared by the experiments, the user study and the
thesis export.

a table is a list of rows; each row maps a column name to a cell. in CSV, numbers keep 6
significant digits, None is an empty cell and booleans are true/false, so files diff cleanly.
"""

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

Row = dict[str, object]

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def write_rows(rows: Sequence[Row], path: Path, *, spreadsheet: bool = False) -> Path:
    """write rows as a CSV file with the first row's columns; no rows give an empty file.

    spreadsheet adds a byte-order mark, so spreadsheet programs read non-ASCII text right; use
    it for forms people fill in.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if spreadsheet else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: _cell(value) for key, value in row.items()} for row in rows)
    return path


def read_rows(path: Path) -> list[Row]:
    """the rows of a CSV file written by `write_rows`, as text; an empty cell is None."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {key: value if value else None for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def latex_table(
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[tuple[str, str]],
    *,
    caption: str,
    label: str,
    align: str | None = None,
    note: str | None = None,
) -> str:
    """a booktabs table (needs \\usepackage{booktabs}) of the given (key, header) columns.

    cells are escaped; headers, caption and note are LaTeX as given, so they may hold math
    such as $\\alpha$. align defaults to the first column left and the rest right; a column
    spec such as >{\\raggedright\\arraybackslash}p{5cm} also needs \\usepackage{array}. the
    table is set in \\small with 4pt column gaps, so most fit a portrait page.
    """
    spec = align or "l" + "r" * (len(columns) - 1)
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        rf"\begin{{tabular}}{{{spec}}}",
        r"\toprule",
        " & ".join(header for _, header in columns) + r" \\",
        r"\midrule",
        *(
            " & ".join(_escape(str(row[key] if row[key] is not None else "")) for key, _ in columns)
            + r" \\"
            for row in rows
        ),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    if note:
        lines += [r"\par\smallskip", rf"{{\footnotesize {note}}}"]
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return "".join(_LATEX_SPECIAL.get(character, character) for character in text)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
