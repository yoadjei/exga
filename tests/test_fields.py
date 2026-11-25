from pathlib import Path

import pytest

from exga.errors import ConfigError
from exga.fields import load_fields, save_fields
from exga.schemas import FieldSpec

VALID = """\
fields:
  - name: sample_size
    description: total number of participants randomised
    group: numeric
    rel_tolerance: 0.01
  - name: study_design
    description: design of the study
    group: categorical
    allowed_values: [rct, cohort]
    synonyms:
      rct: [randomised controlled trial]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "fields.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_fields_load_in_file_order(tmp_path: Path) -> None:
    sample_size, design = load_fields(write(tmp_path, VALID))

    assert (sample_size.name, sample_size.rel_tolerance) == ("sample_size", 0.01)
    assert design.allowed_values == ("rct", "cohort")
    assert design.synonyms == {"rct": ("randomised controlled trial",)}


def test_saved_fields_load_back_unchanged(tmp_path: Path) -> None:
    specs = load_fields(write(tmp_path, VALID))
    path = tmp_path / "saved.yaml"

    save_fields(specs, path)

    assert load_fields(path) == specs
    assert "numeric_tolerance" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("fields: [", "not valid YAML"),
        ("- name: x", "mapping with a 'fields' list"),
        ("fields: []", "has no fields"),
        (
            "fields:\n  - name: Sample Size\n    description: d\n    group: numeric",
            r"fields\[0\]: name: String should match pattern",
        ),
        (
            "fields:\n  - name: x\n    description: d\n    group: categorical",
            r"fields\[0\]: entry: Value error, categorical fields need",
        ),
        (
            "fields:\n  - {name: x, description: d, group: numeric}\n"
            "  - {name: x, description: e, group: numeric}",
            "repeats field names: x",
        ),
    ],
)
def test_malformed_field_lists_are_config_errors(tmp_path: Path, text: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=problem):
        load_fields(write(tmp_path, text))


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read field list"):
        load_fields(tmp_path / "absent.yaml")


def test_the_example_field_list_is_valid() -> None:
    specs = load_fields(Path(__file__).parents[1] / "examples" / "fields.yaml")

    assert {spec.group for spec in specs} == {"numeric", "categorical", "short_text", "long_text"}
    assert all(isinstance(spec, FieldSpec) for spec in specs)
