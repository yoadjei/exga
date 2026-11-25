"""pure operations on a loaded document: find where text occurs, and split long papers.

`locate` and `find_span` implement spec 7.1: try an exact match, then a match after
normalisation, then the best fuzzy match. `chunk` splits a paper into prompt-sized runs,
preferring section boundaries. nothing here reads files; `pdf.py` builds the documents.
"""

import hashlib
import math
import re
from collections.abc import Iterator

from rapidfuzz import fuzz

from exga.matching import normalise_text
from exga.schemas import Box, Chunk, Document, Page, SpanLocation, TextMatch

# a rough average for English text under the BPE tokenizers of current LLMs; the estimate
# only decides where to split, so an error of 20% costs a little prompt space, nothing more
CHARS_PER_TOKEN = 4
# optional markdown hashes and section number, then a standard section name
_HEADING_PATTERN = (
    r"^(?:#+\s*)?(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(abstract|introduction|background|methods?|materials and methods|participants|"
    r"results|discussion|conclusions?|limitations|references|acknowledg(?:e)?ments)\b"
)
_SECTION_HEADING = re.compile(_HEADING_PATTERN, re.IGNORECASE)
# the whole line is the heading, so body lines that begin with "Results" are not split off
_HEADING_LINE = re.compile(_HEADING_PATTERN + r"\s*[.:]?\s*$", re.IGNORECASE)
# a heading is a short paragraph; long ones that start with "Results" are prose
_MAX_HEADING_CHARS = 60
# pdf.py separates paragraphs (PyMuPDF text blocks) with a blank line
_PARAGRAPH_BREAK = "\n\n"


def text_document(text: str, filename: str) -> Document:
    """return a layout-free Document for plain text, such as a benchmark article (spec 10.1).

    paper_id is the sha256 of the UTF-8 text, so the same text always gets the same id.
    """
    paper_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
    page = Page(number=1, text=text, words=tuple(text.split()))
    return Document(paper_id=paper_id, filename=filename, source="text", pages=(page,))


def locate(document: Document, text: str, *, min_similarity: float) -> list[TextMatch]:
    """return where text occurs in document, or [] when it is not found.

    tries, in order: every exact occurrence; every occurrence after normalisation (case,
    punctuation, spacing); the single best fuzzy match with similarity >= min_similarity.
    """
    target_words = text.split()
    target_tokens = normalise_text(text).split()
    if not target_words or not target_tokens:
        return []
    exact = [
        TextMatch(page=page.number, start=start, end=end, method="exact", similarity=1.0)
        for page in document.pages
        for start, end in _occurrences(list(page.words), target_words)
    ]
    if exact:
        return exact
    normalised = [
        TextMatch(page=page.number, start=start, end=end, method="normalised", similarity=1.0)
        for page in document.pages
        for start, end in _normalised_occurrences(page, target_tokens)
    ]
    if normalised:
        return normalised
    best = max(
        (_best_fuzzy(page, " ".join(target_tokens)) for page in document.pages),
        key=lambda match: match.similarity if match else -1.0,
    )
    return [best] if best is not None and best.similarity >= min_similarity else []


def find_span(document: Document, text: str, *, min_similarity: float) -> list[SpanLocation]:
    """return one highlight rectangle per text line for every match of text (spec 7.1).

    empty when text is not found or when the document has no layout (plain text).
    """
    return [
        location
        for match in locate(document, text, min_similarity=min_similarity)
        for location in match_locations(document, match)
    ]


def match_locations(document: Document, match: TextMatch) -> tuple[SpanLocation, ...]:
    """return the rectangles covering a match, one per text line, in reading order."""
    page = document.pages[match.page - 1]
    if not page.boxes:
        return ()
    line_boxes: dict[int, Box] = {}
    for index in range(match.start, match.end):
        line, box = page.lines[index], page.boxes[index]
        current = line_boxes.get(line, box)
        line_boxes[line] = (
            min(current[0], box[0]),
            min(current[1], box[1]),
            max(current[2], box[2]),
            max(current[3], box[3]),
        )
    return tuple(SpanLocation(page=match.page, bbox=box) for box in line_boxes.values())


def matched_text(document: Document, match: TextMatch) -> str:
    """return the document's own words covered by a match, joined by single spaces."""
    return " ".join(document.pages[match.page - 1].words[match.start : match.end])


def _occurrences(words: list[str], target: list[str]) -> Iterator[tuple[int, int]]:
    width = len(target)
    for start in range(len(words) - width + 1):
        if words[start] == target[0] and words[start : start + width] == target:
            yield start, start + width


def _normalised_tokens(page: Page) -> tuple[list[str], list[int]]:
    # one word can normalise to several tokens ("case-control") or none ("-"), so each token
    # remembers which word it came from
    tokens: list[str] = []
    owners: list[int] = []
    for index, word in enumerate(page.words):
        for token in normalise_text(word).split():
            tokens.append(token)
            owners.append(index)
    return tokens, owners


def _normalised_occurrences(page: Page, target: list[str]) -> Iterator[tuple[int, int]]:
    tokens, owners = _normalised_tokens(page)
    for start, end in _occurrences(tokens, target):
        yield owners[start], owners[end - 1] + 1


def _best_fuzzy(page: Page, target: str) -> TextMatch | None:
    tokens, owners = _normalised_tokens(page)
    if not tokens:
        return None
    haystack = " ".join(tokens)
    # partial_ratio_alignment slides the target over the page text and returns the best
    # window: the "fuzzy match over sliding windows" of spec 7.1 in one call
    alignment = fuzz.partial_ratio_alignment(target, haystack)
    if alignment is None:
        return None
    first, last = _tokens_in_span(tokens, alignment.dest_start, alignment.dest_end)
    return TextMatch(
        page=page.number,
        start=owners[first],
        end=owners[last] + 1,
        method="fuzzy",
        similarity=alignment.score / 100.0,
    )


def _tokens_in_span(tokens: list[str], char_start: int, char_end: int) -> tuple[int, int]:
    # maps a character range of " ".join(tokens) to the first and last token it touches
    first = last = 0
    position = 0
    for index, token in enumerate(tokens):
        token_end = position + len(token)
        if token_end <= char_start:
            first = index + 1
        if position < char_end:
            last = index
        position = token_end + 1
    return min(first, last), last


def estimate_tokens(text: str) -> int:
    """return a rough LLM token count for text, CHARS_PER_TOKEN characters per token."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def chunk(document: Document, max_tokens: int) -> list[Chunk]:
    """split a document into runs of at most about max_tokens, preferring section breaks.

    a new chunk starts at a section heading once the current one is half full, and whenever
    the next paragraph would not fit. a paragraph longer than max_tokens is split at spaces.
    raises ValueError when max_tokens < 1.
    """
    if max_tokens < 1:
        raise ValueError(f"chunk needs max_tokens >= 1, got {max_tokens}")
    chunks: list[Chunk] = []
    parts: list[str] = []
    pages: list[int] = []
    sections: list[str] = []
    used_chars = 0
    for page_number, paragraph in _paragraphs(document, max_tokens):
        heading = _heading(paragraph)
        # length of the chunk text if this paragraph joins it, separator included
        joined_chars = used_chars + len(_PARAGRAPH_BREAK) + len(paragraph)
        is_full = math.ceil(joined_chars / CHARS_PER_TOKEN) > max_tokens
        is_good_break = heading is not None and used_chars >= max_tokens * CHARS_PER_TOKEN // 2
        if parts and (is_full or is_good_break):
            chunks.append(_make_chunk(len(chunks), parts, pages, sections))
            parts, pages, sections, used_chars = [], [], [], 0
        used_chars += (len(_PARAGRAPH_BREAK) if parts else 0) + len(paragraph)
        parts.append(paragraph)
        pages.append(page_number)
        if heading is not None:
            sections.append(heading)
    if parts:
        chunks.append(_make_chunk(len(chunks), parts, pages, sections))
    return chunks


def _paragraphs(document: Document, max_tokens: int) -> Iterator[tuple[int, str]]:
    max_chars = max_tokens * CHARS_PER_TOKEN
    for page in document.pages:
        for paragraph in page.text.split(_PARAGRAPH_BREAK):
            text = paragraph.strip()
            while len(text) > max_chars:
                cut = text.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                yield page.number, text[:cut]
                text = text[cut:].strip()
            if text:
                yield page.number, text


def is_heading_line(line: str) -> bool:
    """True when line consists of a standard section heading only, e.g. "2. Methods"."""
    return _HEADING_LINE.match(line.strip()) is not None


def _heading(paragraph: str) -> str | None:
    if len(paragraph) > _MAX_HEADING_CHARS:
        return None
    match = _SECTION_HEADING.match(paragraph)
    return match[1].lower() if match else None


def _make_chunk(index: int, parts: list[str], pages: list[int], sections: list[str]) -> Chunk:
    return Chunk(
        index=index,
        text=_PARAGRAPH_BREAK.join(parts),
        paragraph_pages=tuple(pages),
        sections=tuple(sections),
    )
