"""result tables: CSV round trips and LaTeX rendering (exga.tables)."""

from pathlib import Path

from exga.tables import latex_table, read_rows, write_rows


def test_rows_read_back_as_text_with_empty_cells_as_none(tmp_path: Path) -> None:
    path = write_rows([{"a": 1.5, "b": None, "c": True, "d": "x"}], tmp_path / "t.csv")

    assert read_rows(path) == [{"a": "1.5", "b": None, "c": "true", "d": "x"}]


def test_a_form_with_a_byte_order_mark_reads_the_same(tmp_path: Path) -> None:
    path = write_rows([{"participant": "P01"}], tmp_path / "form.csv", spreadsheet=True)

    assert read_rows(path) == [{"participant": "P01"}]


def test_an_empty_table_reads_as_no_rows(tmp_path: Path) -> None:
    assert read_rows(write_rows([], tmp_path / "empty.csv")) == []


def test_a_latex_table_escapes_cells_but_not_headers_or_caption() -> None:
    text = latex_table(
        [{"name": "a_b & 5%", "n": "3"}, {"name": "c", "n": "n/a"}],
        [("name", "Field"), ("n", r"$n$")],
        caption=r"Sizes at $\alpha$",
        label="tab:sizes",
    )

    lines = text.splitlines()
    assert lines[0] == r"\begin{table}[htbp]"
    assert r"\caption{Sizes at $\alpha$}" in lines
    assert r"\label{tab:sizes}" in lines
    assert r"\begin{tabular}{lr}" in lines
    assert lines[lines.index(r"\toprule") + 1] == r"Field & $n$ \\"
    assert r"a\_b \& 5\% & 3 \\" in lines
    assert r"c & n/a \\" in lines
    assert lines[-2:] == [r"\end{tabular}", r"\end{table}"]


def test_a_latex_table_is_set_small_with_narrow_column_gaps() -> None:
    lines = latex_table([{"x": "1"}], [("x", "X")], caption="C", label="tab:c").splitlines()

    begin = lines.index(r"\begin{tabular}{l}")
    assert {r"\small", r"\setlength{\tabcolsep}{4pt}"} <= set(lines[:begin])


def test_a_latex_table_takes_an_alignment_and_a_note() -> None:
    text = latex_table(
        [{"x": "1"}], [("x", "X")], caption="C", label="tab:c", align="c", note="Source: x.csv"
    )

    assert r"\begin{tabular}{c}" in text
    assert "Source: x.csv" in text.split(r"\bottomrule")[1]


def test_latex_special_characters_are_all_escaped() -> None:
    text = latex_table([{"t": "\\ # $ { } ~ ^"}], [("t", "T")], caption="C", label="tab:t")

    assert (
        r"\textbackslash{} \# \$ \{ \} \textasciitilde{} \textasciicircum{} \\" in text.splitlines()
    )
