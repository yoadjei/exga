import shutil
from pathlib import Path

import pytest

from exga.errors import ConfigError, PdfParseError
from exga.papers import Skipped, load_document, load_folder
from exga.settings import DocumentSettings

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = DocumentSettings()


def test_pdfs_and_text_files_load_in_name_order(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "trial_report.pdf", tmp_path / "b.pdf")
    (tmp_path / "a.md").write_text("Sixty patients were enrolled.", encoding="utf-8")
    (tmp_path / "notes.docx").write_bytes(b"ignored")

    documents, skipped = load_folder(tmp_path, SETTINGS)

    assert [(d.filename, d.source) for d in documents] == [("a.md", "text"), ("b.pdf", "pdf")]
    assert skipped == []


def test_unreadable_papers_are_skipped_with_a_reason(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "trial_report.pdf", tmp_path / "good.pdf")
    shutil.copy(FIXTURES / "image_only.pdf", tmp_path / "scanned.pdf")

    documents, skipped = load_folder(tmp_path, SETTINGS)

    assert [d.filename for d in documents] == ["good.pdf"]
    [only] = skipped
    assert only.filename == "scanned.pdf"
    assert "scanned PDFs are not supported" in only.reason


def test_a_folder_without_papers_is_a_config_error(tmp_path: Path) -> None:
    shutil.copy(FIXTURES / "not_a_pdf.pdf", tmp_path / "broken.pdf")

    with pytest.raises(ConfigError, match="no readable"):
        load_folder(tmp_path, SETTINGS)


def test_a_missing_folder_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_folder(tmp_path / "absent", SETTINGS)


def test_text_that_is_not_utf8_cannot_be_loaded(tmp_path: Path) -> None:
    path = tmp_path / "latin1.txt"
    path.write_bytes("caf\xe9".encode("latin-1"))

    with pytest.raises(PdfParseError, match="UTF-8"):
        load_document(path, SETTINGS)


def test_other_file_types_are_refused(tmp_path: Path) -> None:
    with pytest.raises(PdfParseError, match="neither a PDF"):
        load_document(tmp_path / "paper.docx", SETTINGS)


def test_skipped_files_compare_by_value() -> None:
    assert Skipped("a.pdf", "encrypted") == Skipped(filename="a.pdf", reason="encrypted")
