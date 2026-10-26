"""Tests for :mod:`app.ingestion.chunking`.

Run from the repository root:

    python -m unittest discover -s tests -t . -v

Every fixture here is a synthetic :class:`~app.ingestion.pdf_extract.
ExtractionResult` built in memory from plain dataclasses. No PDF is opened, no
document is downloaded, and no VTU syllabus wording is invented: the
placeholder text used below ("Alpha beta gamma delta.") is deliberately
meaningless.

The real pilot documents are not read by this suite. Tests must not depend on
a file outside the repository, so the pilot runs live in their own scripts under
``data/processed/pilot_2022_cse_5th/`` and ``data/processed/pilot_2025_sem3/``
instead.

Size assertions use ``chars_per_token=1`` so that the settings' token numbers
and the enforced character limits are the same number, which makes the expected
chunk sizes exactly checkable rather than approximately checkable.
"""

from __future__ import annotations

import json
import unittest

try:
    from app.ingestion import chunking
    from app.ingestion.chunking import (
        APPROX_CHARS_PER_TOKEN,
        BOUNDARY_DETECTED,
        BOUNDARY_SUPPLIED,
        BOUNDARY_UNKNOWN,
        DEFAULT_OVERLAP_TOKENS,
        DEFAULT_TARGET_TOKENS,
        ChunkingError,
        ChunkingSettings,
        DocumentMetadata,
        FurnitureRemoval,
        approx_token_count,
        chunk_document,
    )
    from app.ingestion.pdf_extract import (
        PAGE_BLANK,
        PAGE_IMAGE_ONLY,
        PAGE_TEXT,
        ExtractedPage,
        ExtractionResult,
    )

    _IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # PyMuPDF is not installed in the environment
    chunking = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


_SKIP_REASON = f"the ingestion modules cannot be imported, so chunking tests cannot run: {_IMPORT_ERROR}"

#: A meaningless placeholder paragraph. Nothing here is real VTU content.
PARA = "Alpha beta gamma delta."


def _paras(count: int) -> list[str]:
    """Distinct placeholder paragraphs.

    The paragraphs are numbered so no paragraph is a copy of another. Repeating
    one paragraph would let a long accidental suffix/prefix match appear between
    two chunks purely from the repetition, which would make an overlap
    assertion pass (or fail) for the wrong reason.
    """
    return [f"[{index}] {PARA}" for index in range(count)]


def _text_page(page_number: int, text: str) -> ExtractedPage:
    """A page that yielded text."""
    return ExtractedPage(page_number=page_number, outcome=PAGE_TEXT, text=text)


def _result(pages, source_path: str = "synthetic.pdf") -> ExtractionResult:
    """An extraction result holding exactly the pages given, in order."""
    return ExtractionResult(
        source_path=source_path,
        page_count=len(pages),
        pages=tuple(pages),
    )


def _settings(target_tokens: int, overlap_tokens: int) -> ChunkingSettings:
    """Settings whose token numbers equal their character limits."""
    return ChunkingSettings(
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
        chars_per_token=1,
    )


def _meta(document_id: str = "doc-1", **overrides) -> DocumentMetadata:
    """Document metadata with only the fields the test cares about set."""
    fields = {
        "version_id": "v1",
        "filename": "synthetic.pdf",
        "document_type": "syllabus",
        "scheme": "2022",
        "branch": "CSE",
        "semester": "5",
    }
    fields.update(overrides)
    return DocumentMetadata(document_id=document_id, **fields)


def _header_page(page_number: int, body_paragraphs=(), code: str | None = "BCS101",
                 subject_name: str | None = None) -> ExtractedPage:
    """A page shaped like a VTU syllabus subject page.

    The layout mirrors the real document: an optional subject title, a
    ``Semester`` label, a ``Course Code`` label, the code itself, then body
    paragraphs separated by blank lines.
    """
    lines: list[str] = []
    if subject_name:
        lines.append(subject_name)
    if subject_name:
        lines.extend(["Semester", "V"])
    if code:
        lines.extend(["Course Code", code])
    for paragraph in body_paragraphs:
        lines.extend(["", paragraph])
    return _text_page(page_number, "\n".join(lines))


def _header_page_2025(page_number: int, body_paragraphs=(), code: str | None = "1BMATCS301",
                      subject_name: str | None = "DEMO SUBJECT 2025") -> ExtractedPage:
    """A page shaped like a VTU 2025-scheme syllabus subject page.

    The 2025 layout differs from the 2022 one in two ways: the course code
    carries a leading programme digit, and the ``Semester`` label is printed
    *below* the ``Course Code`` label, so the subject title sits directly above
    the label. Both are the same label-and-title structure as the 2022 layout.
    """
    lines: list[str] = []
    if subject_name:
        lines.append(subject_name)
    if code:
        lines.extend(["Course Code", code])
    lines.extend(["Scheme", "2025", "Semester", "3"])
    for paragraph in body_paragraphs:
        lines.extend(["", paragraph])
    return _text_page(page_number, "\n".join(lines))


def _furniture_page(page_number: int, body: str) -> ExtractedPage:
    """A page carrying the pilot document's repeated page furniture.

    The layout mirrors the real pages: an annexure label, the bare counter
    printed under it, one body line, and the date stamp at the foot.
    """
    lines = ["Annexure-II 1", "1", body, "12082024"]
    return _text_page(page_number, "\n".join(lines))


def _shared_suffix_prefix_length(a: str, b: str) -> int:
    """The longest k for which ``a`` ends with the same k characters ``b`` starts with."""
    for k in range(min(len(a), len(b)), 0, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def _chunks_by_section(result):
    """Split the chunk list back into per-section lists, using the summaries."""
    groups = []
    cursor = 0
    for section in result.sections:
        groups.append(result.chunks[cursor : cursor + section.chunk_count])
        cursor += section.chunk_count
    return groups


@unittest.skipIf(chunking is None, _SKIP_REASON)
class ChunkingSettingsTests(unittest.TestCase):
    """The size parameters and their validation."""

    def test_defaults_match_the_pilot_values(self):
        settings = ChunkingSettings()
        self.assertEqual(settings.target_tokens, DEFAULT_TARGET_TOKENS)
        self.assertEqual(settings.overlap_tokens, DEFAULT_OVERLAP_TOKENS)
        self.assertEqual(settings.chars_per_token, APPROX_CHARS_PER_TOKEN)
        self.assertEqual(settings.target_chars, 2000)
        self.assertEqual(settings.overlap_chars, 300)

    def test_fingerprint_is_stable_and_distinguishes_settings(self):
        self.assertEqual(ChunkingSettings().fingerprint, "t500-o75-c4")
        self.assertNotEqual(
            ChunkingSettings().fingerprint,
            ChunkingSettings(target_tokens=400).fingerprint,
        )

    def test_non_positive_target_is_rejected(self):
        for value in (0, -1):
            with self.subTest(target_tokens=value):
                with self.assertRaises(ChunkingError):
                    ChunkingSettings(target_tokens=value)

    def test_negative_overlap_is_rejected(self):
        with self.assertRaises(ChunkingError):
            ChunkingSettings(overlap_tokens=-1)

    def test_overlap_at_least_target_is_rejected(self):
        for value in (100, 101):
            with self.subTest(overlap_tokens=value):
                with self.assertRaises(ChunkingError):
                    ChunkingSettings(target_tokens=100, overlap_tokens=value)

    def test_non_positive_chars_per_token_is_rejected(self):
        with self.assertRaises(ChunkingError):
            ChunkingSettings(chars_per_token=0)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class ApproxTokenCountTests(unittest.TestCase):
    """The documented character-based token approximation."""

    def test_empty_text_has_no_tokens(self):
        self.assertEqual(approx_token_count(""), 0)

    def test_rounds_up(self):
        self.assertEqual(approx_token_count("abcd"), 1)
        self.assertEqual(approx_token_count("abcde"), 2)

    def test_uses_the_supplied_ratio(self):
        self.assertEqual(approx_token_count("abcdefgh", chars_per_token=8), 1)

    def test_invalid_ratio_is_rejected(self):
        with self.assertRaises(ChunkingError):
            approx_token_count("abc", chars_per_token=0)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class DocumentMetadataTests(unittest.TestCase):
    """What the caller must supply, and what stays absent."""

    def test_document_id_is_required(self):
        for value in ("", "   "):
            with self.subTest(document_id=repr(value)):
                with self.assertRaises(ChunkingError):
                    DocumentMetadata(document_id=value)

    def test_unknown_fields_stay_absent(self):
        metadata = DocumentMetadata(document_id="doc-1")
        self.assertIsNone(metadata.version_id)
        self.assertIsNone(metadata.document_type)
        self.assertIsNone(metadata.scheme)
        self.assertIsNone(metadata.subject_name)
        self.assertIsNone(metadata.subject_code)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class ChunkSizeTests(unittest.TestCase):
    """CHK-02: no chunk exceeds the configured maximum."""

    def test_no_chunk_exceeds_the_target(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        self.assertGreater(result.chunk_count, 1)
        for chunk in result.chunks:
            self.assertLessEqual(len(chunk.text), 120)

    def test_larger_target_produces_fewer_chunks(self):
        page = _header_page(1, _paras(8))
        small = chunk_document(_result([page]), _meta(), _settings(60, 10))
        large = chunk_document(_result([page]), _meta(), _settings(600, 10))
        self.assertLess(large.chunk_count, small.chunk_count)

    def test_default_settings_are_applied_when_none_given(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta())
        self.assertEqual(result.settings, ChunkingSettings())
        for chunk in result.chunks:
            self.assertLessEqual(len(chunk.text), result.settings.target_chars)

    def test_a_single_unbreakable_paragraph_is_hard_split_and_recorded(self):
        # One "word" far longer than the limit, so only a hard split can work.
        page = _text_page(1, "x" * 500)
        result = chunk_document(_result([page]), _meta(), _settings(100, 20))
        self.assertGreater(result.chunk_count, 1)
        for chunk in result.chunks:
            self.assertLessEqual(len(chunk.text), 100)
            self.assertTrue(chunk.metadata.hard_split, "CHK-03 must record the hard split")

    def test_ordinary_splitting_is_not_reported_as_a_hard_split(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        for chunk in result.chunks:
            self.assertFalse(chunk.metadata.hard_split)

    def test_recorded_character_count_matches_the_text(self):
        page = _header_page(1, _paras(4))
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        for chunk in result.chunks:
            self.assertEqual(chunk.metadata.char_count, len(chunk.text))
            self.assertEqual(
                chunk.metadata.approx_token_count,
                approx_token_count(chunk.text, result.settings.chars_per_token),
            )


@unittest.skipIf(chunking is None, _SKIP_REASON)
class OverlapTests(unittest.TestCase):
    """Overlap is present, bounded, and never crosses a section boundary."""

    def _result_with_overlap(self):
        page = _header_page(1, _paras(8))
        return chunk_document(_result([page]), _meta(), _settings(120, 30))

    def test_consecutive_chunks_in_a_section_share_text(self):
        result = self._result_with_overlap()
        pairs = 0
        for group in _chunks_by_section(result):
            for first, second in zip(group, group[1:]):
                shared = _shared_suffix_prefix_length(first.text, second.text)
                self.assertGreater(shared, 0, "overlap was requested but not applied")
                self.assertLessEqual(shared, result.settings.overlap_chars)
                pairs += 1
        self.assertGreaterEqual(pairs, 1)

    def test_overlap_does_not_push_a_chunk_over_the_limit(self):
        result = self._result_with_overlap()
        self.assertGreater(result.chunk_count, 1)
        for chunk in result.chunks:
            self.assertLessEqual(len(chunk.text), result.settings.target_chars)

    def test_zero_overlap_produces_no_repeated_text(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta(), _settings(120, 0))
        for group in _chunks_by_section(result):
            for first, second in zip(group, group[1:]):
                self.assertEqual(_shared_suffix_prefix_length(first.text, second.text), 0)

    def test_overlap_never_repeats_text_across_a_section_boundary(self):
        # Two subjects, each small enough to need more than one chunk.
        page = _header_page(1, _paras(4), code="BCS101")
        other = _header_page(
            2,
            ["MODULE-1"] + _paras(4),
            code="BCS202",
        )
        result = chunk_document(_result([page, other]), _meta(), _settings(120, 30))
        for group in _chunks_by_section(result):
            codes = {chunk.metadata.subject_code for chunk in group}
            self.assertEqual(len(codes), 1, "a section must hold one subject only")
        for first, second in zip(result.chunks, result.chunks[1:]):
            if first.metadata.subject_code != second.metadata.subject_code:
                self.assertEqual(_shared_suffix_prefix_length(first.text, second.text), 0)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class OverlapProvenanceTests(unittest.TestCase):
    """FR-ING-04 / CHK-04: the repeated overlap text keeps its own pages.

    The overlap excerpt is a trailing piece of the previous chunk. When a
    chunk ends with several paragraphs the excerpt can begin inside an earlier
    paragraph, so attributing it to only the last paragraph would let a chunk
    contain text whose page is missing from its ``page_numbers``.
    """

    def _two_page_overlap(self):
        # Page 1 holds a two-line paragraph, page 2 a short one, so both fit in
        # the first chunk. Page 3 forces a second chunk. The overlap budget is
        # large enough that the excerpt starts inside page 1's paragraph.
        pages = [
            _text_page(1, "AAAA\nBBBB"),
            _text_page(2, "CC"),
            _text_page(3, "D"),
        ]
        return chunk_document(_result(pages), _meta(), _settings(13, 12))

    def test_overlap_that_starts_on_an_earlier_page_cites_that_page(self):
        result = self._two_page_overlap()
        self.assertEqual(result.chunk_count, 2)
        first, second = result.chunks
        shared = _shared_suffix_prefix_length(first.text, second.text)
        self.assertGreater(shared, 0, "the fixture must actually produce an overlap")

        # The repeated excerpt is "BBBB" (page 1) plus "CC" (page 2).
        self.assertIn("BBBB", second.text)
        self.assertIn("CC", second.text)
        self.assertIn(
            1,
            second.metadata.page_numbers,
            "page 1 supplied text repeated into this chunk, so it must be cited",
        )
        self.assertEqual(second.metadata.page_numbers, (1, 2, 3))
        self.assertEqual(second.metadata.page_start, 1)
        self.assertEqual(second.metadata.page_end, 3)

    def test_overlap_keeps_every_page_of_text_the_chunk_really_contains(self):
        result = self._two_page_overlap()
        for chunk in result.chunks:
            with self.subTest(chunk=chunk.metadata.chunk_index):
                # No page number cited may exceed the chunk's own span, and the
                # span must be the whole range it covers.
                self.assertEqual(chunk.metadata.page_start, min(chunk.metadata.page_numbers))
                self.assertEqual(chunk.metadata.page_end, max(chunk.metadata.page_numbers))

    def test_overlap_still_respects_the_size_limit(self):
        result = self._two_page_overlap()
        for chunk in result.chunks:
            self.assertLessEqual(len(chunk.text), result.settings.target_chars)

    def test_overlap_does_not_leak_a_page_it_did_not_repeat(self):
        # Three one-line paragraphs on three pages. The first chunk holds pages
        # 1 and 2; its excerpt is only the page 2 paragraph, so page 1 must not
        # leak into the second chunk.
        pages = [_text_page(1, "AAAA"), _text_page(2, "BBBB"), _text_page(3, "CCCC")]
        result = chunk_document(_result(pages), _meta(), _settings(12, 8))
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(result.chunks[0].metadata.page_numbers, (1, 2))
        self.assertEqual(result.chunks[1].metadata.page_numbers, (2, 3))


@unittest.skipIf(chunking is None, _SKIP_REASON)
class DeterministicIdTests(unittest.TestCase):
    """FR-ING-07 / FR-ING-10 / AC-14: rerunning the same input is a no-op."""

    def test_same_input_and_settings_produce_identical_ids(self):
        page = _header_page(1, _paras(8))
        first = chunk_document(_result([page]), _meta(), _settings(120, 30))
        second = chunk_document(_result([page]), _meta(), _settings(120, 30))
        self.assertEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )
        self.assertEqual(
            [chunk.text for chunk in first.chunks],
            [chunk.text for chunk in second.chunks],
        )

    def test_ids_are_unique_within_a_result(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        ids = [chunk.chunk_id for chunk in result.chunks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ids_carry_the_document_id(self):
        page = _header_page(1, _paras(4))
        result = chunk_document(_result([page]), _meta("doc-xyz"), _settings(120, 30))
        for chunk in result.chunks:
            self.assertTrue(chunk.chunk_id.startswith("doc-xyz:"))

    def test_different_settings_change_the_ids(self):
        page = _header_page(1, _paras(8))
        first = chunk_document(_result([page]), _meta(), _settings(120, 30))
        second = chunk_document(_result([page]), _meta(), _settings(150, 30))
        self.assertNotEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )

    def test_different_document_ids_never_collide(self):
        page = _header_page(1, _paras(4))
        first = chunk_document(_result([page]), _meta("doc-a"), _settings(120, 30))
        second = chunk_document(_result([page]), _meta("doc-b"), _settings(120, 30))
        first_ids = {chunk.chunk_id for chunk in first.chunks}
        second_ids = {chunk.chunk_id for chunk in second.chunks}
        self.assertTrue(first_ids)
        self.assertEqual(first_ids & second_ids, set())
        self.assertNotEqual(first.chunks[0].chunk_id, second.chunks[0].chunk_id)

    def test_different_version_changes_the_ids(self):
        page = _header_page(1, _paras(4))
        first = chunk_document(_result([page]), _meta(version_id="v1"), _settings(120, 30))
        second = chunk_document(_result([page]), _meta(version_id="v2"), _settings(120, 30))
        self.assertNotEqual(first.chunks[0].chunk_id, second.chunks[0].chunk_id)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class PageProvenanceTests(unittest.TestCase):
    """FR-ING-04 / CHK-04 / AC-02: every chunk traces back to real PDF pages."""

    def test_single_page_chunk_reports_one_page(self):
        page = _header_page(3, _paras(2))
        result = chunk_document(_result([page]), _meta(), _settings(40, 10))
        self.assertGreater(result.chunk_count, 1)
        for chunk in result.chunks:
            self.assertFalse(chunk.metadata.spans_pages)
            self.assertEqual(chunk.metadata.page_number, 3)
            self.assertEqual(chunk.metadata.page_start, 3)
            self.assertEqual(chunk.metadata.page_end, 3)
            self.assertEqual(chunk.metadata.page_numbers, (3,))

    def test_multi_page_chunk_reports_a_range(self):
        first = _header_page(1, ["One two three four five six seven eight nine ten."])
        second = _text_page(2, "Eleven twelve thirteen fourteen fifteen sixteen seventeen.")
        result = chunk_document(_result([first, second]), _meta(), _settings(200, 30))
        self.assertEqual(result.chunk_count, 1)
        chunk = result.chunks[0]
        self.assertTrue(chunk.metadata.spans_pages)
        self.assertIsNone(chunk.metadata.page_number)
        self.assertEqual(chunk.metadata.page_start, 1)
        self.assertEqual(chunk.metadata.page_end, 2)
        self.assertEqual(chunk.metadata.page_numbers, (1, 2))
        self.assertIn("Eleven twelve", chunk.text)

    def test_no_chunk_has_null_provenance(self):
        pages = [
            _header_page(1, _paras(4)),
            ExtractedPage(page_number=2, outcome=PAGE_BLANK),
            _header_page(3, _paras(4)),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(120, 30))
        self.assertGreater(result.chunk_count, 0)
        for chunk in result.chunks:
            self.assertTrue(chunk.metadata.page_numbers)
            self.assertGreaterEqual(chunk.metadata.page_start, 1)
            self.assertLessEqual(chunk.metadata.page_end, 3)
            self.assertLessEqual(chunk.metadata.page_start, chunk.metadata.page_end)

    def test_original_page_numbers_survive_a_skipped_page(self):
        pages = [
            _header_page(1, ["One two three four five six seven eight."]),
            ExtractedPage(page_number=2, outcome=PAGE_IMAGE_ONLY, image_count=1),
            _text_page(3, "Nine ten eleven twelve thirteen fourteen."),
        ]
        result = chunk_document(_result([page for page in pages]), _meta(), _settings(200, 30))
        self.assertEqual(result.skipped_pages, (2,))
        for chunk in result.chunks:
            self.assertNotIn(2, chunk.metadata.page_numbers)
        self.assertEqual(result.cited_pages, (1, 3))

    def test_skipped_pages_are_reported_and_never_cited(self):
        pages = [
            _text_page(1, "Only page one text here."),
            ExtractedPage(page_number=2, outcome=PAGE_IMAGE_ONLY, image_count=1),
            ExtractedPage(page_number=3, outcome=PAGE_BLANK),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(200, 30))
        self.assertEqual(result.skipped_pages, (2, 3))
        self.assertEqual(result.cited_pages, (1,))

    def test_chunk_index_is_sequential(self):
        page = _header_page(1, _paras(8))
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        self.assertEqual(
            [chunk.metadata.chunk_index for chunk in result.chunks],
            list(range(result.chunk_count)),
        )

    def test_section_chunk_counts_account_for_every_chunk(self):
        pages = [
            _header_page(1, ["MODULE-1"] + _paras(3)),
            _header_page(2, _paras(3), code="BCS202"),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(120, 30))
        self.assertEqual(
            sum(section.chunk_count for section in result.sections),
            result.chunk_count,
        )


@unittest.skipIf(chunking is None, _SKIP_REASON)
class SubjectAndModuleMetadataTests(unittest.TestCase):
    """FR-META-01 / META-01: per-chunk subject and module metadata."""

    def test_detected_subject_code_propagates_to_its_chunks(self):
        page = _header_page(1, _paras(4), subject_name="DEMO SUBJECT", code="BCS101")
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        self.assertGreater(result.chunk_count, 0)
        for chunk in result.chunks:
            self.assertEqual(chunk.metadata.subject_code, "BCS101")
            self.assertEqual(chunk.metadata.subject_name, "DEMO SUBJECT")
            self.assertEqual(chunk.metadata.subject_boundary, BOUNDARY_DETECTED)

    def test_detected_module_propagates_and_changes_at_a_heading(self):
        paragraphs = _paras(2)
        page = _header_page(
            1,
            ["MODULE-1", paragraphs[0], "MODULE-2", paragraphs[1]],
            subject_name="DEMO SUBJECT",
            code="BCS101",
        )
        result = chunk_document(_result([page]), _meta(), _settings(120, 30))
        modules = [chunk.metadata.module_label for chunk in result.chunks]
        self.assertIn("Module-1", modules)
        self.assertIn("Module-2", modules)
        for chunk in result.chunks:
            if chunk.metadata.module_label:
                self.assertEqual(chunk.metadata.module_boundary, BOUNDARY_DETECTED)

    def test_the_header_section_before_the_first_module_has_no_module(self):
        page = _header_page(
            1,
            ["MODULE-1", PARA],
            subject_name="DEMO SUBJECT",
            code="BCS101",
        )
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        header = result.sections[0]
        self.assertIsNone(header.module_number)
        self.assertEqual(header.module_boundary, BOUNDARY_UNKNOWN)
        self.assertEqual(header.subject_code, "BCS101")

    def test_module_numbering_resets_at_a_new_subject(self):
        page = _text_page(
            1,
            "\n".join(
                [
                    "Course Code",
                    "BCS101",
                    "",
                    "MODULE-1",
                    "",
                    PARA,
                    "",
                    "MODULE-2",
                    "",
                    PARA,
                    "",
                    "Course Code",
                    "BCS202",
                    "",
                    "MODULE-1",
                    "",
                    PARA,
                ]
            ),
        )
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        after_second_subject = [
            section for section in result.sections if section.subject_code == "BCS202"
        ]
        self.assertTrue(after_second_subject)
        self.assertIsNone(
            after_second_subject[0].module_number,
            "the module number must not carry over from the previous subject",
        )
        self.assertEqual(after_second_subject[1].module_number, 1)

    def test_supplied_subject_is_used_only_when_the_document_does_not_state_one(self):
        page = _text_page(1, PARA)
        metadata = _meta(subject_name="Supplied Subject", subject_code="SUP101")
        result = chunk_document(_result([page]), metadata, _settings(400, 30))
        self.assertEqual(result.chunk_count, 1)
        chunk = result.chunks[0]
        self.assertEqual(chunk.metadata.subject_name, "Supplied Subject")
        self.assertEqual(chunk.metadata.subject_code, "SUP101")
        self.assertEqual(chunk.metadata.subject_boundary, BOUNDARY_SUPPLIED)

    def test_a_detected_subject_wins_over_a_supplied_one(self):
        page = _header_page(1, _paras(1), subject_name="DETECTED SUBJECT", code="BCS101")
        metadata = _meta(subject_name="Supplied Subject", subject_code="SUP101")
        result = chunk_document(_result([page]), metadata, _settings(400, 30))
        chunk = result.chunks[0]
        self.assertEqual(chunk.metadata.subject_code, "BCS101")
        self.assertEqual(chunk.metadata.subject_name, "DETECTED SUBJECT")
        self.assertEqual(chunk.metadata.subject_boundary, BOUNDARY_DETECTED)

    def test_document_level_fields_propagate_to_every_chunk(self):
        page = _header_page(1, _paras(4))
        metadata = _meta()
        result = chunk_document(_result([page]), metadata, _settings(120, 30))
        for chunk in result.chunks:
            self.assertEqual(chunk.metadata.document_id, "doc-1")
            self.assertEqual(chunk.metadata.version_id, "v1")
            self.assertEqual(chunk.metadata.filename, "synthetic.pdf")
            self.assertEqual(chunk.metadata.document_type, "syllabus")
            self.assertEqual(chunk.metadata.scheme, "2022")
            self.assertEqual(chunk.metadata.branch, "CSE")
            self.assertEqual(chunk.metadata.semester, "5")

    def test_module_label_is_absent_when_no_module_is_detected(self):
        page = _text_page(1, PARA)
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        chunk = result.chunks[0]
        self.assertIsNone(chunk.metadata.module_number)
        self.assertIsNone(chunk.metadata.module_label)
        self.assertEqual(chunk.metadata.module_boundary, BOUNDARY_UNKNOWN)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class NonModuleSectionTests(unittest.TestCase):
    """FR-META-02 / META-02: material after the last module is not folded into it.

    The pilot document places course outcomes, assessment details, and learning
    resources after Module 5. They belong to the subject but to no module, so
    they must get a section whose module stays unknown rather than inheriting
    Module 5 from the section above them.
    """

    def _page_with_trailing_material(self, heading: str) -> ExtractedPage:
        return _text_page(
            1,
            "\n".join(
                [
                    "DEMO SUBJECT",
                    "Semester",
                    "V",
                    "Course Code",
                    "BCS101",
                    "",
                    "MODULE-5",
                    "",
                    "Module five body text.",
                    "",
                    heading,
                    "",
                    "Trailing material body text.",
                ]
            ),
        )

    def _result_for(self, heading: str):
        return chunk_document(
            _result([self._page_with_trailing_material(heading)]),
            _meta(),
            _settings(400, 30),
        )

    def test_module_five_content_is_still_attributed_to_module_five(self):
        result = self._result_for("Suggested Learning Resources:")
        module_five = [s for s in result.sections if s.module_number == 5]
        self.assertEqual(len(module_five), 1)
        for chunk in result.chunks:
            if "Module five body text." in chunk.text:
                self.assertEqual(chunk.metadata.module_number, 5)
                self.assertEqual(chunk.metadata.module_boundary, BOUNDARY_DETECTED)

    def test_trailing_material_is_not_attributed_to_a_module(self):
        result = self._result_for("Suggested Learning Resources:")
        for chunk in result.chunks:
            if "Trailing material body text." in chunk.text:
                self.assertIsNone(
                    chunk.metadata.module_number,
                    "non-module material must not inherit the module above it",
                )
                self.assertEqual(chunk.metadata.module_boundary, BOUNDARY_UNKNOWN)
                self.assertEqual(chunk.metadata.subject_code, "BCS101")

    def test_each_known_non_module_heading_opens_an_unknown_module_section(self):
        headings = [
            "Course outcomes (Course Skill Set):",
            "Course outcome (Course Skill Set)",
            "Assessment Details (both CIE and SEE)",
            "Suggested Learning Resources:",
            "Web links and Video Lectures (e-Resources):",
        ]
        for heading in headings:
            with self.subTest(heading=heading):
                last = self._result_for(heading).sections[-1]
                self.assertEqual(last.first_line, heading)
                self.assertIsNone(last.module_number)
                self.assertEqual(last.module_boundary, BOUNDARY_UNKNOWN)

    def test_a_heading_hidden_by_a_trailing_qualifier_is_still_recognised(self):
        # The 2025 scheme prints some headings with a trailing parenthetical
        # and a second colon. Those headings used to slip past the fixed
        # heading set, so their text stayed attributed to the module above
        # them. The qualifier is reduced away before the set is consulted.
        headings = [
            "Suggested Learning Resources: (Text Book/ Reference Book/ Manuals):",
            "Assessment Details for CIE (both CIE and SEE)",
            "Web links and Video Lectures (e-Resources):",
        ]
        for heading in headings:
            with self.subTest(heading=heading):
                last = self._result_for(heading).sections[-1]
                self.assertEqual(last.first_line, heading)
                self.assertIsNone(last.module_number)
                self.assertEqual(last.module_boundary, BOUNDARY_UNKNOWN)
                self.assertEqual(last.subject_code, "BCS101")

    def test_the_trailing_component_headings_are_recognised(self):
        # Both wordings of the practical/tutorial component lead-in appear in
        # the pilot documents; the assessment heading is spelled differently in
        # the 2025 scheme. None of them was in the fixed heading set.
        headings = [
            "PRACTICAL COMPONENT OF IPCC",
            "PRACTICAL COMPONENT OF IPCC(May cover all / major modules)",
            "TUTORIAL COMPONENT OF PCC",
            "Assessment Structure:",
        ]
        for heading in headings:
            with self.subTest(heading=heading):
                last = self._result_for(heading).sections[-1]
                self.assertEqual(last.first_line, heading)
                self.assertIsNone(last.module_number)
                self.assertEqual(last.module_boundary, BOUNDARY_UNKNOWN)

    def test_an_unrecognised_heading_keeps_the_module_above_it(self):
        # Only the fixed heading set is understood; anything else stays with the
        # module above it, which is the stated limitation of the detector.
        result = self._result_for("Something Else Entirely")
        self.assertEqual(len(result.sections), 2)
        last = result.sections[-1]
        self.assertEqual(last.module_number, 5)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class PageFurnitureTests(unittest.TestCase):
    """Repeated page furniture is removed conservatively and reported.

    A line is only removed when it sits in a furniture position on at least
    three pages, and every removal is recorded on ``ChunkingResult.furniture``
    so the run reports what it dropped instead of editing the text silently.
    """

    def _three_furniture_pages(self):
        return [
            _furniture_page(1, "Alpha body one."),
            _furniture_page(2, "Beta body two."),
            _furniture_page(3, "Gamma body three."),
        ]

    def _result(self):
        return chunk_document(
            _result(self._three_furniture_pages()), _meta(), _settings(400, 30)
        )

    def test_repeated_furniture_is_recorded_for_audit(self):
        removed = {
            (removal.kind, removal.text): removal.page_numbers
            for removal in self._result().furniture
        }
        self.assertEqual(
            removed,
            {
                ("header", "Annexure-II 1"): (1, 2, 3),
                ("page_counter", "1"): (1, 2, 3),
                ("footer", "12082024"): (1, 2, 3),
            },
        )

    def test_removed_furniture_is_absent_from_the_chunks(self):
        for chunk in self._result().chunks:
            self.assertNotIn("Annexure-II 1", chunk.text)
            self.assertNotIn("12082024", chunk.text)

    def test_real_body_text_is_preserved(self):
        joined = "\n".join(chunk.text for chunk in self._result().chunks)
        for body in ("Alpha body one.", "Beta body two.", "Gamma body three."):
            self.assertIn(body, joined)

    def test_a_line_seen_on_too_few_pages_is_kept(self):
        pages = [
            _text_page(1, "MKV-TEMPLATE for IPCC (26.04.2022)\nAlpha body."),
            _text_page(2, "MKV-TEMPLATE for IPCC (26.04.2022)\nBeta body."),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertEqual(result.furniture, ())
        for chunk in result.chunks:
            self.assertIn("MKV-TEMPLATE for IPCC (26.04.2022)", chunk.text)

    def test_a_repeated_word_inside_the_body_is_never_removed(self):
        pages = [
            _text_page(number, f"Body line {number}\nThis template is used here.\nTail {number}")
            for number in (1, 2, 3)
        ]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertEqual(result.furniture, ())
        for chunk in result.chunks:
            self.assertIn("This template is used here.", chunk.text)

    def test_a_glued_template_label_is_removed_when_repeated(self):
        # The 2025 scheme glues the version stamp onto the template label with
        # no space ("... template30032026 1"), which used to stop the label from
        # being recognised, so the header stayed in every chunk.
        label = "VTU/PCC-PEC-OEC (3 Credits) template30032026 1"
        pages = [_text_page(number, f"{label}\nBody {number}.") for number in (1, 2, 3)]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        removed = {(removal.kind, removal.text) for removal in result.furniture}
        self.assertIn(("header", label), removed)
        for chunk in result.chunks:
            self.assertNotIn(label, chunk.text)

    def test_a_dotted_or_prefixed_date_stamp_is_removed_when_repeated(self):
        # The 2022 scheme's 3rd-semester footer is a dotted date on some pages
        # and a stamp with stray punctuation in front on others; both used to
        # survive because the footer rule required a bare run of digits.
        dotted = "15.09.2023"
        prefixed = "@# 16032024"
        pages = [_text_page(number, f"Body {number}.\n{dotted}") for number in (1, 2, 3)]
        pages += [_text_page(number, f"Body {number}.\n{prefixed}") for number in (4, 5, 6)]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        removed = {(removal.kind, removal.text) for removal in result.furniture}
        self.assertIn(("footer", dotted), removed)
        self.assertIn(("footer", prefixed), removed)

    def test_a_short_number_at_the_foot_of_a_page_is_never_a_footer(self):
        # A content number that happens to sit at the foot of the page - a
        # module number, a year - must survive: the footer rule needs at least
        # six digits, so a bare "50" or "2022" is not a stamp.
        for number in ("50", "2022"):
            with self.subTest(number=number):
                pages = [
                    _text_page(index, f"Body {index}.\n{number}") for index in (1, 2, 3)
                ]
                result = chunk_document(_result(pages), _meta(), _settings(400, 30))
                self.assertEqual(result.furniture, ())
                joined = "\n".join(chunk.text for chunk in result.chunks)
                self.assertIn(number, joined)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class MissingOrAmbiguousHeadingTests(unittest.TestCase):
    """FR-META-02 / META-02: absent or unclear structure is never guessed."""

    def test_a_document_with_no_headings_yields_unknown_structure(self):
        page = _text_page(1, PARA)
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.chunk_count, 1)
        self.assertEqual(result.chunk_count, len(result.sections))
        section = result.sections[0]
        self.assertIsNone(section.subject_name)
        self.assertIsNone(section.subject_code)
        self.assertIsNone(section.module_number)
        self.assertEqual(section.subject_boundary, BOUNDARY_UNKNOWN)
        self.assertEqual(section.module_boundary, BOUNDARY_UNKNOWN)
        self.assertEqual(result.ambiguous_heading_lines, ())

    def test_a_module_heading_with_an_hours_annotation_is_a_boundary(self):
        page = _text_page(1, "\n".join(["MODULE-1 10 hours", "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.ambiguous_heading_lines, ())
        self.assertEqual(result.chunks[0].metadata.module_number, 1)

    def test_a_bare_module_heading_is_a_boundary(self):
        page = _text_page(1, "\n".join(["Module-2", "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.ambiguous_heading_lines, ())
        self.assertEqual(result.chunks[0].metadata.module_number, 2)

    def test_an_inline_mention_of_a_module_is_not_treated_as_a_boundary(self):
        ambiguous_line = "Module-3 Assessment covers three topics."
        page = _text_page(1, "\n".join(["MODULE-1", "", ambiguous_line, "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.ambiguous_heading_lines, (ambiguous_line,))
        for chunk in result.chunks:
            self.assertEqual(chunk.metadata.module_number, 1)
        self.assertEqual([section.module_number for section in result.sections].count(3), 0)

    def test_a_course_code_label_without_a_code_is_not_a_subject_boundary(self):
        page = _text_page(1, "\n".join(["Course Code", "not-a-code", "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.sections[0].subject_code, None)
        self.assertEqual(result.sections[0].subject_boundary, BOUNDARY_UNKNOWN)
        self.assertEqual(result.ambiguous_heading_lines, ())

    def test_a_semester_label_with_nothing_above_it_yields_no_subject_name(self):
        page = _text_page(1, "\n".join(["Semester", "V", "Course Code", "BCS101", "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        # The header lines stay inside the subject, so there is no orphan section.
        self.assertEqual(len(result.sections), 1)
        self.assertEqual(result.sections[0].first_line, "Semester")
        chunk = result.chunks[0]
        self.assertEqual(chunk.metadata.subject_code, "BCS101")
        self.assertIsNone(chunk.metadata.subject_name)

    def test_a_page_counter_above_the_semester_label_is_not_a_subject_name(self):
        page = _text_page(
            1,
            "\n".join(["7", "Semester", "V", "Course Code", "BCS101", "", PARA]),
        )
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        subject_sections = [
            section for section in result.sections if section.subject_code == "BCS101"
        ]
        self.assertEqual(len(subject_sections), 1)
        self.assertIsNone(
            subject_sections[0].subject_name,
            "a bare page counter must not be reported as a subject name",
        )
        for chunk in result.chunks:
            self.assertNotEqual(chunk.metadata.subject_name, "7")


@unittest.skipIf(chunking is None, _SKIP_REASON)
class LayoutGeneralisationTests(unittest.TestCase):
    """The detector handles both observed VTU header layouts, not just one.

    The 2022 scheme prints the semester above the code and a letter-only code
    such as ``BCS501``. The 2025 scheme prints the semester below the code and
    a code carrying a leading programme digit such as ``1BMATCS301``. Both use
    the same ``Course Code`` label and the same title-above-label structure, so
    both must be detected the same way rather than yielding an unknown subject.
    """

    def test_a_course_code_with_a_programme_prefix_is_a_subject_boundary(self):
        result = chunk_document(_result([_header_page_2025(1)]), _meta(), _settings(400, 30))
        section = result.sections[0]
        self.assertEqual(section.subject_code, "1BMATCS301")
        self.assertEqual(section.subject_boundary, BOUNDARY_DETECTED)
        self.assertEqual(result.chunks[0].metadata.subject_code, "1BMATCS301")

    def test_the_title_above_course_code_is_the_subject_name(self):
        result = chunk_document(_result([_header_page_2025(1)]), _meta(), _settings(400, 30))
        self.assertEqual(result.sections[0].subject_name, "DEMO SUBJECT 2025")
        self.assertEqual(result.chunks[0].metadata.subject_name, "DEMO SUBJECT 2025")

    def test_the_title_does_not_leak_into_the_section_before_the_subject(self):
        page = _text_page(
            1,
            "\n".join(
                [
                    "Lead-in material.",
                    "DEMO SUBJECT 2025",
                    "Course Code",
                    "1BMATCS301",
                    "Scheme",
                    "2025",
                    "",
                    PARA,
                ]
            ),
        )
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(len(result.sections), 2)
        lead_in, subject = result.sections
        self.assertEqual(lead_in.first_line, "Lead-in material.")
        self.assertIsNone(lead_in.subject_code)
        self.assertEqual(subject.first_line, "DEMO SUBJECT 2025")
        self.assertEqual(subject.subject_code, "1BMATCS301")

    def test_a_module_heading_with_a_delimited_title_is_a_boundary(self):
        for line, number in (("Module-1: Modular Arithmetic", 1), ("Module-2 - Statistics", 2)):
            with self.subTest(line=line):
                page = _header_page_2025(1, [line, "", PARA])
                result = chunk_document(_result([page]), _meta(), _settings(400, 30))
                self.assertEqual(result.ambiguous_heading_lines, ())
                self.assertEqual([s.module_number for s in result.sections].count(number), 1)
                for chunk in result.chunks:
                    if PARA in chunk.text:
                        self.assertEqual(chunk.metadata.module_number, number)
                        self.assertEqual(chunk.metadata.module_boundary, BOUNDARY_DETECTED)

    def test_a_module_heading_with_a_bare_trailing_phrase_stays_ambiguous(self):
        # No delimiter, so the trailing words are prose and not a title.
        line = "Module-3 Assessment"
        page = _text_page(1, "\n".join(["MODULE-1", "", PARA, "", line, "", PARA]))
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        self.assertEqual(result.ambiguous_heading_lines, (line,))
        self.assertEqual([s.module_number for s in result.sections].count(3), 0)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class EmptyInputTests(unittest.TestCase):
    """Empty input is a fact about the document, not a crash."""

    def test_a_document_with_no_pages_returns_an_empty_result(self):
        result = chunk_document(
            ExtractionResult(source_path="empty.pdf", page_count=0, pages=()),
            _meta(),
        )
        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunk_count, 0)
        self.assertEqual(result.chunks, ())
        self.assertEqual(result.sections, ())
        self.assertEqual(result.cited_pages, ())
        self.assertEqual(result.skipped_pages, ())

    def test_pages_with_no_text_return_an_empty_result_and_report_the_pages(self):
        pages = [
            ExtractedPage(page_number=1, outcome=PAGE_BLANK),
            ExtractedPage(page_number=2, outcome=PAGE_IMAGE_ONLY, image_count=1),
        ]
        result = chunk_document(_result(pages), _meta())
        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunk_count, 0)
        self.assertEqual(result.skipped_pages, (1, 2))
        self.assertEqual(result.document_id, "doc-1")

    def test_a_text_page_of_only_whitespace_produces_nothing(self):
        page = _text_page(1, "   \n\n\t  \n   \n")
        result = chunk_document(_result([page]), _meta())
        self.assertTrue(result.is_empty)
        self.assertEqual(result.chunk_count, 0)
        self.assertEqual(result.skipped_pages, ())

    def test_an_empty_page_between_two_text_pages_is_skipped(self):
        pages = [
            _text_page(1, PARA),
            ExtractedPage(page_number=2, outcome=PAGE_BLANK),
            _text_page(3, PARA),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertFalse(result.is_empty)
        self.assertEqual(result.skipped_pages, (2,))
        self.assertEqual(result.cited_pages, (1, 3))


@unittest.skipIf(chunking is None, _SKIP_REASON)
class PageCoverageTests(unittest.TestCase):
    """Page coverage is reported from the page list, not inferred from chunks.

    A page whose surviving lines carry no letter at all - a page counter or a
    stamp that the furniture pass kept - yields no citable chunk. The page must
    still be accounted for, and a chunk of four characters of page numbers must
    not be emitted as the smallest item in the corpus.
    """

    def test_a_page_of_only_numbers_is_accounted_for_without_a_chunk(self):
        pages = [_text_page(1, "Real body text."), _text_page(2, "12\n\n34")]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertEqual(result.skipped_pages, ())
        self.assertEqual(result.cited_pages, (1,))
        self.assertEqual(result.pages_without_content, (2,))

    def test_no_chunk_is_content_free(self):
        pages = [_text_page(1, "Real body text."), _text_page(2, "12\n\n34")]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        for chunk in result.chunks:
            self.assertRegex(
                chunk.text,
                r"[^\W\d_]",
                "a chunk with no letter in it is not citable evidence",
            )

    def test_every_text_page_is_cited_or_reported_without_content(self):
        pages = [
            _text_page(1, "Real body text."),
            _text_page(2, "12\n\n34"),
            ExtractedPage(page_number=3, outcome=PAGE_BLANK),
            _text_page(4, "More body text."),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        accounted = (
            set(result.cited_pages)
            | set(result.pages_without_content)
            | set(result.skipped_pages)
        )
        self.assertEqual(accounted, {1, 2, 3, 4})
        self.assertEqual(result.pages_without_content, (2,))

    def test_a_document_of_only_numbers_reports_every_page_as_uncited(self):
        lines = "11\n\n22"
        pages = [_text_page(1, lines), _text_page(2, lines)]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertTrue(result.is_empty)
        self.assertEqual(result.skipped_pages, ())
        self.assertEqual(result.pages_without_content, (1, 2))

    def test_a_page_whose_lines_were_all_furniture_is_reported(self):
        # Every content line on page 3 is repeated furniture, so the page
        # yields no chunk; it must still appear in page coverage rather than
        # disappear from the report.
        label = "Annexure-II 1"
        pages = [
            _text_page(1, f"{label}\n1\nAlpha body one.\n12082024"),
            _text_page(2, f"{label}\n1\nBeta body two.\n12082024"),
            _text_page(3, f"{label}\n1\n12082024"),
        ]
        result = chunk_document(_result(pages), _meta(), _settings(400, 30))
        self.assertIn(3, result.pages_without_content)
        self.assertNotIn(1, result.pages_without_content)
        self.assertNotIn(2, result.pages_without_content)


@unittest.skipIf(chunking is None, _SKIP_REASON)
class DocumentIsolationTests(unittest.TestCase):
    """CHK-05: chunks never contain text from two documents."""

    def test_two_documents_never_share_text_or_ids(self):
        first_marker = "FIRSTDOCMARKER"
        second_marker = "SECONDDOCMARKER"
        first = chunk_document(
            _result([_text_page(1, f"{first_marker} first body text.")]),
            _meta("doc-1"),
            _settings(400, 30),
        )
        second = chunk_document(
            _result([_text_page(1, f"{second_marker} second body text.")]),
            _meta("doc-2"),
            _settings(400, 30),
        )

        for chunk in first.chunks:
            self.assertIn(first_marker, chunk.text)
            self.assertNotIn(second_marker, chunk.text)
            self.assertEqual(chunk.metadata.document_id, "doc-1")
        for chunk in second.chunks:
            self.assertIn(second_marker, chunk.text)
            self.assertNotIn(first_marker, chunk.text)
            self.assertEqual(chunk.metadata.document_id, "doc-2")

        first_ids = {chunk.chunk_id for chunk in first.chunks}
        second_ids = {chunk.chunk_id for chunk in second.chunks}
        self.assertEqual(first_ids & second_ids, set())

    def test_every_chunk_belongs_to_the_supplied_document(self):
        page = _header_page(1, _paras(6))
        result = chunk_document(_result([page]), _meta("only-this-document"), _settings(120, 30))
        self.assertGreater(result.chunk_count, 1)
        for chunk in result.chunks:
            self.assertEqual(chunk.metadata.document_id, "only-this-document")
            self.assertEqual(result.document_id, "only-this-document")


@unittest.skipIf(chunking is None, _SKIP_REASON)
class ChunkRecordTests(unittest.TestCase):
    """FR-META-01: text separate from metadata, and a serialisable record."""

    def _one_chunk(self):
        page = _header_page(1, _paras(1), subject_name="DEMO SUBJECT", code="BCS101")
        result = chunk_document(_result([page]), _meta(), _settings(400, 30))
        return result.chunks[0]

    def test_text_is_stored_separately_from_metadata(self):
        chunk = self._one_chunk()
        self.assertIsInstance(chunk.text, str)
        self.assertFalse(hasattr(chunk.metadata, "text"))
        self.assertEqual(chunk.metadata.char_count, len(chunk.text))

    def test_record_has_the_expected_keys_and_no_faiss_id(self):
        record = self._one_chunk().to_record()
        expected = {
            "chunk_id",
            "chunk_index",
            "document_id",
            "version_id",
            "filename",
            "document_type",
            "scheme",
            "branch",
            "semester",
            "subject_name",
            "subject_code",
            "subject_boundary",
            "module",
            "module_label",
            "module_boundary",
            "page_number",
            "page_start",
            "page_end",
            "page_numbers",
            "char_count",
            "approx_token_count",
            "hard_split",
            "chunk_text",
        }
        self.assertEqual(set(record), expected)
        self.assertNotIn("faiss_id", record)

    def test_record_is_json_serialisable_and_keeps_absent_values_absent(self):
        chunk = self._one_chunk()
        record = chunk.to_record()
        self.assertEqual(record["chunk_text"], chunk.text)
        self.assertEqual(record["module"], None)
        self.assertEqual(record["module_boundary"], BOUNDARY_UNKNOWN)
        self.assertIsInstance(record["page_numbers"], list)
        json.dumps(record)

    def test_absent_metadata_stays_absent_rather_than_defaulted(self):
        page = _text_page(1, PARA)
        metadata = DocumentMetadata(document_id="doc-1")
        result = chunk_document(_result([page]), metadata, _settings(400, 30))
        record = result.chunks[0].to_record()
        for key in ("version_id", "filename", "document_type", "scheme", "branch",
                    "semester", "subject_name", "subject_code", "module", "module_label"):
            with self.subTest(key=key):
                self.assertIsNone(record[key])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
