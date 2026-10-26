"""Page-aware PDF text extraction.

This module is the extraction foundation only. It turns one local PDF file
into a structured, page-by-page result in which every page keeps its
original one-based PDF page number, so later stages (chunking, embedding,
indexing) can build on it without losing provenance.

Scope boundaries:

* No chunking, embeddings, FAISS, Gemini, or Flask code lives here.
* No OCR. Image-only pages are *reported*, not read, so OCR stays a
  separate, explicit decision (``REQUIREMENTS.md`` §6.1 ING-05, D6).
* No document metadata is invented. This module produces no title, source
  URL, or effective date; those are supplied by the ingestion stage from a
  real source, not guessed here.

Requirement traceability:

* FR-ING-01 / ING-01 - PyMuPDF extracts text page by page, preserving the
  original one-based page number.
* FR-ING-05 / ING-04 / ING-06 - every page is classified as exactly one of
  ``text``, ``blank``, ``image-only``, or ``extraction failure``. No outcome
  is collapsed into another, and a non-text page is never returned as valid
  empty text.
* ING-05 - image-only and scan-only pages are reported as such.

Known limitation
----------------
Distinguishing a genuinely blank page from an image-only page depends on
PyMuPDF reporting image content for the page. A page whose only content is
vector drawing (no raster image) is reported as ``blank``, because this
module treats "no extractable text and no image" as blank. That is a real,
stated limitation rather than a certainty the implementation cannot
support.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Page outcome: the page yielded machine-readable text.
PAGE_TEXT = "text"

#: Page outcome: the page genuinely has no content.
PAGE_BLANK = "blank"

#: Page outcome: the page has content that is not machine-readable text
#: (a scan or a picture). Not blank; OCR is a separate, deferred path.
PAGE_IMAGE_ONLY = "image-only"

#: Page outcome: text was expected but extraction produced none because
#: extraction raised. Not blank.
PAGE_EXTRACTION_FAILURE = "extraction failure"

#: The complete set of page outcomes. Every page gets exactly one of these.
PAGE_OUTCOMES = (PAGE_TEXT, PAGE_BLANK, PAGE_IMAGE_ONLY, PAGE_EXTRACTION_FAILURE)

__all__ = [
    "PAGE_TEXT",
    "PAGE_BLANK",
    "PAGE_IMAGE_ONLY",
    "PAGE_EXTRACTION_FAILURE",
    "PAGE_OUTCOMES",
    "ExtractedPage",
    "ExtractionResult",
    "PdfExtractionError",
    "classify_page_outcome",
    "extract_pdf",
]


def _require_pymupdf():
    """Import PyMuPDF, or raise an error naming exactly what is missing.

    The import is deferred to the moment a PDF is actually extracted. Nothing
    else in this module needs PyMuPDF: the page-outcome constants, the value
    objects and :func:`classify_page_outcome` are plain Python. Deferring the
    import is what lets the chunking, canonical, indexing and retrieval stages
    import this module in an interpreter that has no PDF toolkit — only calling
    :func:`extract_pdf` there fails, with a message that says which interpreter
    is missing the package.
    """
    try:  # PyMuPDF 1.24+ exposes the package as ``pymupdf``.
        import pymupdf as fitz
    except ImportError:  # older releases expose only the legacy ``fitz`` name
        try:
            import fitz
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError(
                "PyMuPDF is required for PDF extraction but is not installed in "
                "this Python environment. Install it with: "
                "python -m pip install PyMuPDF"
            ) from exc
    return fitz


class PdfExtractionError(Exception):
    """Raised when a PDF cannot be opened, read, or parsed.

    Extraction never returns an empty successful result to signal a broken
    input: a missing path, an unreadable file, a directory, an encrypted
    document, and a malformed or unparsable file all raise this error with a
    message that says what went wrong.
    """


@dataclass(frozen=True)
class ExtractedPage:
    """One page of a PDF, with its original page number and its outcome.

    ``page_number`` is the one-based number of the page in the original PDF
    and is the provenance later stages must keep. ``text`` is empty for any
    outcome other than :data:`PAGE_TEXT`; consumers must branch on
    ``outcome``, never on whether ``text`` is empty.
    """

    page_number: int
    outcome: str
    text: str = ""
    image_count: int = 0
    error: str | None = None

    @property
    def has_text(self) -> bool:
        """True only when this page's outcome is :data:`PAGE_TEXT`."""
        return self.outcome == PAGE_TEXT


@dataclass(frozen=True)
class ExtractionResult:
    """The structured result of extracting one PDF file.

    ``pages`` holds every page in original order, so no page is dropped and
    no page number is renumbered. ``source_path`` is the path that was
    opened; no other document metadata is produced or guessed.
    """

    source_path: str
    page_count: int
    pages: tuple[ExtractedPage, ...] = field(default_factory=tuple)

    def text_pages(self) -> tuple[ExtractedPage, ...]:
        """The pages that yielded text, in original order."""
        return tuple(page for page in self.pages if page.outcome == PAGE_TEXT)

    def non_text_pages(self) -> tuple[ExtractedPage, ...]:
        """The pages that did not yield text, in original order."""
        return tuple(page for page in self.pages if page.outcome != PAGE_TEXT)


def classify_page_outcome(
    *,
    text: str | None = None,
    image_count: int = 0,
    error: str | None = None,
) -> str:
    """Return the single outcome for one page.

    The decision order is deliberate and must not be reordered quietly:

    1. An extraction error is an :data:`PAGE_EXTRACTION_FAILURE`. A failure
       is never reported as blank.
    2. Text that is not only whitespace is :data:`PAGE_TEXT`.
    3. Otherwise, reported image content means :data:`PAGE_IMAGE_ONLY`. An
       image-only page is never reported as blank.
    4. Otherwise the page is :data:`PAGE_BLANK`.
    """
    if error is not None:
        return PAGE_EXTRACTION_FAILURE
    if text is not None and text.strip():
        return PAGE_TEXT
    if image_count > 0:
        return PAGE_IMAGE_ONLY
    return PAGE_BLANK


def _count_page_images(page: "fitz.Page") -> int:
    """Count image content reported for a page.

    Rendered image blocks are preferred, because they describe what is
    actually drawn on the page. Pages that report no rendered blocks fall
    back to the image XObjects the page references.
    """
    blocks = page.get_text("dict").get("blocks", [])
    rendered = sum(1 for block in blocks if block.get("type") == 1)
    if rendered:
        return rendered
    return len(page.get_images(full=True))


def _extract_page(page: "fitz.Page", page_number: int) -> ExtractedPage:
    """Extract and classify a single page, preserving its page number."""
    try:
        text = page.get_text("text")
        image_count = 0
        if not text.strip():
            image_count = _count_page_images(page)
    except Exception as exc:  # PyMuPDF raises a variety of error types here
        return ExtractedPage(
            page_number=page_number,
            outcome=PAGE_EXTRACTION_FAILURE,
            error=f"{type(exc).__name__}: {exc}",
        )

    outcome = classify_page_outcome(text=text, image_count=image_count)
    return ExtractedPage(
        page_number=page_number,
        outcome=outcome,
        text=text if outcome == PAGE_TEXT else "",
        image_count=image_count,
    )


def extract_pdf(path: str | os.PathLike[str]) -> ExtractionResult:
    """Extract text from a local PDF, page by page.

    Returns an :class:`ExtractionResult` holding every page with its
    original one-based number. Raises :class:`PdfExtractionError` if the
    path is missing, is not a file, cannot be read, is encrypted, or is not
    a parsable PDF. A broken input never produces a successful empty result.

    Raises ``ImportError`` if PyMuPDF is not installed in the running
    interpreter; that is the only operation in this module that needs it.
    """
    fitz = _require_pymupdf()
    source_path = os.fspath(path)
    display_path = os.path.abspath(source_path)

    if not os.path.exists(source_path):
        raise PdfExtractionError(f"PDF not found: {display_path}")
    if not os.path.isfile(source_path):
        raise PdfExtractionError(f"Not a file: {display_path}")
    if not os.access(source_path, os.R_OK):
        raise PdfExtractionError(f"PDF is not readable: {display_path}")

    try:
        document = fitz.open(source_path)
    except Exception as exc:
        raise PdfExtractionError(
            f"Could not open PDF ({display_path}): {type(exc).__name__}: {exc}"
        ) from exc

    try:
        if document.needs_pass:
            raise PdfExtractionError(
                f"PDF is encrypted and requires a password: {display_path}"
            )

        page_count = document.page_count
        if page_count < 1:
            raise PdfExtractionError(
                f"PDF contains no pages and cannot be parsed as a document: "
                f"{display_path}"
            )

        pages = tuple(
            _extract_page(document.load_page(index), index + 1)
            for index in range(page_count)
        )
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(
            f"Failed while reading pages of {display_path}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        document.close()

    return ExtractionResult(
        source_path=display_path,
        page_count=page_count,
        pages=pages,
    )
