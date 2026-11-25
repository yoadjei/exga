"""the Streamlit pages, run headlessly with AppTest (spec 7.11, 0A.6).

each test drives the pages as a person would, with a mock model client in the session, and
checks the project folder afterwards: the pages only call the library, so what matters is
that the right calls happen and that every state shows a message and a next step.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import exga.app
from exga.app import ui
from exga.app.ui import env_file_argument
from exga.errors import BudgetExceededError
from exga.llm.mock import MockCall, MockLLMClient
from exga.project import Project, add_paper_file, create_project, run_extraction
from exga.records import save_records
from exga.schemas import CalibrationRecord, FieldSpec, RawResponse
from exga.settings import AuditSettings, ExtractionSettings, HostedSettings, Settings

MAIN = Path(exga.app.__file__).parent / "main.py"
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 25, tzinfo=UTC)
LOCAL = HostedSettings(base_url="http://localhost:8000/v1", model="local-model")
SETTINGS = Settings(
    extraction=ExtractionSettings(samples=2, workers=1),
    audit=AuditSettings(rate=0.5, min_items=1),
    hosted=LOCAL,
)
SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants", group="numeric")
TRIAL = (FIXTURES / "trial_report.pdf").read_bytes()


def answer(_call: MockCall, _index: int) -> str:
    return json.dumps(
        {"value": "120", "evidence": "A total of 120 participants were randomised", "page": 1}
    )


def mock_factory(_settings: Settings) -> MockLLMClient:
    return MockLLMClient(answer)


def app(project: Project | None = None, settings: Settings = SETTINGS) -> AppTest:
    test = AppTest.from_file(str(MAIN), default_timeout=60)
    test.session_state[ui.SETTINGS] = settings
    test.session_state[ui.CLIENT_FACTORY] = mock_factory
    if project is not None:
        test.session_state[ui.PROJECT_ROOT] = str(project.root)
    return test.run()


def page(test: AppTest, screen: str) -> AppTest:
    return test.switch_page(ui.SCREENS[screen]).run()


def button(test: AppTest, label: str) -> Callable[[], AppTest]:
    [match] = [widget for widget in test.button if widget.label == label]
    return lambda: match.click().run()


def texts(test: AppTest) -> str:
    """everything the page says, in one string, for loose assertions."""
    parts = [
        element.value for kind in ("markdown", "text", "caption") for element in getattr(test, kind)
    ]
    parts += [
        element.value
        for kind in ("info", "success", "warning", "error")
        for element in getattr(test, kind)
    ]
    return "\n".join(str(part) for part in parts)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "review", [SAMPLE_SIZE])
    add_paper_file(project, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    return project


@pytest.fixture
def extracted(project: Project) -> Project:
    run_extraction(project, MockLLMClient(answer), SETTINGS, NOW)
    return project


@pytest.mark.parametrize("screen", ["fields", "run", "calibrate", "review", "audit", "export"])
def test_without_a_project_every_page_says_where_to_open_one(screen: str) -> None:
    test = page(app(), screen)

    assert not test.exception
    assert [info.value for info in test.info] == ["No project is open. Open or create one first."]


def test_a_new_project_is_created_and_opened(tmp_path: Path) -> None:
    test = app()
    test.text_input(key="new_folder").set_value(str(tmp_path / "review"))
    test = button(test, "Create")()

    assert test.session_state[ui.PROJECT_ROOT] == str(tmp_path / "review")
    assert "Project created" in texts(test)
    assert "Add the fields to extract from each paper." in texts(test)


def test_a_folder_holding_other_files_is_refused(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")
    test = app()
    test.text_input(key="new_folder").set_value(str(tmp_path))
    test = button(test, "Create")()

    assert "is not empty" in test.error[0].value
    assert ui.PROJECT_ROOT not in test.session_state


def test_an_empty_folder_name_is_refused() -> None:
    test = button(app(), "Open")()

    assert [error.value for error in test.error] == ["Enter a folder."]


def test_a_field_is_added_and_a_bad_one_explained(project: Project) -> None:
    test = page(app(project), "fields")
    test = test.selectbox[0].set_value("short_text").run()  # the form changes with the kind
    test.text_input[0].set_value("country")
    test.text_area[0].set_value("country of recruitment")
    test = button(test, "Add field")()

    assert [spec.name for spec in project.store.fields()] == ["sample_size", "country"]
    assert "Added country" in texts(test)

    test.text_input[0].set_value("Bad Name")
    test.text_area[0].set_value("anything")
    test = button(test, "Add field")()
    assert "should match pattern" in test.error[0].value


def test_a_hosted_endpoint_needs_consent_before_a_run(project: Project) -> None:
    hosted = SETTINGS.model_copy(
        update={"hosted": HostedSettings(base_url="https://api.example.com/v1", model="m")}
    )
    test = page(app(project, hosted), "run")
    run = next(widget for widget in test.button if widget.label == "Run extraction")

    assert "api\\.example\\.com" in test.warning[0].value
    assert run.disabled
    test.checkbox[0].check()
    test = test.run()
    assert not next(w for w in test.button if w.label == "Run extraction").disabled


def test_papers_are_uploaded_and_extracted(project: Project) -> None:
    test = page(app(project), "run")
    # submitted at once: a rerun before submitting discards a form's values, upload included
    test.file_uploader[0].upload("notes.md", b"Sixty participants were randomised.")
    test = button(test, "Add papers")()
    assert "Added 1 paper." in texts(test)

    test = button(test, "Run extraction")()

    assert not test.exception
    assert "Extracted 2 items." in texts(test)
    assert len(project.store.extractions()) == 2
    assert "Every field of every paper is extracted." in texts(test.run())


def test_calibrate_shows_the_required_sizes_and_records_a_new_level(extracted: Project) -> None:
    test = page(app(extracted), "calibrate")
    required = test.dataframe[1].value

    assert list(required["0 errors"]) == [45, 22, 11]
    test.selectbox[0].set_value(0.1)
    test = test.run()
    assert "Choose the error level before you look at results" in test.warning[0].value
    test = button(test, "Recalibrate at ≤ 10%")()

    [version] = extracted.store.threshold_log()
    assert version.results["sample_size"].alpha == 0.1
    assert "Recalibrated at ≤ 10%" in texts(test)


def test_review_lists_values_with_status_in_words(extracted: Project) -> None:
    test = page(app(extracted), "review")
    table = test.dataframe[0].value

    assert list(table["Status"]) == ["— Not certifiable"]
    assert list(table["Value"]) == ["120"]
    assert "Select a row" in texts(test)


def select_review_row(test: AppTest, row: int) -> AppTest:
    # AppTest cannot click a dataframe row; the selection is set as Streamlit stores it
    test.session_state["review_table"] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    return test.run()


def test_a_selected_value_shows_its_page_and_takes_a_correction(extracted: Project) -> None:
    test = select_review_row(page(app(extracted), "review"), 0)

    assert "Paper: trial.pdf" in [text.value for text in test.text]
    assert len(test.get("image")) == 1  # the page, with the evidence highlighted
    test.text_input[0].set_value("121")
    test = button(test, "Save correction")()

    assert extracted.store.corrections() == {
        (extracted.store.extractions()[0].paper_id, "sample_size"): "121"
    }
    assert extracted.store.records() == []  # a correction never becomes a calibration record
    assert list(test.dataframe[0].value["Checked value"]) == ["121"]


def test_an_audit_is_answered_and_recalibrates(extracted: Project) -> None:
    test = page(app(extracted), "audit")
    test = button(test, "Draw 1 values to check")()
    assert "Item 1 of 1" in [header.value for header in test.subheader]

    test = button(test, "✓ The model's value is right")()
    test = button(test, "Finish the audit and recalibrate")()

    [record] = extracted.store.records()
    assert (record.source, record.wrong) == ("random_audit", False)
    assert "Audit finished: 1 checked values added." in texts(test)
    assert "Every extracted value has been audited." in texts(test)


def test_an_audit_answer_can_be_given_again(extracted: Project) -> None:
    test = button(page(app(extracted), "audit"), "Draw 1 values to check")()
    test = button(test, "I cannot check this item")()
    test = button(test, "Answer again")()
    test.text_input[0].set_value("121")
    test = button(test, "Save the right value")()

    [item] = extracted.store.audit_items(1)
    assert (item.status, item.checked_value) == ("checked", "121")


def test_export_offers_the_results_and_guarantees(extracted: Project) -> None:
    test = page(app(extracted), "export")

    labels = [widget.label for widget in test.download_button]
    assert labels == ["Download results.csv"]
    assert test.dataframe[0].value["checked_value"].tolist() == [""]


def test_review_and_audit_say_what_to_do_before_any_extraction(project: Project) -> None:
    for screen in ("review", "audit", "export"):
        test = page(app(project), screen)
        assert "Nothing is extracted yet" in test.info[0].value


def test_the_env_file_comes_from_the_arguments_after_streamlit_run() -> None:
    assert env_file_argument(["--env-file", "local.env"]) == Path("local.env")
    assert env_file_argument(["--other", "x"]) is None


def test_an_existing_project_is_opened(project: Project) -> None:
    test = app()
    test.text_input(key="open_folder").set_value(str(project.root))
    test = button(test, "Open")()

    assert test.session_state[ui.PROJECT_ROOT] == str(project.root)
    assert [metric.value for metric in test.metric][:2] == ["1", "1"]


def test_an_unused_field_is_removed_only_when_confirmed(project: Project) -> None:
    project.store.save_fields(
        [SAMPLE_SIZE, FieldSpec(name="country", description="c", group="short_text")]
    )
    test = page(app(project), "fields")
    test.selectbox[1].set_value("country")
    test = button(test, "Remove")()
    assert "Tick the box to confirm." in test.error[0].value

    test.selectbox[1].set_value("country")
    test.checkbox[0].check()
    test = button(test, "Remove")()
    assert [spec.name for spec in project.store.fields()] == ["sample_size"]


def test_benchmark_records_are_imported_on_the_calibrate_page(
    extracted: Project, tmp_path: Path
) -> None:
    records = [
        CalibrationRecord(
            paper_id=f"{index:064x}",
            field="sample_size",
            group="numeric",
            score=0.95,
            wrong=False,
            source="benchmark",
            created_at=NOW,
        )
        for index in range(60)
    ]
    save_records(records, tmp_path / "records.jsonl")
    test = page(app(extracted), "calibrate")
    test.file_uploader[1].upload("records.jsonl", (tmp_path / "records.jsonl").read_bytes())
    test = [w for w in test.button if w.label == "Import"][1].click().run()

    assert len(extracted.store.records()) == 60
    assert "Imported records (threshold version 1)." in texts(test)
    assert test.dataframe[0].value["Status"].tolist() == ["✓ Certified"]


class SpentClient:
    model_id = "spent"

    def generate(self, *_args: object, **_kwargs: object) -> list[RawResponse]:
        raise BudgetExceededError("spent 5.00 USD of a 5.00 USD budget")


def test_a_spent_budget_stops_the_run_with_a_way_on(project: Project) -> None:
    test = page(app(project), "run")
    test.session_state[ui.CLIENT_FACTORY] = lambda _settings: SpentClient()
    test = button(test.run(), "Run extraction")()

    assert "Answers so far are cached; run again to continue." in test.warning[0].value
    assert project.store.extractions() == []
