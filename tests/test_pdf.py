import hashlib
import math
from pathlib import Path

import pymupdf
import pytest

from exga.document import chunk, find_span, locate
from exga.errors import PdfParseError
from exga.pdf import load_pdf, render_page
from exga.schemas import SpanLocation
from exga.settings import DocumentSettings

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = DocumentSettings()


@pytest.fixture(scope="module")
def trial_path() -> Path:
    return FIXTURES / "trial_report.pdf"


def test_loads_every_page_keyed_by_the_file_hash(trial_path: Path) -> None:
    document = load_pdf(trial_path, SETTINGS)

    assert document.paper_id == hashlib.sha256(trial_path.read_bytes()).hexdigest()
    assert (document.filename, document.source, len(document.pages)) == (
        "trial_report.pdf",
        "pdf",
        2,
    )


def test_page_text_keeps_headings_as_separate_paragraphs(trial_path: Path) -> None:
    first, second = load_pdf(trial_path, SETTINGS).pages

    paragraphs = first.text.split("\n\n")
    assert paragraphs[1] == "Abstract"
    assert paragraphs[2].startswith("A total of 120 participants")
    assert "2. Methods" in paragraphs
    assert second.text.split("\n\n")[0] == "3. Results"


def test_every_word_has_a_box_inside_its_page(trial_path: Path) -> None:
    page = load_pdf(trial_path, SETTINGS).pages[0]

    assert len(page.words) == len(page.boxes) == len(page.lines) > 50
    assert all(0 <= x0 <= x1 <= 595 and 0 <= y0 <= y1 <= 842 for x0, y0, x1, y1 in page.boxes)


def test_a_word_hyphenated_across_lines_is_found(trial_path: Path) -> None:
    document = load_pdf(trial_path, SETTINGS)

    [match] = locate(
        document, "assessed at randomisation and after twelve weeks", min_similarity=0.9
    )

    assert match.page == 1


def test_columns_are_read_one_after_the_other() -> None:
    text = load_pdf(FIXTURES / "two_column.pdf", SETTINGS).pages[0].text

    assert text.index("recruitment of patients") < text.index("Right column first line")


def test_a_quote_is_located_with_one_box_per_line(trial_path: Path) -> None:
    document = load_pdf(trial_path, SETTINGS)

    locations = find_span(document, "120 participants were randomised", min_similarity=0.9)

    assert [location.page for location in locations] == [1]
    x0, y0, x1, y1 = locations[0].bbox
    assert x0 < x1
    assert y0 < y1


def test_a_loaded_document_can_be_chunked(trial_path: Path) -> None:
    chunks = chunk(load_pdf(trial_path, SETTINGS), max_tokens=60)

    assert len(chunks) > 1
    assert chunks[-1].last_page == 2


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("image_only.pdf", "scanned"),
        ("encrypted.pdf", "encrypted"),
        ("not_a_pdf.pdf", "not a readable PDF"),
        ("missing.pdf", "cannot read"),
    ],
)
def test_unusable_files_raise_pdf_parse_error(name: str, message: str) -> None:
    with pytest.raises(PdfParseError, match=message):
        load_pdf(FIXTURES / name, SETTINGS)


def pixel(png: bytes, x: int, y: int) -> tuple[int, ...]:
    return tuple(pymupdf.Pixmap(png).pixel(x, y))


def test_render_scales_the_page_by_zoom(trial_path: Path) -> None:
    png = render_page(trial_path, 1, [], zoom=1.5)

    image = pymupdf.Pixmap(png)
    assert png.startswith(b"\x89PNG")
    # the pixmap covers the scaled page rounded outwards: 892.5 points become 893 pixels
    assert (image.width, image.height) == (math.ceil(595 * 1.5), math.ceil(842 * 1.5))


def test_render_draws_highlights_only_inside_their_boxes(trial_path: Path) -> None:
    box = (100.0, 400.0, 300.0, 420.0)
    zoom = 1.0

    plain = render_page(trial_path, 1, [], zoom=zoom)
    highlighted = render_page(trial_path, 1, [SpanLocation(page=1, bbox=box)], zoom=zoom)

    inside, outside = (200, 410), (200, 600)
    assert pixel(plain, *inside) == (255, 255, 255)
    red, green, blue = pixel(highlighted, *inside)[:3]
    # a yellow tint: less blue than red and green
    assert blue < red
    assert blue < green
    assert pixel(highlighted, *outside) == pixel(plain, *outside)


def test_highlights_for_other_pages_are_ignored(trial_path: Path) -> None:
    elsewhere = SpanLocation(page=2, bbox=(100.0, 400.0, 300.0, 420.0))

    assert render_page(trial_path, 1, [elsewhere], zoom=1.0) == render_page(
        trial_path, 1, [], zoom=1.0
    )


def test_render_rejects_a_page_that_does_not_exist(trial_path: Path) -> None:
    with pytest.raises(PdfParseError, match="no page 3"):
        render_page(trial_path, 3, [], zoom=1.0)
