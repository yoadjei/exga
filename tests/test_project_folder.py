"""project folders (ADR 0010): layout, uploaded papers, and resumable extraction runs."""

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from exga.errors import ConfigError, LLMResponseError, PdfParseError
from exga.llm.mock import MockCall, MockLLMClient
from exga.project import (
    add_paper_file,
    create_project,
    import_gold_file,
    open_project,
    project_documents,
    run_extraction,
)
from exga.schemas import FieldSpec, RawResponse
from exga.settings import ExtractionSettings, Settings

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 25, tzinfo=UTC)
SETTINGS = Settings(extraction=ExtractionSettings(samples=2, workers=2))
SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants", group="numeric")
COUNTRY = FieldSpec(name="country", description="country of recruitment", group="short_text")
TRIAL = (FIXTURES / "trial_report.pdf").read_bytes()


def answer(_call: MockCall, _index: int) -> str:
    return json.dumps({"value": "120", "evidence": "A total of 120 participants", "page": 1})


def test_a_new_project_has_its_folders_and_fields(tmp_path: Path) -> None:
    project = create_project(tmp_path / "review", [SAMPLE_SIZE, COUNTRY])

    assert project.papers_dir.is_dir()
    assert project.cache_dir.is_dir()
    assert open_project(tmp_path / "review").store.fields() == (SAMPLE_SIZE, COUNTRY)


def test_a_folder_holding_a_project_is_never_overwritten(tmp_path: Path) -> None:
    create_project(tmp_path, [SAMPLE_SIZE])

    with pytest.raises(ConfigError, match="already holds a project"):
        create_project(tmp_path, [COUNTRY])
    assert open_project(tmp_path).store.fields() == (SAMPLE_SIZE,)


def test_opening_a_folder_without_a_project_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no project in"):
        open_project(tmp_path)


def test_an_uploaded_pdf_is_stored_by_content_under_its_own_name(tmp_path: Path) -> None:
    project = create_project(tmp_path, [SAMPLE_SIZE])

    document = add_paper_file(project, "../Trial 2024.pdf", TRIAL, SETTINGS.document, NOW)
    add_paper_file(project, "copy.pdf", TRIAL, SETTINGS.document, NOW)

    digest = hashlib.sha256(TRIAL).hexdigest()
    assert document.paper_id == digest
    assert document.filename == "Trial 2024.pdf"
    assert [path.name for path in project.papers_dir.iterdir()] == [f"{digest}.pdf"]
    [paper] = project.store.papers()
    assert (paper.filename, paper.path) == ("Trial 2024.pdf", Path("papers") / f"{digest}.pdf")


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("broken.pdf", b"not a pdf", "broken.pdf is not a readable PDF"),
        ("notes.docx", b"text", "notes.docx is neither a PDF"),
    ],
)
def test_an_unreadable_upload_leaves_nothing_behind(
    tmp_path: Path, name: str, data: bytes, message: str
) -> None:
    project = create_project(tmp_path, [SAMPLE_SIZE])

    with pytest.raises(PdfParseError, match=message):
        add_paper_file(project, name, data, SETTINGS.document, NOW)
    assert list(project.papers_dir.iterdir()) == []
    assert project.store.papers() == []


def test_papers_load_from_a_moved_project_folder(tmp_path: Path) -> None:
    project = create_project(tmp_path / "before", [SAMPLE_SIZE])
    add_paper_file(project, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    later = NOW + timedelta(seconds=1)
    add_paper_file(project, "notes.md", b"Forty participants.", SETTINGS.document, later)
    shutil.move(tmp_path / "before", tmp_path / "after")

    documents, skipped = project_documents(open_project(tmp_path / "after"), SETTINGS.document)

    assert [document.filename for document in documents] == ["trial.pdf", "notes.md"]
    assert skipped == []


def test_a_run_extracts_only_the_items_the_project_lacks(tmp_path: Path) -> None:
    project = create_project(tmp_path, [SAMPLE_SIZE])
    add_paper_file(project, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    seen: list[tuple[int, int]] = []

    first = run_extraction(
        project, MockLLMClient(answer), SETTINGS, NOW, progress=lambda *done: seen.append(done)
    )
    again = run_extraction(project, MockLLMClient(answer), SETTINGS, NOW)
    project.store.save_fields([SAMPLE_SIZE, COUNTRY])
    added = run_extraction(project, MockLLMClient(answer), SETTINGS, NOW)

    assert (first.extracted, again.extracted, added.extracted) == (1, 0, 1)
    assert seen == [(1, 1)]
    assert first.parse_failure_rate == 0.0
    extractions = project.store.extractions()
    assert sorted(e.field for e in extractions) == ["country", "sample_size"]
    assert {e.decision for e in extractions} == {"NOT_CERTIFIABLE"}


def test_a_rerun_is_answered_from_the_project_cache(tmp_path: Path) -> None:
    first = create_project(tmp_path / "first", [SAMPLE_SIZE])
    add_paper_file(first, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    run_extraction(first, MockLLMClient(answer), SETTINGS, NOW)
    # a second project with the same paper and a copy of the cache sends no request
    second = create_project(tmp_path / "second", [SAMPLE_SIZE])
    shutil.copytree(first.cache_dir, second.cache_dir, dirs_exist_ok=True)
    add_paper_file(second, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    client = MockLLMClient(answer)

    summary = run_extraction(second, client, SETTINGS, NOW)

    assert summary.extracted == 1
    assert client.calls == []


class FailingClient:
    model_id = "failing"

    def generate(self, *_args: object, **_kwargs: object) -> list[RawResponse]:
        raise LLMResponseError("HTTP 400: context length exceeded")


def test_items_whose_requests_failed_are_retried_by_the_next_run(tmp_path: Path) -> None:
    project = create_project(tmp_path, [SAMPLE_SIZE])
    add_paper_file(project, "trial.pdf", TRIAL, SETTINGS.document, NOW)

    failed = run_extraction(project, FailingClient(), SETTINGS, NOW)
    retried = run_extraction(project, MockLLMClient(answer), SETTINGS, NOW)

    assert (failed.extracted, failed.failed_requests) == (0, 1)
    assert failed.errors == ("trial.pdf · sample_size: HTTP 400: context length exceeded",)
    assert (retried.extracted, retried.failed_requests) == (1, 0)


def test_gold_values_become_annotation_records(tmp_path: Path) -> None:
    project = create_project(tmp_path, [SAMPLE_SIZE])
    document = add_paper_file(project, "trial.pdf", TRIAL, SETTINGS.document, NOW)
    run_extraction(project, MockLLMClient(answer), SETTINGS, NOW)
    gold = tmp_path / "gold.csv"
    gold.write_text(f"paper_id,field,value\n{document.paper_id},sample_size,121\n")

    version = import_gold_file(project, gold, SETTINGS, NOW)

    [record] = project.store.records()
    assert (record.source, record.wrong) == ("annotation", True)
    assert version.n_records == 1
