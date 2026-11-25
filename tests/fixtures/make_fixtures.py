"""regenerate the synthetic PDF fixtures in this folder: python tests/fixtures/make_fixtures.py

every fixture is invented test text, labelled as such on the page; none is a real study.
text is placed line by line, so the tests know exactly where each word sits.
"""

from pathlib import Path

import pymupdf

FOLDER = Path(__file__).parent
FONT_SIZE = 11
LINE_HEIGHT = 15
LEFT_MARGIN = 72

TRIAL_PAGES = [
    [
        "Synthetic trial report (exga test fixture; not a real study)",
        "",
        "Abstract",
        "A total of 120 participants were randomised to the intervention or",
        "to usual care. The primary outcome was depression score at twelve weeks.",
        "",
        "2. Methods",
        "Participants were recruited in Ghana between 2021 and 2022 and were",
        "assessed at random-",
        "isation and after twelve weeks. The study design was a randomised",
        "controlled trial with two parallel arms.",
    ],
    [
        "3. Results",
        "The mean age was 54.2 years (SD 8.1). Depression scores fell more with",
        "the intervention than with usual care (difference -3.5 points).",
        "",
        "Discussion",
        "The intervention reduced depression scores compared with usual care.",
    ],
]


def _new_pdf() -> pymupdf.Document:
    pdf = pymupdf.open()
    pdf.set_metadata({"producer": "exga test fixtures", "creationDate": "", "modDate": ""})
    return pdf


def _save(pdf: pymupdf.Document, name: str) -> None:
    # fixed metadata and no new file id keep the bytes, and so the paper_id, reproducible
    pdf.save(FOLDER / name, garbage=4, deflate=True, no_new_id=True)
    pdf.close()


def _write_lines(page: pymupdf.Page, lines: list[str], *, x: float, top: float) -> None:
    for index, line in enumerate(lines):
        if line:
            page.insert_text(
                (x, top + index * LINE_HEIGHT), line, fontsize=FONT_SIZE, fontname="helv"
            )


def make_trial_report() -> None:
    """two pages of single-column text with section headings and a hyphenated line break."""
    pdf = _new_pdf()
    for lines in TRIAL_PAGES:
        page = pdf.new_page(width=595, height=842)
        _write_lines(page, lines, x=LEFT_MARGIN, top=90)
    _save(pdf, "trial_report.pdf")


def make_two_column() -> None:
    """one page with two text columns, to check that reading order keeps columns apart."""
    pdf = _new_pdf()
    page = pdf.new_page(width=595, height=842)
    left = ["Left column first line about", "the recruitment of patients."]
    right = ["Right column first line about", "the follow-up of patients."]
    _write_lines(page, left, x=LEFT_MARGIN, top=90)
    _write_lines(page, right, x=320, top=90)
    _write_lines(
        page,
        ["Synthetic two-column page (exga test fixture; not a real study)"] * 3,
        x=LEFT_MARGIN,
        top=200,
    )
    _save(pdf, "two_column.pdf")


def make_image_only() -> None:
    """a page with a drawing but no text, standing in for a scanned PDF."""
    pdf = _new_pdf()
    page = pdf.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(100, 100, 400, 300), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    _save(pdf, "image_only.pdf")


def make_encrypted() -> None:
    """a password-protected PDF."""
    pdf = _new_pdf()
    page = pdf.new_page(width=595, height=842)
    _write_lines(
        page, ["Encrypted synthetic page (exga test fixture)."] * 20, x=LEFT_MARGIN, top=90
    )
    pdf.save(
        FOLDER / "encrypted.pdf",
        encryption=pymupdf.mupdf.PDF_ENCRYPT_AES_256,
        owner_pw="fixture-owner",
        user_pw="fixture-user",
    )
    pdf.close()


def make_not_a_pdf() -> None:
    """a file with a .pdf name whose bytes are not a PDF."""
    (FOLDER / "not_a_pdf.pdf").write_bytes(b"this file is plain text with a pdf extension\n")


if __name__ == "__main__":
    make_trial_report()
    make_two_column()
    make_image_only()
    make_encrypted()
    make_not_a_pdf()
