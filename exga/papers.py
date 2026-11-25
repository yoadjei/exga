"""loading the papers of a run from files: PDFs with layout, or plain text (spec 7.1, 10.1)."""

from dataclasses import dataclass
from pathlib import Path

from exga.document import text_document
from exga.errors import ConfigError, PdfParseError
from exga.pdf import load_pdf
from exga.schemas import Document
from exga.settings import DocumentSettings

PDF_SUFFIXES = frozenset({".pdf"})
TEXT_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True)
class Skipped:
    """a file that was not loaded, and why."""

    filename: str
    reason: str


def load_document(path: Path, settings: DocumentSettings) -> Document:
    """load one paper; raises PdfParseError when it cannot be read or has the wrong type."""
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return load_pdf(path, settings)
    if suffix in TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PdfParseError(f"cannot read {path.name} as UTF-8 text: {exc}") from exc
        return text_document(text, path.name)
    raise PdfParseError(f"{path.name} is neither a PDF nor a .md or .txt file")


def load_folder(folder: Path, settings: DocumentSettings) -> tuple[list[Document], list[Skipped]]:
    """load every PDF and text file directly inside folder, in file-name order.

    files that fail to load are returned as Skipped, so one bad PDF does not stop a run;
    other file types are ignored. raises ConfigError when folder is missing or yields no
    paper at all.
    """
    if not folder.is_dir():
        raise ConfigError(f"papers folder not found: {folder}")
    documents: list[Document] = []
    skipped: list[Skipped] = []
    paths = sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in PDF_SUFFIXES | TEXT_SUFFIXES
    )
    for path in paths:
        try:
            documents.append(load_document(path, settings))
        except PdfParseError as exc:
            skipped.append(Skipped(filename=path.name, reason=str(exc)))
    if not documents:
        raise ConfigError(f"no readable PDF, .md or .txt files in {folder}")
    return documents, skipped
