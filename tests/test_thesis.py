"""the thesis tables (exga.thesis): number formats and the rows of each table.

simulation tables are built from the committed results, which are real; experiment and study
tables from small invented rows, shaped as `read_rows` returns them (text, None when empty).
"""

from pathlib import Path

import pytest

from exga.study import TRUST_STATEMENTS
from exga.tables import Row, read_rows
from exga.thesis import (
    ablation_table,
    audit_table,
    baselines_table,
    calibration_sizes_table,
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
    ("value", "text"), [("0.0412", "4.1%"), (0.5, "50.0%"), ("1", "100.0%"), (None, "n/a")]
)
def test_rates_are_percentages_with_one_decimal(value: object, text: str) -> None:
    assert percent(value) == text


def test_intervals_and_differences_have_their_own_format() -> None:
    assert interval("0.01", "0.083") == "[1.0%, 8.3%]"
    assert interval(None, "0.1") == "n/a"
    assert points("0.125") == "+12.5 pp"
    assert points("-0.05") == "-5.0 pp"


def test_the_guarantee_table_shows_every_simulated_configuration() -> None:
    table = guarantee_table(read_rows(REPOSITORY / "results" / "guarantee_simulation.csv"))

    assert len(table.rows) == 30
    assert table.rows[0] == {
        "population": "monotone: Beta(4, 1) scores, P(wrong) = 1 - s",
        "alpha": "5%",
        "n_cal": "200",
        "certified": "21.4%",
        "violated": "2.7%",
        "within": "yes",
    }
    assert {row["within"] for row in table.rows} == {"yes"}
    assert (table.rows[1]["population"], table.rows[1]["n_cal"]) == ("", "1,000")
    assert sum(bool(row["population"]) for row in table.rows) == 5
    assert r"\label{tab:guarantee_simulation}" in table.latex()


def test_the_audit_table_compares_random_and_biased_logging() -> None:
    table = audit_table(read_rows(REPOSITORY / "results" / "audit_simulation.csv"))

    assert len(table.rows) == 10
    assert {row["policy"] for row in table.rows} == {"random audit", "wrong logged at 0.5"}


def test_calibration_sizes_match_the_table_in_the_method_page() -> None:
    table = calibration_sizes_table()
    method = (REPOSITORY / "docs" / "method.md").read_text(encoding="utf-8")

    assert [tuple(row.values()) for row in table.rows] == [
        ("5%", "45", "77", "105"),
        ("10%", "22", "38", "52"),
        ("20%", "11", "18", "25"),
    ]
    for alpha, row in zip(("0.05", "0.10", "0.20"), table.rows, strict=True):
        assert f"| {alpha} | {row['zero']} | {row['one']} | {row['two']} |" in method


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


def test_the_main_table_shows_the_primary_variant_with_all_fields_first() -> None:
    rows = [
        group_row("m", "combined", "numeric", "0.1"),
        group_row("m", "combined", "all", "0.1"),
        group_row("m", "agreement", "all", "0.1"),
    ]

    table = main_table(rows, "combined", name="main_results", dataset="the benchmark")

    assert [(row["group"], row["alpha"]) for row in table.rows] == [
        ("all fields", "10%"),
        ("numeric", "10%"),
    ]
    assert table.rows[0]["accepted"] == "50.0% [40.0%, 60.0%]"
    assert table.rows[0]["error"] == "4.2%"  # no interval when the bootstrap had none
    assert table.rows[0]["certified"] == "yes"
    assert "the benchmark" in table.caption


def test_the_ablation_table_compares_score_variants_on_all_fields() -> None:
    rows = [
        group_row("m", "agreement", "all", "0.1"),
        group_row("m", "combined", "all", "0.1"),
        group_row("m", "combined", "numeric", "0.1"),
    ]

    table = ablation_table(rows)

    assert [row["variant"] for row in table.rows] == ["agreement", "combined"]
    assert table.rows[0]["mean_accepted"] == "45.0%"


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
    rows = [
        group_row("m", "combined", "x", "0.1") | {"field": "n", "group": "numeric"},
        group_row("m", "combined", "x", "0.2") | {"field": "n", "group": "numeric"},
    ]

    table = fields_table(rows, "combined", "m")

    assert [(row["field"], row["alpha"], row["certified"]) for row in table.rows] == [
        ("n", "10%", "90.0%"),
        ("n", "20%", "90.0%"),
    ]


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


def test_the_study_table_formats_each_measure_in_its_unit() -> None:
    rows = [
        summary_row("all", "manual_minutes", "20"),
        summary_row("all", "tool_accuracy", "0.9"),
        summary_row("all", "accuracy_difference", "0.05"),
        summary_row("all", "sus", "72.5"),
        summary_row("manual first", "minutes_difference", "-8"),
    ]

    table = study_table(rows)

    assert [(row["participants"], row["measure"], row["median"]) for row in table.rows] == [
        ("all", "Minutes, by hand", "20.0"),
        ("all", "Accuracy, with exga", "90.0%"),
        ("all", "Accuracy, exga minus by hand", "+5.0 pp"),
        ("all", "SUS score (0-100)", "72.5"),
        ("manual first", "Minutes, exga minus by hand", "-8.0"),
    ]
    assert table.rows[0]["iqr"] == "[0.0, 20.0]"


def test_the_trust_table_quotes_each_statement() -> None:
    answers = {"answer_1": "0", "answer_2": "1", "answer_3": "1", "answer_4": "3", "answer_5": "1"}
    rows = [Row(item=f"trust_{n}", n="6", median="4", **answers) for n in range(1, 5)]

    table = trust_table(rows)

    assert [row["statement"] for row in table.rows] == list(TRUST_STATEMENTS)
    assert table.rows[0]["answer_4"] == "3"


def test_the_trust_statements_are_those_on_the_questionnaire() -> None:
    questionnaire = (REPOSITORY / "study" / "questionnaire.md").read_text(encoding="utf-8")

    assert all(f"| {statement} |" in questionnaire for statement in TRUST_STATEMENTS)
