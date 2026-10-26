"""Tests for :mod:`app.ingestion.canonical`.

Run from the repository root:

    python -m unittest discover -s tests -t . -v

Most tests here are pure: they build a canonical dataset from synthetic records
or a synthetic extraction result, so they do not read a PDF, do not download
anything, and do not depend on the dataset directory existing.

The one test that does use the five real PDFs is skipped when the dataset
directory is absent, so the suite still passes on a machine that does not have
it. That test writes into a temporary directory and never touches the checked-in
canonical dataset or the historical pilot outputs.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app.ingestion import canonical
    from app.ingestion.canonical import (
        CANONICAL_DOCUMENTS,
        CANONICAL_SCHEMA_VERSION,
        REGULATION,
        SYLLABUS,
        build_canonical_dataset,
        canonical_records,
        read_canonical_dataset,
        sha256_of_file,
        write_canonical_dataset,
    )
    from app.ingestion.chunking import ChunkingSettings, DocumentMetadata, chunk_document
    from app.ingestion.pdf_extract import (
        PAGE_TEXT,
        ExtractedPage,
        ExtractionResult,
        _require_pymupdf,
    )

    # Building from the real PDFs needs the PDF toolkit. Asking the extraction
    # module for it is what tells this suite whether those tests can run; the
    # pure tests below need no PDF at all and run either way.
    try:
        _require_pymupdf()
        HAVE_PYMUPDF = True
    except ImportError:
        HAVE_PYMUPDF = False
    _IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # PyMuPDF is not installed in this environment
    canonical = None  # type: ignore[assignment]
    HAVE_PYMUPDF = False
    _IMPORT_ERROR = exc


_SKIP_REASON = f"the ingestion modules cannot be imported, so canonical tests cannot run: {_IMPORT_ERROR}"

#: Meaningless placeholder text. No VTU syllabus wording is invented.
PARA = "Alpha beta gamma delta."


def _text_page(page_number: int, text: str) -> ExtractedPage:
    return ExtractedPage(page_number=page_number, outcome=PAGE_TEXT, text=text)


def _syllabus_page(page_number: int, code: str, paragraphs) -> ExtractedPage:
    """A page shaped like a VTU syllabus subject page."""
    lines = ["SYNTHETIC SUBJECT", "Semester", "V", "Course Code", code]
    for paragraph in paragraphs:
        lines.extend(["", paragraph])
    return _text_page(page_number, "\n".join(lines))


def _extraction(pages, source_path: str = "synthetic.pdf") -> ExtractionResult:
    return ExtractionResult(source_path=source_path, page_count=len(pages), pages=tuple(pages))


def _synthetic_extraction() -> ExtractionResult:
    """A two-page synthetic document that the chunker turns into real chunks."""
    return _extraction(
        [
            _syllabus_page(1, "BCS101", [f"[{index}] {PARA}" for index in range(3)]),
            _syllabus_page(2, "BCS102", [f"[{index}] {PARA}" for index in range(3)]),
        ]
    )


def _record(chunk_id: str, text: str, **overrides) -> dict:
    """A chunk record with the same keys as ``Chunk.to_record()``."""
    record = {
        "chunk_id": chunk_id,
        "chunk_index": 0,
        "document_id": "doc-a",
        "version_id": "va",
        "filename": "a.pdf",
        "document_type": SYLLABUS,
        "scheme": "2022",
        "branch": None,
        "semester": "5",
        "subject_name": "SYNTHETIC SUBJECT",
        "subject_code": "BCS101",
        "subject_boundary": "detected",
        "module": 1,
        "module_label": "Module 1",
        "module_boundary": "detected",
        "page_number": 1,
        "page_start": 1,
        "page_end": 1,
        "page_numbers": [1],
        "char_count": len(text),
        "approx_token_count": len(text) // 4,
        "hard_split": False,
        "chunk_text": text,
    }
    record.update(overrides)
    return record


def _summary(document_id: str, chunk_count: int, **overrides) -> dict:
    summary = {
        "key": document_id,
        "document_id": document_id,
        "version_id": "v1",
        "filename": "a.pdf",
        "source_relative_path": "Syllabus/a.pdf",
        "document_type": SYLLABUS,
        "scheme": "2022",
        "semester": "5",
        "branch": None,
        "page_count": 2,
        "text_pages": 2,
        "non_text_pages": 0,
        "chunk_count": chunk_count,
    }
    summary.update(overrides)
    return summary


def _write_fixture(directory: Path, records=None, summaries=None) -> dict:
    records = records if records is not None else [
        _record("chunk-1", "database normalization"),
        _record("chunk-2", "software engineering", chunk_index=1),
    ]
    summaries = summaries if summaries is not None else [_summary("doc-a", len(records))]
    return write_canonical_dataset(Path(directory), records, summaries)


@unittest.skipIf(canonical is None, _SKIP_REASON)
class CanonicalRegistryTests(unittest.TestCase):
    """The five documents this project is allowed to process."""

    def test_exactly_five_documents_are_registered(self):
        self.assertEqual(len(CANONICAL_DOCUMENTS), 5)

    def test_keys_and_document_ids_are_unique(self):
        keys = [document.key for document in CANONICAL_DOCUMENTS]
        ids = [document.document_id for document in CANONICAL_DOCUMENTS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(ids), len(set(ids)))

    def test_source_paths_are_relative_pdfs(self):
        for document in CANONICAL_DOCUMENTS:
            with self.subTest(document=document.key):
                self.assertFalse(document.source_relative.is_absolute())
                self.assertEqual(document.source_relative.suffix, ".pdf")

    def test_document_types_are_known(self):
        for document in CANONICAL_DOCUMENTS:
            with self.subTest(document=document.key):
                self.assertIn(document.document_type, (SYLLABUS, REGULATION))

    def test_syllabi_carry_scheme_and_semester(self):
        for document in CANONICAL_DOCUMENTS:
            if document.document_type != SYLLABUS:
                continue
            with self.subTest(document=document.key):
                self.assertIsNotNone(document.scheme)
                self.assertIsNotNone(document.semester)

    def test_regulations_carry_no_scheme_semester_or_branch(self):
        """A regulation is given no scheme, semester or branch that its structure does not establish."""
        regulations = [d for d in CANONICAL_DOCUMENTS if d.document_type == REGULATION]
        self.assertEqual(len(regulations), 2)
        for document in regulations:
            with self.subTest(document=document.key):
                self.assertIsNone(document.scheme)
                self.assertIsNone(document.semester)
                self.assertIsNone(document.branch)


@unittest.skipIf(canonical is None, _SKIP_REASON)
class CanonicalRecordTests(unittest.TestCase):
    """Record generation from one document's extraction result (no PDF needed)."""

    def setUp(self):
        self.document = CANONICAL_DOCUMENTS[0]
        self.extraction = _synthetic_extraction()

    def test_records_carry_the_document_identity(self):
        records = canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())
        self.assertTrue(records)
        for record in records:
            self.assertEqual(record["document_id"], self.document.document_id)
            self.assertEqual(record["version_id"], "abc123")
            self.assertEqual(record["filename"], self.document.source_relative.name)
            self.assertEqual(record["document_type"], SYLLABUS)
            self.assertEqual(record["scheme"], "2022")
            self.assertEqual(record["semester"], "3")

    def test_page_provenance_is_one_based_and_in_range(self):
        records = canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())
        for record in records:
            for page in record["page_numbers"]:
                self.assertGreaterEqual(page, 1)
                self.assertLessEqual(page, self.extraction.page_count)

    def test_chunk_ids_are_deterministic(self):
        first = canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())
        second = canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())
        self.assertEqual(
            [record["chunk_id"] for record in first],
            [record["chunk_id"] for record in second],
        )

    def test_chunk_ids_differ_between_documents(self):
        other = CANONICAL_DOCUMENTS[1]
        first = canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())
        second = canonical_records(other, self.extraction, "abc123", ChunkingSettings())
        ids_first = {record["chunk_id"] for record in first}
        ids_second = {record["chunk_id"] for record in second}
        self.assertTrue(ids_first.isdisjoint(ids_second))

    def test_a_regulation_document_keeps_unknown_metadata_unknown(self):
        regulation = [d for d in CANONICAL_DOCUMENTS if d.document_type == REGULATION][0]
        records = canonical_records(regulation, self.extraction, "abc123", ChunkingSettings())
        for record in records:
            self.assertIsNone(record["scheme"])
            self.assertIsNone(record["semester"])
            self.assertIsNone(record["branch"])

    def test_record_keys_match_the_chunker_record(self):
        """The canonical format is the chunker's record, not a parallel schema."""
        metadata = DocumentMetadata(
            document_id="doc-x",
            version_id="v1",
            filename="x.pdf",
            document_type=SYLLABUS,
        )
        result = chunk_document(self.extraction, metadata, ChunkingSettings())
        self.assertTrue(result.chunks)
        self.assertEqual(
            set(result.chunks[0].to_record()),
            set(canonical_records(self.document, self.extraction, "abc123", ChunkingSettings())[0]),
        )


@unittest.skipIf(canonical is None, _SKIP_REASON)
class CanonicalWriteReadTests(unittest.TestCase):
    """Writing and reading the dataset, without any PDF."""

    def test_round_trip_returns_the_written_records(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _write_fixture(directory)
            read_manifest, records = read_canonical_dataset(Path(directory))
        self.assertEqual(manifest, read_manifest)
        self.assertEqual(len(records), 2)
        self.assertEqual([record["chunk_id"] for record in records], ["chunk-1", "chunk-2"])

    def test_written_files_are_the_documented_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_fixture(directory)
            names = sorted(path.name for path in Path(directory).iterdir())
        self.assertEqual(names, ["chunks.jsonl", "manifest.json"])

    def test_manifest_records_the_schema_and_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = _write_fixture(directory)
            self.assertEqual(manifest["schema_version"], CANONICAL_SCHEMA_VERSION)
            self.assertEqual(manifest["chunk_count"], 2)
            self.assertEqual(manifest["document_count"], 1)
            self.assertEqual(manifest["chunks_sha256"], sha256_of_file(Path(directory) / "chunks.jsonl"))

    def test_no_timestamp_is_written(self):
        """A timestamp in the artifacts would break byte-reproducible rebuilds."""
        with tempfile.TemporaryDirectory() as directory:
            _write_fixture(directory)
            text = (Path(directory) / "manifest.json").read_text(encoding="utf-8")
        for forbidden in ("timestamp", "generated_at", "created_at", "build_seconds"):
            self.assertNotIn(forbidden, text)

    def test_duplicate_chunk_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                _write_fixture(
                    Path(directory),
                    records=[_record("same", "one"), _record("same", "two")],
                    summaries=[_summary("doc-a", 2)],
                )

    def test_rebuild_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _write_fixture(first)
            _write_fixture(second)
            self.assertEqual(
                (Path(first) / "chunks.jsonl").read_bytes(),
                (Path(second) / "chunks.jsonl").read_bytes(),
            )
            self.assertEqual(
                (Path(first) / "manifest.json").read_bytes(),
                (Path(second) / "manifest.json").read_bytes(),
            )

    def test_missing_chunks_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                read_canonical_dataset(Path(directory))

    def test_tampered_chunks_file_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_fixture(directory)
            path = Path(directory) / "chunks.jsonl"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                read_canonical_dataset(Path(directory))
        self.assertIn("manifest.json", str(caught.exception))

    def test_unsupported_schema_version_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_fixture(directory)
            manifest_path = Path(directory) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = CANONICAL_SCHEMA_VERSION + 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                read_canonical_dataset(Path(directory))
        self.assertIn("schema_version", str(caught.exception))


@unittest.skipIf(canonical is None, _SKIP_REASON)
@unittest.skipUnless(HAVE_PYMUPDF, "PyMuPDF is not installed in this interpreter, so the PDFs cannot be read")
@unittest.skipUnless(canonical.DATASET_ROOT.is_dir(), f"dataset directory not present: {canonical.DATASET_ROOT}")
class RealDatasetTests(unittest.TestCase):
    """The five real PDFs, built into a temporary directory.

    Skipped when the dataset directory is absent or the running interpreter
    has no PDF toolkit. The checked-in canonical dataset and the historical
    pilot directories are never written to.
    """

    def test_all_five_documents_are_processed(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = build_canonical_dataset(Path(directory))
            _, records = read_canonical_dataset(Path(directory))
        self.assertEqual(manifest["document_count"], 5)
        self.assertEqual(manifest["chunk_count"], len(records))
        self.assertEqual(len({record["document_id"] for record in records}), 5)

    def test_every_record_carries_its_source_and_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            build_canonical_dataset(Path(directory))
            _, records = read_canonical_dataset(Path(directory))
        for record in records:
            self.assertTrue(record["chunk_id"])
            self.assertTrue(record["document_id"])
            self.assertTrue(record["version_id"])
            self.assertTrue(record["filename"])
            self.assertTrue(record["document_type"])
            self.assertTrue(record["page_numbers"])
            self.assertTrue(record["chunk_text"].strip())

    def test_regulation_records_keep_unknown_metadata_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            build_canonical_dataset(Path(directory))
            _, records = read_canonical_dataset(Path(directory))
        regulations = [r for r in records if r["document_type"] == REGULATION]
        self.assertTrue(regulations)
        for record in regulations:
            self.assertIsNone(record["scheme"])
            self.assertIsNone(record["semester"])
            self.assertIsNone(record["branch"])

    def test_rebuild_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            build_canonical_dataset(Path(first))
            build_canonical_dataset(Path(second))
            self.assertEqual(
                (Path(first) / "chunks.jsonl").read_bytes(),
                (Path(second) / "chunks.jsonl").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
