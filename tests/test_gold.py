import hashlib
from pathlib import Path

import pytest

from exga.errors import ConfigError
from exga.gold import Agreement, agreement, load_gold
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings

RULES = MatchingSettings()
A = hashlib.sha256(b"paper a").hexdigest()
B = hashlib.sha256(b"paper b").hexdigest()
SPECS = [
    FieldSpec(name="sample_size", description="participants", group="numeric"),
    FieldSpec(
        name="study_design",
        description="design",
        group="categorical",
        allowed_values=("rct", "cohort"),
    ),
    FieldSpec(name="country", description="country", group="short_text"),
]


def write(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "gold.csv"
    path.write_text("\n".join(["paper_id,field,value", *lines]) + "\n", encoding="utf-8")
    return path


def test_gold_values_load_with_nr_as_not_reported(tmp_path: Path) -> None:
    path = write(tmp_path, f"{A},sample_size,120", f"{A},study_design,RCT", f"{B},country,NR")

    assert load_gold(path, SPECS) == {
        (A, "sample_size"): "120",
        (A, "study_design"): "RCT",
        (B, "country"): None,
    }


def test_a_spreadsheet_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "gold.csv"
    path.write_text(f"paper_id,field,value\n{A},country,Ghana\n", encoding="utf-8-sig")

    assert load_gold(path, SPECS) == {(A, "country"): "Ghana"}


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("abc,sample_size,120", "line 2: paper_id 'abc' is not a sha256"),
        (f"{A},year,2020", "line 2: field 'year' is not in the field list"),
        (f"{A},sample_size,", 'line 2: an empty gold value is ambiguous; write "NR"'),
        (f"{A},sample_size,about a hundred-ish", "line 2: gold value .* is not a number"),
        (f"{A},study_design,survey", "line 2: gold value 'survey' is not allowed"),
    ],
)
def test_malformed_lines_are_named(tmp_path: Path, line: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=problem):
        load_gold(write(tmp_path, line), SPECS)


def test_a_repeated_item_is_an_error(tmp_path: Path) -> None:
    path = write(tmp_path, f"{A},country,Ghana", f"{A},country,Kenya")

    with pytest.raises(ConfigError, match=r"line 3: country for paper .* is repeated"):
        load_gold(path, SPECS)


def test_missing_columns_are_named(tmp_path: Path) -> None:
    path = tmp_path / "gold.csv"
    path.write_text("paper,field\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="lacks columns: paper_id, value"):
        load_gold(path, SPECS)


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read gold file"):
        load_gold(tmp_path / "absent.csv", SPECS)


def test_agreement_uses_each_field_rule_on_shared_items() -> None:
    first = {
        (A, "sample_size"): "120",
        (B, "sample_size"): "90",
        (A, "country"): "USA",
        (B, "country"): None,
    }
    second = {(A, "sample_size"): "120.0", (B, "sample_size"): "95", (A, "country"): "usa"}

    results = agreement(first, second, SPECS, RULES)

    assert results == [
        Agreement(field="sample_size", agreed=1, compared=2),
        Agreement(field="study_design", agreed=0, compared=0),
        Agreement(field="country", agreed=1, compared=1),
    ]
    assert [result.rate for result in results] == [0.5, None, 1.0]
