"""Streamlit helpers the pages share: settings, the open project, the clock, the model client,
and how values, statuses and evidence are shown. no method logic lives here (ADR 0010).

text that comes from papers or the model is always shown with `st.text` or in tables, never
as markdown, so a paper cannot inject links or images into the page.
"""

import argparse
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from exga.errors import ConfigError, PdfParseError
from exga.llm.base import LLMClient
from exga.llm.hosted import HostedLLMClient
from exga.messages import status
from exga.pdf import render_page
from exga.project import Project, open_project, project_settings
from exga.schemas import Decision, Extraction
from exga.settings import Settings, load_settings
from exga.store import PaperRow

PROJECT_ROOT = "exga.project_root"
"""session key of the open project's folder, as a string."""
SETTINGS = "exga.settings"
"""session key of the `Settings` loaded when the session started."""
CLIENT_FACTORY = "exga.client_factory"
"""session key of a callable(Settings) -> LLMClient used instead of the hosted client; tests
put a mock here."""
FLASH = "exga.flash"
"""session key of a message to show once, after a rerun."""
METHOD_URL = "https://github.com/yoadjei/exga/blob/main/docs/method.md"
SCREENS = {
    "project": "screens/project.py",
    "fields": "screens/fields.py",
    "run": "screens/run.py",
    "calibrate": "screens/calibrate.py",
    "review": "screens/review.py",
    "audit": "screens/audit.py",
    "export": "screens/export.py",
}
"""page paths relative to main.py, keyed as `exga.views.next_step` names them."""
TITLES = {
    "project": "Project",
    "fields": "Fields",
    "run": "Upload and run",
    "calibrate": "Calibrate",
    "review": "Review",
    "audit": "Audit",
    "export": "Export",
}


def link(screen: str) -> None:
    """a link to another page, by its key in SCREENS."""
    st.page_link(SCREENS[screen], label=f"Go to {TITLES[screen]}")


_BADGE_COLOURS: dict[Decision, Literal["green", "orange", "gray"]] = {
    "ACCEPT": "green",
    "FLAG": "orange",
    "NOT_CERTIFIABLE": "gray",
}

ClientFactory = Callable[[Settings], LLMClient]


def now() -> datetime:
    """the current time in UTC; the library itself never reads the clock."""
    return datetime.now(UTC)


def env_file_argument(argv: list[str]) -> Path | None:
    """the --env-file passed after `streamlit run main.py --`, if any."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=Path, default=None)
    known, _ = parser.parse_known_args(argv)
    env_file: Path | None = known.env_file
    return env_file


def base_settings() -> Settings:
    """the session's settings, loaded once; stops the page with the reason when invalid."""
    if SETTINGS not in st.session_state:
        try:
            st.session_state[SETTINGS] = load_settings(env_file_argument(sys.argv[1:]))
        except ConfigError as exc:
            st.error(f"exga cannot start: {exc}")
            st.stop()
    settings: Settings = st.session_state[SETTINGS]
    return settings


def current_project() -> Project | None:
    """the project open in this session, or None; a folder that vanished is closed."""
    root = st.session_state.get(PROJECT_ROOT)
    if root is None:
        return None
    try:
        return open_project(Path(root))
    except ConfigError:
        del st.session_state[PROJECT_ROOT]
        return None


def require_project() -> Project:
    """the open project; without one, the page says where to open one and stops."""
    project = current_project()
    if project is None:
        st.info("No project is open. Open or create one first.")
        link("project")
        st.stop()
    return project


def settings_for(project: Project) -> Settings:
    """settings at the project's chosen error level (see `project_settings`)."""
    return project_settings(project.store, base_settings())


@contextmanager
def model_client(settings: Settings) -> Iterator[LLMClient]:
    """the model client for a run, closed afterwards; raises ConfigError when unusable."""
    factory: ClientFactory | None = st.session_state.get(CLIENT_FACTORY)
    if factory is not None:
        yield factory(settings)
        return
    with HostedLLMClient(settings.hosted) as client:
        yield client


@contextmanager
def uploaded_file(upload: UploadedFile) -> Iterator[Path]:
    """an upload as a temporary file for the library's file readers, removed afterwards."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / Path(upload.name).name
        path.write_bytes(upload.getvalue())
        yield path


def flash(message: str) -> None:
    """keep a success message to show after the next rerun."""
    st.session_state[FLASH] = message


def show_flash() -> None:
    """show and forget the kept message, if any."""
    message = st.session_state.pop(FLASH, None)
    if message is not None:
        st.success(message)


def method_link() -> None:
    """the info link every guarantee points to (spec 0A.6)."""
    st.caption(f"[How the guarantee works]({METHOD_URL})")


def status_badge(decision: Decision | None) -> None:
    """the decision as symbol, word and colour together, never colour alone."""
    if decision is None:
        st.badge("No decision yet", color="gray")
        return
    st.badge(status(decision), color=_BADGE_COLOURS[decision])


def shown_value(extraction: Extraction) -> str:
    """the model's value in words."""
    if extraction.failed:
        return "No usable answer"
    return "Not reported" if extraction.value is None else extraction.value


def show_evidence(
    project: Project, extraction: Extraction, paper: PaperRow | None, settings: Settings
) -> None:
    """the quoted evidence and, for a PDF where it was found, the page with it highlighted."""
    if extraction.evidence is None:
        st.caption("The model quoted no evidence.")
        return
    st.caption("Evidence quoted by the model")
    st.text(extraction.evidence)
    if not extraction.location:
        st.caption("The quote was not found in the paper; check the paper itself.")
        return
    if paper is None or paper.path is None or paper.source != "pdf":
        return
    page = extraction.location[0].page
    highlights = [location for location in extraction.location if location.page == page]
    try:
        image = render_page(
            project.root / paper.path, page, highlights, settings.document.render_zoom
        )
    except PdfParseError as exc:
        st.warning(f"The page cannot be shown: {exc}")
        return
    st.image(image, caption=f"Page {page}, evidence highlighted", width="stretch")
