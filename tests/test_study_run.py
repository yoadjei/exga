"""study/study.py end to end (spec 11.3, ADR 0012): forms, sheet, calibration and analysis.

the participants, their times and answers are invented for the test; they are not study data.
"""

import csv
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exga.export import COLUMNS
from exga.papers import load_folder
from exga.records import load_records, save_records
from exga.schemas import CalibrationRecord
from exga.settings import DocumentSettings

REPOSITORY = Path(__file__).parents[1]
RUN = REPOSITORY / "study" / "study.py"
PAPERS = {
    "A": {"a1.md": ("120", "Ghana"), "a2.md": ("80", "Kenya")},
    "B": {"b1.md": ("64", "Peru"), "b2.md": ("200", "NR")},
}


def run_script(*args: object) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("EXGA_")}
    return subprocess.run(
        [sys.executable, str(RUN), *map(str, args)],
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def study(tmp_path: Path) -> Path:
    """two paper sets of two text papers, a field list and gold for every item."""
    ids: dict[str, str] = {}
    for paper_set, papers in PAPERS.items():
        folder = tmp_path / "papers" / paper_set
        folder.mkdir(parents=True)
        for name, (size, country) in papers.items():
            where = "" if country == "NR" else f" in {country}"
            text = f"Study {name}. {size} participants{where}."
            (folder / name).write_text(text, encoding="utf-8")
        documents, _ = load_folder(folder, DocumentSettings())
        ids |= {document.filename: document.paper_id for document in documents}
    (tmp_path / "fields.yaml").write_text(
        "fields:\n"
        "  - {name: n, description: number of participants, group: numeric}\n"
        "  - {name: country, description: country of the data, group: short_text}\n",
        encoding="utf-8",
    )
    gold = [
        {"paper_id": ids[name], "field": field, "value": value}
        for papers in PAPERS.values()
        for name, values in papers.items()
        for field, value in zip(("n", "country"), values, strict=True)
    ]
    write(tmp_path / "gold.csv", gold)
    return tmp_path


def test_prepare_writes_the_forms_and_never_overwrites_them(study: Path) -> None:
    data = study / "data"

    first = run_script("prepare", "--participants", 4, "--seed", 0, "--out", data)
    (data / "sessions.csv").write_text("filled in\n", encoding="utf-8")
    again = run_script("prepare", "--participants", 4, "--seed", 0, "--out", data)

    assert first.returncode == 0, first.stderr
    assert len(read(data / "assignment.csv")) == 4
    assert (data / "answers").is_dir()
    assert again.returncode == 2
    assert "already exists" in again.stderr
    assert (data / "sessions.csv").read_text(encoding="utf-8") == "filled in\n"


def test_a_sheet_asks_for_every_field_of_every_paper(study: Path) -> None:
    out = study / "data" / "sheet_A.csv"

    result = run_script(
        "sheet", "--papers", study / "papers" / "A", "--fields", study / "fields.yaml", "--out", out
    )

    assert result.returncode == 0, result.stderr
    rows = read(out)
    assert [(row["paper"], row["field"]) for row in rows] == [
        ("a1.md", "n"),
        ("a1.md", "country"),
        ("a2.md", "n"),
        ("a2.md", "country"),
    ]
    assert rows[1]["question"] == "country of the data"
    assert all(row["value"] == "" for row in rows)


def test_calibration_records_leave_out_the_study_papers(study: Path) -> None:
    study_paper = load_folder(study / "papers" / "A", DocumentSettings())[0][0].paper_id
    other = "f" * 64
    at = datetime(2026, 11, 25, tzinfo=UTC)
    records = [
        CalibrationRecord(
            paper_id=paper_id,
            field="n",
            group="numeric",
            score=0.9,
            wrong=False,
            source="annotation",
            created_at=at,
        )
        for paper_id in (study_paper, other)
    ]
    save_records(records, study / "records.jsonl")

    result = run_script(
        "calibration",
        "--records",
        study / "records.jsonl",
        "--papers",
        study / "papers",
        "--out",
        study / "calibration.jsonl",
    )

    assert result.returncode == 0, result.stderr
    assert [record.paper_id for record in load_records(study / "calibration.jsonl")] == [other]
    assert "left out 1 of 2 records" in result.stdout


def fill_in(data: Path, finished: list[str]) -> None:
    """minutes, answers and questionnaires for the finished participants only.

    manual answers are all right; the tool's answers are right except one country the
    participant did not correct, and they saved two corrections.
    """
    sessions = read(data / "sessions.csv")
    for row in sessions:
        if row["participant"] in finished:
            row["minutes"] = "20" if row["condition"] == "manual" else "8.5"
    write(data / "sessions.csv", sessions)
    questionnaire = read(data / "questionnaire.csv")
    for row in questionnaire:
        if row["participant"] in finished:
            row |= {"role": "student", "experience": "some"}
            row |= {f"sus_{n}": "4" if n % 2 else "2" for n in range(1, 11)}
            row |= {f"trust_{n}": "4" for n in range(1, 5)}
    write(data / "questionnaire.csv", questionnaire)
    for row in read(data / "assignment.csv"):
        participant = row["participant"]
        if participant not in finished:
            continue
        sets = {
            row["first_condition"]: row["first_set"],
            row["second_condition"]: row["second_set"],
        }
        manual = [
            {"paper": name, "field": field, "value": value}
            for name, values in PAPERS[sets["manual"]].items()
            for field, value in zip(("n", "country"), values, strict=True)
        ]
        write(data / "answers" / f"{participant}_manual.csv", manual)
        tool = []
        for index, item in enumerate(
            (name, field, value)
            for name, values in PAPERS[sets["tool"]].items()
            for field, value in zip(("n", "country"), values, strict=True)
        ):
            name, field, value = item
            model = "Atlantis" if index == 1 else value
            checked = value if index in (2, 3) else ""
            tool.append(dict.fromkeys(COLUMNS, "") | {"paper": name, "field": field})
            tool[-1] |= {"value": model, "checked_value": checked}
        write(data / "answers" / f"{participant}_tool.csv", tool)


def test_the_analysis_summarises_the_participants_who_finished(study: Path) -> None:
    data, out = study / "data", study / "results"
    assert run_script("prepare", "--participants", 4, "--seed", 0, "--out", data).returncode == 0
    fill_in(data, finished=["P01", "P02", "P03"])

    result = run_script(
        "analyse",
        "--data",
        data,
        "--papers",
        study / "papers",
        "--fields",
        study / "fields.yaml",
        "--gold",
        study / "gold.csv",
        "--out",
        out,
    )

    assert result.returncode == 0, result.stderr
    participants = read(out / "participants.csv")
    assert [row["participant"] for row in participants] == ["P01", "P02", "P03"]
    assert {(row["manual_accuracy"], row["tool_accuracy"]) for row in participants} == {
        ("1", "0.75")
    }
    assert {
        (row["minutes_difference"], row["tool_corrected"], row["sus"]) for row in participants
    } == {("-11.5", "2", "75")}
    summary = read(out / "summary.csv")
    assert len(summary) == 3 * 8
    assert next(r for r in summary if r["group"] == "all" and r["measure"] == "sus")["n"] == "3"
    assert [row["n"] for row in read(out / "trust.csv")] == ["3"] * 4
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["participants"] == 3
    assert manifest["excluded"] == {"P04": "no time recorded for the manual condition"}
    assert "P04" in result.stdout
