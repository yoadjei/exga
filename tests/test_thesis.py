"""the thesis tables (exga.thesis): number formats and the rows of each table.

simulation tables are built from the committed results, which are real; experiment and study
tables from small invented rows, shaped as `read_rows` returns them (text, None when empty).
"""

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from exga.schemas import FieldSpec
from exga.study import TRUST_STATEMENTS
from exga.tables import Row, read_rows
from exga.thesis import (
    POPULATIONS,
    ThesisTable,
    ablation_table,
    audit_table,
    baselines_table,
    calibration_sizes_table,
    data_table,
    fields_table,
    guarantee_table,
    interval,
    main_table,
    percent,
    points,
    study_table,
    trust_table,
)

REPOSITORY = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("value", "text"), [("0.0412", "4.1"), (0.5, "50.0"), ("1", "100.0"), (None, "n/a")]
)
def test_rates_are_percentages_with_one_decimal_and_the_unit_left_to_the_header(
    value: object, text: str
) -> None:
    assert percent(value) == text


def test_intervals_and_differences_have_their_own_format() -> None:
    assert interval("0.01", "0.083") == "[1.0, 8.3]"
    assert interval(None, "0.1") == "n/a"
    assert points("0.125") == "+12.5"
    assert points("-0.05") == "-5.0"


def test_a_value_that_rounds_to_zero_shows_no_minus_sign() -> None:
    assert (percent("-0.0001"), points("-0.0001")) == ("0.0", "+0.0")


def test_rate_columns_name_their_unit_in_the_header() -> None:
    table = guarantee_table(read_rows(REPOSITORY / "results" / "guarantee_simulation.csv"))

    assert r"(\%)" in dict(table.columns)["certified"]
    assert "%" not in "".join(map(str, table.rows[0].values()))


def test_the_guarantee_table_shows_every_simulated_configuration() -> None:
    table = guarantee_table(read_rows(REPOSITORY / "results" / "guarantee_simulation.csv"))

    assert len(table.rows) == 30
    assert table.rows[0] == {
        "population": "monotone, linear",
        "alpha": "0.05",
        "n_cal": "200",
        "certified": "21.4",
        "violated": "2.7",
        "within": "yes",
    }
    assert {row["within"] for row in table.rows} == {"yes"}
    assert (table.rows[1]["population"], table.rows[1]["n_cal"]) == ("", "1,000")
    assert sum(bool(row["population"]) for row in table.rows) == 5
    assert r"\label{tab:guarantee_simulation}" in table.latex()


@pytest.mark.parametrize("build", [guarantee_table, audit_table])
def test_the_simulation_tables_define_every_population_in_a_note(
    build: Callable[[Sequence[Row]], ThesisTable],
) -> None:
    name = "guarantee" if build is guarantee_table else "audit"
    table = build(read_rows(REPOSITORY / "results" / f"{name}_simulation.csv"))

    assert table.note is not None
    assert all(label in table.note.lower() for label in POPULATIONS.values())
    assert {row["population"] for row in table.rows} - {""} == set(POPULATIONS.values())


def test_the_audit_table_compares_random_and_biased_logging() -> None:
    table = audit_table(read_rows(REPOSITORY / "results" / "audit_simulation.csv"))

    assert len(table.rows) == 10
    assert {row["policy"] for row in table.rows} == {"random audit", "wrong logged at 0.5"}


def test_calibration_sizes_match_the_table_in_the_method_page() -> None:
    table = calibration_sizes_table()
    method = (REPOSITORY / "docs" / "method.md").read_text(encoding="utf-8")

    assert [tuple(row.values()) for row in table.rows] == [
        ("0.05", "45", "77", "105"),
        ("0.10", "22", "38", "52"),
        ("0.20", "11", "18", "25"),
    ]
    for row in table.rows:
        assert f"| {' | '.join(map(str, row.values()))} |" in method


def test_the_data_table_counts_items_and_unreported_values_per_field() -> None:
    size = FieldSpec(name="n", description="number randomised", group="numeric")
    country = FieldSpec(name="country", description="country of the trial", group="short_text")
    items = [("p1", size, "120"), ("p1", country, "Ghana"), ("p2", size, None), ("p3", size, "80")]

    table = data_table(items, name="main_data", dataset="the benchmark")

    assert [tuple(row.values()) for row in table.rows] == [
        ("n", "numeric", "3", "1"),
        ("country", "short_text", "1", "0"),
        ("all fields", "", "4", "1"),
    ]
    assert "3 papers" in table.caption
    assert r"\label{tab:main_data}" in table.latex()


def group_row(model: str, variant: str, group: str, alpha: str) -> Row:
    return {
        "model": model,
        "variant": variant,
        "alpha": alpha,
        "group": group,
        "test_items": "48",
        "raw_accuracy": "0.75",
        "acceptance_rate": "0.5",
        "acceptance_low": "0.4",
        "acceptance_high": "0.6",
        "realised_error": "0.0416667",
        "error_low": None,
        "error_high": None,
        "certified": "true",
        "mean_acceptance_rate": "0.45",
        "mean_realised_error": "0.05",
        "certified_share": "0.9",
        "error_above_alpha_rate": "0.12",
    }


def test_the_main_table_shows_one_model_and_the_primary_variant_with_all_fields_first() -> None:
    rows = [
        group_row("m", "combined", "numeric", "0.1"),
        group_row("m", "combined", "all", "0.2"),
        group_row("m", "combined", "all", "0.1"),
        group_row("m", "agreement", "all", "0.1"),
        group_row("other", "combined", "all", "0.1"),
    ]

    table = main_table(rows, "combined", "m", dataset="the benchmark")

    assert [(row["group"], row["alpha"]) for row in table.rows] == [
        ("all fields", "0.10"),
        ("", "0.20"),  # a group is named once per block
        ("numeric", "0.10"),
    ]
    assert table.name == "results_m"
    assert table.rows[0]["accepted"] == "50.0"  # spec 11.2: an interval for the error only
    assert table.rows[0]["error"] == "4.2"  # no interval when the bootstrap had none
    assert table.rows[0]["certified"] == "yes"
    assert "the benchmark" in table.caption
    assert "model m " in table.caption


def test_the_main_table_gives_the_error_interval_and_large_counts_with_separators() -> None:
    row = group_row("m", "combined", "all", "0.1") | {
        "error_low": "0.01",
        "error_high": "0.083",
        "test_items": "1234",
    }

    [shown] = main_table([row], "combined", "m", dataset="the benchmark").rows

    assert (shown["error"], shown["items"]) == ("4.2 [1.0, 8.3]", "1,234")


def test_the_ablation_table_compares_score_variants_on_all_fields() -> None:
    rows = [
        group_row("m", "agreement", "all", "0.1"),
        group_row("m", "combined", "all", "0.1"),
        group_row("m", "combined", "numeric", "0.1"),
    ]

    table = ablation_table(rows)

    assert [row["variant"] for row in table.rows] == ["agreement", "combined"]
    assert table.rows[0]["mean_accepted"] == "45.0"


def test_nested_labels_show_once_per_block() -> None:
    rows = [
        group_row("m", "agreement", "all", "0.1"),
        group_row("m", "agreement", "all", "0.2"),
        group_row("m", "combined", "all", "0.1"),
        group_row("other", "combined", "all", "0.1"),
    ]

    table = ablation_table(rows)

    assert [(row["model"], row["variant"]) for row in table.rows] == [
        ("m", "agreement"),
        ("", ""),
        ("", "combined"),
        ("other", "combined"),  # a new model names its variant again
    ]


def test_the_baselines_table_names_each_method() -> None:
    rows: list[Row] = [
        {
            "model": "m",
            "variant": "combined",
            "baseline": name,
            "cutoff": "0.8" if name == "fixed_cutoff" else None,
            "acceptance_rate": "1",
            "realised_error": "0.25",
            "mean_acceptance_rate": "1",
            "mean_realised_error": "0.24",
        }
        for name in ("accept_all", "fixed_cutoff", "verify_all")
    ]

    table = baselines_table(rows, "combined")

    assert [row["method"] for row in table.rows] == [
        "accept all",
        "fixed cut-off at 0.8",
        "verify all",
    ]


def test_the_fields_table_lists_each_field_at_each_level() -> None:
    rows = [  # as evaluate writes them: each level, then each field
        group_row("m", "combined", "x", alpha) | {"field": field, "group": group}
        for alpha in ("0.1", "0.2")
        for field, group in (("n", "numeric"), ("country", "short_text"))
    ]

    table = fields_table(rows, "combined", "m")

    assert [(row["field"], row["group"], row["alpha"]) for row in table.rows] == [
        ("n", "numeric", "0.10"),
        ("", "", "0.20"),
        ("country", "short_text", "0.10"),
        ("", "", "0.20"),
    ]
    assert table.rows[0]["certified"] == "90.0"


def summary_row(group: str, measure: str, median: str) -> Row:
    return {
        "group": group,
        "measure": measure,
        "n": "6",
        "mean": median,
        "sd": "2",
        "median": median,
        "q1": "0",
        "q3": median,
        "minimum": "0",
        "maximum": median,
    }


def test_the_study_table_names_each_measure_with_its_unit() -> None:
    rows = [
        summary_row("all", "manual_minutes", "20"),
        summary_row("all", "tool_accuracy", "0.9"),
        summary_row("all", "accuracy_difference", "0.05"),
        summary_row("all", "sus", "72.5"),
        summary_row("manual first", "minutes_difference", "-8"),
        summary_row("tool first", "minutes_difference", "3"),
    ]

    table = study_table(rows)

    assert [(row["participants"], row["measure"], row["median"]) for row in table.rows] == [
        ("all", "Minutes, by hand", "20.0"),
        ("", "Accuracy, with exga (%)", "90.0"),
        ("", "Accuracy, difference (pp)", "+5.0"),
        ("", "SUS score (0-100)", "72.5"),
        ("manual first", "Minutes, difference", "-8.0"),
        ("tool first", "Minutes, difference", "+3.0"),  # differences carry their sign
    ]
    assert "differences (exga minus by hand)" in table.caption
    assert (table.rows[0]["iqr"], table.rows[0]["range"]) == ("[0.0, 20.0]", "[0.0, 20.0]")


def test_a_spread_is_unsigned_in_the_unit_of_its_measure() -> None:
    rows = [
        summary_row("all", "manual_minutes", "20") | {"sd": "2.5"},
        summary_row("all", "tool_accuracy", "0.9") | {"sd": "0.013"},
        summary_row("all", "accuracy_difference", "0.05") | {"sd": "0.02"},
    ]

    assert [row["sd"] for row in study_table(rows).rows] == ["2.5", "1.3", "2.0"]


def test_the_trust_table_quotes_each_statement() -> None:
    answers = {"answer_1": "0", "answer_2": "1", "answer_3": "1", "answer_4": "3", "answer_5": "1"}
    rows = [Row(item=f"trust_{n}", n="6", median="4", **answers) for n in range(1, 5)]

    table = trust_table(rows)

    assert [row["statement"] for row in table.rows] == list(TRUST_STATEMENTS)
    assert table.rows[0]["answer_4"] == "3"
    assert r"\begin{tabular}{>{\raggedright\arraybackslash}p{0.5\linewidth}" in table.latex()


def test_the_trust_statements_are_those_on_the_questionnaire() -> None:
    questionnaire = (REPOSITORY / "study" / "questionnaire.md").read_text(encoding="utf-8")

    assert all(f"| {statement} |" in questionnaire for statement in TRUST_STATEMENTS)
