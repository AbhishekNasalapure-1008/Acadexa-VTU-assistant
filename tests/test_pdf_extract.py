"""Tests for :mod:`app.ingestion.pdf_extract`.

Run from the repository root:

    python -m unittest discover -s tests -t . -v

Test fixtures are built locally with PyMuPDF and written to a temporary
directory. No document is downloaded and no VTU syllabus content is
invented; the text used here is deliberately meaningless placeholder text.
"""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    from app.ingestion import pdf_extract
    from app.ingestion.pdf_extract import (
        PAGE_BLANK,
        PAGE_EXTRACTION_FAILURE,
        PAGE_IMAGE_ONLY,
        PAGE_TEXT,
        PdfExtractionError,
        classify_page_outcome,
        extract_pdf,
    )

    _IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # PyMuPDF is not installed in the environment
    pdf_extract = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


_SKIP_REASON = f"PyMuPDF is not importable, so PDF tests cannot run: {_IMPORT_ERROR}"


def _write_pdf(path: str, build) -> str:
    """Build a PDF at ``path`` using a callback that fills a new document."""
    fitz = pdf_extract.fitz
    document = fitz.open()
    try:
        build(document)
        document.save(path)
    finally:
        document.close()
    return path


def _add_text_page(document, text: str) -> None:
    page = document.new_page()
    page.insert_text((72, 72), text)


def _add_image_page(document) -> None:
    """Add a page whose only content is a raster image (no text)."""
    fitz = pdf_extract.fitz
    page = document.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32))
    pixmap.set_rect(pixmap.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(72, 72, 232, 232), pixmap=pixmap)


@unittest.skipIf(pdf_extract is None, _SKIP_REASON)
class TextExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def _pdf_path(self, name: str = "fixture.pdf") -> str:
        return os.path.join(self.tmpdir, name)

    def test_multiple_text_pages_keep_one_based_page_numbers(self) -> None:
        path = _write_pdf(
            self._pdf_path(),
            lambda doc: [_add_text_page(doc, text) for text in ("Alpha", "Beta", "Gamma")],
        )

        result = extract_pdf(path)

        self.assertEqual(result.page_count, 3)
        self.assertEqual([page.page_number for page in result.pages], [1, 2, 3])
        self.assertEqual([page.outcome for page in result.pages], [PAGE_TEXT] * 3)
        self.assertIn("Alpha", result.pages[0].text)
        self.assertIn("Beta", result.pages[1].text)
        self.assertIn("Gamma", result.pages[2].text)
        # Page text is not shuffled between pages.
        self.assertNotIn("Beta", result.pages[0].text)
        self.assertNotIn("Alpha", result.pages[1].text)

    def test_blank_page_is_reported_blank_not_failed(self) -> None:
        def build(document):
            _add_text_page(document, "First")
            document.new_page()  # genuinely empty page
            _add_text_page(document, "Third")

        result = extract_pdf(_write_pdf(self._pdf_path(), build))

        self.assertEqual(result.page_count, 3)
        self.assertEqual(
            [page.outcome for page in result.pages],
            [PAGE_TEXT, PAGE_BLANK, PAGE_TEXT],
        )
        blank = result.pages[1]
        self.assertEqual(blank.page_number, 2)
        self.assertEqual(blank.text, "")
        self.assertIsNone(blank.error)
        self.assertEqual(blank.image_count, 0)
        # The blank page is not silently dropped from the result.
        self.assertEqual([page.page_number for page in result.text_pages()], [1, 3])
        self.assertEqual([page.page_number for page in result.non_text_pages()], [2])

    def test_image_only_page_is_image_only_not_blank(self) -> None:
        def build(document):
            _add_image_page(document)
            _add_text_page(document, "Caption")

        result = extract_pdf(_write_pdf(self._pdf_path(), build))

        image_page = result.pages[0]
        self.assertEqual(image_page.page_number, 1)
        self.assertEqual(image_page.outcome, PAGE_IMAGE_ONLY)
        self.assertNotEqual(image_page.outcome, PAGE_BLANK)
        self.assertEqual(image_page.text, "")
        self.assertGreater(image_page.image_count, 0)
        self.assertEqual(result.pages[1].outcome, PAGE_TEXT)

    def test_accepts_a_pathlike_path(self) -> None:
        import pathlib

        path = _write_pdf(
            self._pdf_path(), lambda doc: _add_text_page(doc, "Only page")
        )

        result = extract_pdf(pathlib.Path(path))

        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.pages[0].page_number, 1)
        self.assertEqual(result.pages[0].outcome, PAGE_TEXT)


@unittest.skipIf(pdf_extract is None, _SKIP_REASON)
class BadInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def test_missing_path_raises(self) -> None:
        missing = os.path.join(self.tmpdir, "does-not-exist.pdf")
        with self.assertRaises(PdfExtractionError):
            extract_pdf(missing)

    def test_directory_path_raises(self) -> None:
        with self.assertRaises(PdfExtractionError):
            extract_pdf(self.tmpdir)

    def test_malformed_pdf_raises(self) -> None:
        path = os.path.join(self.tmpdir, "malformed.pdf")
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\nthis file is truncated and not parsable")

        with self.assertRaises(PdfExtractionError):
            extract_pdf(path)

    def test_empty_file_raises(self) -> None:
        path = os.path.join(self.tmpdir, "empty.pdf")
        with open(path, "wb"):
            pass

        with self.assertRaises(PdfExtractionError):
            extract_pdf(path)

    def test_encrypted_pdf_raises_rather_than_returning_empty_text(self) -> None:
        fitz = pdf_extract.fitz
        path = os.path.join(self.tmpdir, "encrypted.pdf")
        document = fitz.open()
        try:
            document.new_page().insert_text((72, 72), "locked content")
            document.save(
                path,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw="user",
                owner_pw="owner",
            )
        finally:
            document.close()

        # Confirm the fixture really is encrypted before asserting on it.
        probe = fitz.open(path)
        try:
            self.assertTrue(probe.needs_pass)
        finally:
            probe.close()

        with self.assertRaises(PdfExtractionError):
            extract_pdf(path)


@unittest.skipIf(pdf_extract is None, _SKIP_REASON)
class ClassifyPageOutcomeTests(unittest.TestCase):
    """Covers the four-way page rule at the classification level.

    These call the same ``classify_page_outcome`` the extraction loop uses,
    so the blank / image-only / extraction-failure distinctions are checked
    directly. :class:`PageLevelExtractionFailureTests` covers the same rule
    from a real PyMuPDF page error.
    """

    def test_error_is_extraction_failure_not_blank(self) -> None:
        self.assertEqual(
            classify_page_outcome(error="RuntimeError: boom"),
            PAGE_EXTRACTION_FAILURE,
        )

    def test_error_takes_precedence_over_absent_text_and_images(self) -> None:
        self.assertEqual(
            classify_page_outcome(text="", image_count=0, error="boom"),
            PAGE_EXTRACTION_FAILURE,
        )

    def test_real_text_is_text(self) -> None:
        self.assertEqual(classify_page_outcome(text="Module 1"), PAGE_TEXT)

    def test_whitespace_only_text_has_no_content(self) -> None:
        self.assertEqual(classify_page_outcome(text=" \n\t "), PAGE_BLANK)

    def test_images_without_text_are_image_only(self) -> None:
        self.assertEqual(
            classify_page_outcome(text="", image_count=2),
            PAGE_IMAGE_ONLY,
        )

    def test_nothing_at_all_is_blank(self) -> None:
        self.assertEqual(
            classify_page_outcome(text="", image_count=0),
            PAGE_BLANK,
        )

    def test_every_outcome_is_a_distinct_declared_value(self) -> None:
        outcomes = {
            classify_page_outcome(text="text"),
            classify_page_outcome(text=""),
            classify_page_outcome(text="", image_count=1),
            classify_page_outcome(error="boom"),
        }
        self.assertEqual(outcomes, set(pdf_extract.PAGE_OUTCOMES))
        self.assertEqual(len(set(pdf_extract.PAGE_OUTCOMES)), 4)


@unittest.skipIf(pdf_extract is None, _SKIP_REASON)
class PageLevelExtractionFailureTests(unittest.TestCase):
    """Covers a page-level PyMuPDF error reaching the extraction loop.

    A corrupt content stream could not be produced reliably, so the error is
    provoked with a page object taken from a document that has been closed:
    calling ``get_text`` on it raises a real PyMuPDF error. Nothing is
    monkeypatched, and if a future PyMuPDF build stops raising here the test
    reports as skipped rather than passing.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def test_page_error_is_extraction_failure_and_keeps_page_number(self) -> None:
        fitz = pdf_extract.fitz
        path = _write_pdf(
            os.path.join(self.tmpdir, "one-page.pdf"),
            lambda doc: _add_text_page(doc, "Text that will not be read"),
        )

        document = fitz.open(path)
        page = document.load_page(0)
        document.close()

        try:
            page.get_text("text")
        except Exception:
            pass
        else:
            self.skipTest(
                "This PyMuPDF build does not raise for a page taken from a "
                "closed document, so the page-level error path cannot be "
                "provoked here."
            )

        extracted = pdf_extract._extract_page(page, 4)

        self.assertEqual(extracted.outcome, PAGE_EXTRACTION_FAILURE)
        self.assertNotEqual(extracted.outcome, PAGE_BLANK)
        self.assertNotEqual(extracted.outcome, PAGE_TEXT)
        self.assertEqual(extracted.page_number, 4)
        self.assertEqual(extracted.text, "")
        self.assertIsNotNone(extracted.error)


if __name__ == "__main__":
    unittest.main()
