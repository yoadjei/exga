"""the release metadata agree: citation file, pyproject and the installed package (spec 14)."""

import tomllib
from importlib.metadata import version
from pathlib import Path

import yaml

REPOSITORY = Path(__file__).parents[1]


def test_the_citation_file_names_the_released_version_and_licence() -> None:
    citation = yaml.safe_load((REPOSITORY / "CITATION.cff").read_text(encoding="utf-8"))
    project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    licence = (REPOSITORY / project["license-files"][0]).read_text(encoding="utf-8")

    assert citation["cff-version"] == "1.2.0"
    assert {"message", "title", "authors", "date-released"} <= set(citation)
    assert citation["version"] == project["version"] == version("exga")
    assert citation["license"] == project["license"]
    assert licence.startswith(f"{project['license']} License")
