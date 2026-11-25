"""read PDFs into `Document`s and render highlighted pages (spec 7.1); the I/O half of P2.

each call opens one PDF, reads what it needs and closes it (CLAUDE.md 5). text, word boxes
and searching live in pure `document.py`; this module only talks to PyMuPDF.
"""

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pymupdf

from exga.document import is_heading_line
from exga.errors import PdfParseError
from exga.schemas import Box, Document, Page, SpanLocation
from exga.settings import DocumentSettings

# PyMuPDF block type for text; image blocks (type 1) carry no text
_TEXT_BLOCK = 0
# asks MuPDF to join words hyphenated at a line end; it does not always recognise the break
# (it does not in tests/fixtures), and `locate` then finds such words by its fuzzy step
_TEXT_FLAGS = pymupdf.TEXT_DEHYPHENATE | pymupdf.TEXT_PRESERVE_WHITESPACE
# a text line is identified by its block and its line within the block
_LINES_PER_BLOCK = 10_000


def load_pdf(path: Path, settings: DocumentSettings) -> Document:
    """return the page text and word boxes of the PDF at path.

    paper_id is the sha256 of the file bytes. raises PdfParseError when the file cannot be
    read or opened, is encrypted, or has fewer than settings.min_text_chars characters of
    text (a scanned PDF, which is out of scope).
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PdfParseError(f"cannot read {path}: {exc}") from exc
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PdfParseError(f"{path.name} is not a readable PDF: {exc}") from exc
    with pdf:
        if pdf.needs_pass:
            raise PdfParseError(f"{path.name} is encrypted")
        pages = tuple(_read_page(pdf[index], index + 1) for index in range(pdf.page_count))
    text_chars = sum(len(page.text.strip()) for page in pages)
    if text_chars < settings.min_text_chars:
        raise PdfParseError(
            f"{path.name} has {text_chars} characters of text; scanned PDFs are not supported"
        )
    return Document(
        paper_id=hashlib.sha256(data).hexdigest(),
        filename=path.name,
        source="pdf",
        pages=pages,
    )


def _read_page(page: pymupdf.Page, number: int) -> Page:
    blocks = page.get_text("blocks", flags=_TEXT_FLAGS)
    paragraphs = [
        paragraph
        for block in blocks
        if block[6] == _TEXT_BLOCK
        for paragraph in _split_at_headings(block[4].split("\n"))
    ]
    words: list[str] = []
    boxes: list[Box] = []
    lines: list[int] = []
    for x0, y0, x1, y1, word, block_no, line_no, _word_no in page.get_text(
        "words", flags=_TEXT_FLAGS
    ):
        words.append(word)
        boxes.append((float(x0), float(y0), float(x1), float(y1)))
        lines.append(int(block_no) * _LINES_PER_BLOCK + int(line_no))
    return Page(
        number=number,
        text="\n\n".join(paragraphs),
        words=tuple(words),
        boxes=tuple(boxes),
        lines=tuple(lines),
    )


def _split_at_headings(lines: list[str]) -> list[str]:
    # PyMuPDF puts a heading and its body in one block when they are evenly spaced, so a
    # heading line becomes a paragraph of its own, where chunking can break
    groups: list[list[str]] = [[]]
    for line in lines:
        if is_heading_line(line):
            groups += [[line], []]
        elif line.strip():
            groups[-1].append(line)
    return [" ".join(" ".join(group).split()) for group in groups if group]


def render_page(
    path: Path, page_number: int, highlights: Sequence[SpanLocation], zoom: float
) -> bytes:
    """return a PNG of one page with the highlights on that page drawn over it.

    renders on demand and changes nothing on disk. raises PdfParseError when the file cannot
    be opened or page_number is out of range.
    """
    try:
        pdf = pymupdf.open(path)
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise PdfParseError(f"cannot open {path.name}: {exc}") from exc
    with pdf:
        if not 1 <= page_number <= pdf.page_count:
            raise PdfParseError(f"{path.name} has no page {page_number}")
        page = pdf[page_number - 1]
        for location in highlights:
            if location.page == page_number:
                page.add_highlight_annot(pymupdf.Rect(*location.bbox))
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        return bytes(pixmap.tobytes("png"))
