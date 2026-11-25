import hashlib

import pytest

from exga.document import (
    chunk,
    estimate_tokens,
    find_span,
    is_heading_line,
    locate,
    match_locations,
    matched_text,
    text_document,
)
from exga.schemas import Chunk, Document, Page, SpanLocation

SIMILARITY = 0.9
PAPER_ID = hashlib.sha256(b"layout fixture").hexdigest()


def laid_out_page(number: int, lines: list[str]) -> Page:
    # each word is 10 points wide per character, each line 12 points tall, 2 points apart
    words, boxes, line_keys = [], [], []
    for line_index, line in enumerate(lines):
        x = 72.0
        y0 = 100.0 + 14.0 * line_index
        for word in line.split():
            words.append(word)
            boxes.append((x, y0, x + 10.0 * len(word), y0 + 12.0))
            line_keys.append(line_index)
            x += 10.0 * len(word) + 5.0
    return Page(
        number=number,
        text="\n\n".join(lines),
        words=tuple(words),
        boxes=tuple(boxes),
        lines=tuple(line_keys),
    )


DOCUMENT = Document(
    paper_id=PAPER_ID,
    filename="fixture.pdf",
    source="pdf",
    pages=(
        laid_out_page(1, ["A total of 120 participants were", "randomised to two arms."]),
        laid_out_page(2, ["This case-control comparison included", "120 participants overall."]),
        laid_out_page(3, ["Outcomes were assessed at random-", "isation and at twelve weeks."]),
    ),
)


def test_text_document_is_one_layout_free_page_keyed_by_its_hash() -> None:
    document = text_document("Sixty patients were enrolled.", "PMC1.md")

    assert document.paper_id == hashlib.sha256(b"Sixty patients were enrolled.").hexdigest()
    assert document.source == "text"
    assert document.pages[0].words == ("Sixty", "patients", "were", "enrolled.")
    assert document.pages[0].boxes == ()


def test_every_exact_occurrence_is_found() -> None:
    matches = locate(DOCUMENT, "120 participants", min_similarity=SIMILARITY)

    assert [(m.page, m.method) for m in matches] == [(1, "exact"), (2, "exact")]
    assert matched_text(DOCUMENT, matches[0]) == "120 participants"


def test_a_quote_spanning_two_lines_is_found_exactly() -> None:
    [match] = locate(DOCUMENT, "120 participants were randomised", min_similarity=SIMILARITY)

    assert (match.page, match.start, match.end) == (1, 3, 7)


def test_case_punctuation_and_hyphens_are_matched_after_normalising() -> None:
    [match] = locate(DOCUMENT, "This Case Control comparison", min_similarity=SIMILARITY)

    assert match.method == "normalised"
    assert matched_text(DOCUMENT, match) == "This case-control comparison"


def test_a_word_split_by_a_line_break_hyphen_is_found_fuzzily() -> None:
    [match] = locate(DOCUMENT, "assessed at randomisation", min_similarity=SIMILARITY)

    assert match.method == "fuzzy"
    assert match.page == 3
    assert match.similarity >= SIMILARITY
    assert "assessed" in matched_text(DOCUMENT, match)


@pytest.mark.parametrize("text", ["the trial was stopped early for harm", "", "   ", "..."])
def test_text_that_is_absent_or_empty_is_not_found(text: str) -> None:
    assert locate(DOCUMENT, text, min_similarity=SIMILARITY) == []


def test_a_fuzzy_match_below_the_threshold_is_not_reported() -> None:
    assert locate(DOCUMENT, "assessed at randomisation", min_similarity=0.99) == []


def test_highlights_cover_each_matched_line_once() -> None:
    [match] = locate(DOCUMENT, "120 participants were randomised", min_similarity=SIMILARITY)

    first_line, second_line = match_locations(DOCUMENT, match)

    words = DOCUMENT.pages[0].boxes
    assert first_line == SpanLocation(page=1, bbox=(words[3][0], 100.0, words[5][2], 112.0))
    assert second_line == SpanLocation(page=1, bbox=(72.0, 114.0, words[6][2], 126.0))


def test_find_span_returns_rectangles_for_every_match() -> None:
    locations = find_span(DOCUMENT, "120 participants", min_similarity=SIMILARITY)

    assert [location.page for location in locations] == [1, 2]


def test_plain_text_documents_are_searched_but_have_nothing_to_highlight() -> None:
    document = text_document("Sixty patients were enrolled in each arm.", "PMC1.md")

    assert locate(document, "patients were enrolled", min_similarity=SIMILARITY)
    assert find_span(document, "patients were enrolled", min_similarity=SIMILARITY) == []


def section_document(paragraphs_per_section: int) -> Document:
    sections = ["Abstract", "1. Introduction", "2. Methods", "3. Results", "Discussion"]
    pages = []
    for number, heading in enumerate(sections, start=1):
        body = [f"{heading} paragraph {i} " + "word " * 40 for i in range(paragraphs_per_section)]
        pages.append(Page(number=number, text="\n\n".join([heading, *body]), words=()))
    return Document(paper_id=PAPER_ID, filename="long.pdf", source="pdf", pages=tuple(pages))


def test_a_short_document_is_one_chunk() -> None:
    [only] = chunk(section_document(1), max_tokens=10_000)

    assert (only.first_page, only.last_page) == (1, 5)
    assert only.sections == ("abstract", "introduction", "methods", "results", "discussion")


def test_long_documents_split_within_the_budget_and_lose_no_text() -> None:
    document = section_document(4)

    chunks = chunk(document, max_tokens=300)

    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 300 for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # whitespace around paragraphs is dropped; every word survives, in order
    rejoined = " ".join(c.text for c in chunks).split()
    assert rejoined == " ".join(page.text for page in document.pages).split()


def test_chunks_prefer_to_start_at_section_headings() -> None:
    chunks = chunk(section_document(2), max_tokens=250)

    assert chunks[1].text.startswith(("1. Introduction", "2. Methods", "3. Results"))


def test_a_paragraph_longer_than_the_budget_is_split_at_spaces() -> None:
    page = Page(number=1, text="token " * 500, words=())
    document = Document(paper_id=PAPER_ID, filename="x.pdf", source="pdf", pages=(page,))

    chunks = chunk(document, max_tokens=100)

    assert len(chunks) > 1
    assert all(estimate_tokens(c.text) <= 100 for c in chunks)
    assert all(c.text.startswith("token") for c in chunks)


@pytest.mark.parametrize(
    "line", ["Abstract", "2. Methods", "3.1 Results:", "## Discussion", "  Conclusions.  "]
)
def test_lines_that_are_only_a_section_name_are_headings(line: str) -> None:
    assert is_heading_line(line)


@pytest.mark.parametrize(
    "line", ["Results were similar in both arms", "Study design", "", "2. Randomisation"]
)
def test_prose_and_other_titles_are_not_headings(line: str) -> None:
    assert not is_heading_line(line)


def test_markdown_headings_start_chunks() -> None:
    text = "## Methods\n\n" + "word " * 300 + "\n\n## Results\n\n" + "word " * 300

    chunks = chunk(text_document(text, "PMC1.md"), max_tokens=500)

    assert [c.sections for c in chunks] == [("methods",), ("results",)]


def test_chunk_rejects_a_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        chunk(DOCUMENT, max_tokens=0)


def test_chunks_record_the_page_of_every_paragraph() -> None:
    [only] = chunk(section_document(1), max_tokens=10_000)

    assert only.paragraph_pages == (1, 1, 2, 2, 3, 3, 4, 4, 5, 5)


def test_a_chunk_with_a_page_missing_for_a_paragraph_is_rejected() -> None:
    with pytest.raises(ValueError, match="2 paragraphs but 1 paragraph pages"):
        Chunk(index=0, text="one\n\ntwo", paragraph_pages=(1,), sections=())
