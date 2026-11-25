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
from exga.llm.mock import MockCall, MockLLMClient
from exga.project import Project, add_paper_file, create_project, run_extraction
from exga.schemas import FieldSpec
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


@pytest.mark.parametrize("screen", ["fields"])
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


def test_the_env_file_comes_from_the_arguments_after_streamlit_run() -> None:
    assert env_file_argument(["--env-file", "local.env"]) == Path("local.env")
    assert env_file_argument(["--other", "x"]) is None
