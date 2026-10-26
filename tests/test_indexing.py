"""Tests for :mod:`app.indexing.vector_index` and :mod:`app.retrieval.search`.

Run from the repository root:

    python -m unittest discover -s tests -t . -v

These tests never load a real embedding model and never read a PDF. They use a
small deterministic bag-of-words embedder and a six-chunk synthetic canonical
dataset written into a temporary directory, so the whole suite is fast, offline,
and reproducible.

The tests that need FAISS are skipped when ``faiss`` is not installed in the
running interpreter, with the reason printed. That keeps the suite meaningful in
an interpreter that has the ingestion dependencies but not the vector-index
ones; the vector-index tests are then run in the interpreter that has FAISS.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.indexing import vector_index
from app.indexing.embedding import EmbeddingConfig, EmbeddingDependencyError, require_sentence_transformers
from app.indexing.vector_index import (
    BUILDING_MARKER,
    ENTRIES_FILENAME,
    INDEX_FILENAME,
    MANIFEST_FILENAME,
    METRIC_INNER_PRODUCT,
    IndexArtifactError,
    IndexDependencyError,
    build_entries,
    build_index,
    load_index,
)
from app.ingestion.canonical import (
    REGULATION,
    SYLLABUS,
    read_canonical_dataset,
    write_canonical_dataset,
)
from app.retrieval.search import MetadataFilter, Retriever

try:
    import faiss  # noqa: F401

    _FAISS_ERROR: Exception | None = None
except ImportError as exc:
    _FAISS_ERROR = exc

_FAISS_SKIP_REASON = f"faiss is not installed in this interpreter: {_FAISS_ERROR}"

FAKE_MODEL_ID = "fake/bag-of-words"


# --------------------------------------------------------------------------- #
# Deterministic, offline stand-ins
# --------------------------------------------------------------------------- #


def _tokens(text: str) -> list[str]:
    cleaned = "".join(character if character.isalnum() else " " for character in text.lower())
    return [token for token in cleaned.split() if token]


#: The words the stand-in embedder gives a dimension to. Assigning one
#: dimension per word is what makes ranking exactly checkable: two texts that
#: share a word really do score higher, and two texts that do not share one
#: really do score zero. A hash-based vector cannot promise that, because two
#: different words can land on the same dimension and create a match out of
#: nothing. The vocabulary is deliberately wider than it needs to be for the
#: six-chunk corpus so the queries used below are covered too.
FAKE_VOCABULARY: tuple[str, ...] = (
    "and",
    "attendance",
    "award",
    "bachelor",
    "database",
    "degree",
    "distributions",
    "engineering",
    "evaluation",
    "examination",
    "form",
    "indexing",
    "management",
    "normal",
    "normalization",
    "optimization",
    "probability",
    "project",
    "query",
    "regulations",
    "requirement",
    "software",
    "statistics",
    "strategies",
    "third",
)


class FakeEmbedder:
    """A deterministic, collision-free bag-of-words embedder.

    Word-shaped vectors make ranking checkable: the score between a query and a
    chunk is exactly the cosine of their shared-word overlap. Words outside
    :data:`FAKE_VOCABULARY` are ignored, so a text made only of unknown words
    embeds to the zero vector.
    """

    def __init__(self, model_id: str = FAKE_MODEL_ID, dimension: int = 32) -> None:
        self.config = EmbeddingConfig(
            model_id=model_id, dimension=dimension, normalize=True, batch_size=4
        )
        self.encode_calls = 0
        self.encoded: list[str] = []
        if len(FAKE_VOCABULARY) > dimension:
            raise ValueError(
                f"the stand-in vocabulary needs {len(FAKE_VOCABULARY)} dimensions "
                f"but the embedder was given {dimension}"
            )
        # One distinct dimension per word. There is no hashing, so there is no
        # collision, and the same text always produces the same vector.
        self._positions = {word: index for index, word in enumerate(FAKE_VOCABULARY)}

    @property
    def dimension(self) -> int:
        return self.config.dimension

    def encode(self, texts, *, batch_size=None) -> np.ndarray:
        items = [str(text) for text in texts]
        self.encode_calls += 1
        self.encoded.extend(items)
        vectors = np.zeros((len(items), self.config.dimension), dtype=np.float32)
        for row, text in enumerate(items):
            for token in _tokens(text):
                position = self._positions.get(token)
                if position is not None:
                    vectors[row, position] += 1.0
            norm = float(np.linalg.norm(vectors[row]))
            if norm:
                vectors[row] /= norm
        return vectors

    def encode_query(self, query: str) -> np.ndarray:
        return self.encode([query])[0]


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


#: Six chunks across three documents: two 2022-scheme syllabus chunks, two
#: 2025-scheme syllabus chunks, and two regulation chunks with unknown scheme.
#: The texts are meaningless placeholders chosen so that word overlap between a
#: query and a chunk is deliberate and checkable.
def _corpus() -> list[dict]:
    return [
        _record("chunk-a1", "database normalization third normal form",
                page_numbers=[1], page_start=1, page_end=1),
        _record("chunk-a2", "software engineering project management",
                chunk_index=1, page_numbers=[2, 3], page_start=2, page_end=3,
                module=2, module_label="Module 2"),
        _record("chunk-b1", "probability distributions and statistics",
                document_id="doc-b", version_id="vb", filename="b.pdf",
                scheme="2025", semester="3", page_numbers=[5], page_start=5, page_end=5),
        _record("chunk-b2", "database indexing and query optimization strategies",
                document_id="doc-b", version_id="vb", filename="b.pdf",
                scheme="2025", semester="3", chunk_index=1,
                page_numbers=[6], page_start=6, page_end=6),
        _record("chunk-c1", "award of bachelor degree regulations attendance requirement",
                document_id="doc-c", version_id="vc", filename="c.pdf",
                document_type=REGULATION, scheme=None, semester=None, branch=None,
                page_numbers=[10], page_start=10, page_end=10, module=None,
                module_label=None),
        _record("chunk-c2", "examination and evaluation regulations",
                document_id="doc-c", version_id="vc", filename="c.pdf",
                document_type=REGULATION, scheme=None, semester=None, branch=None,
                chunk_index=1, page_numbers=[11], page_start=11, page_end=11,
                module=None, module_label=None),
    ]


def _summaries(records) -> list[dict]:
    by_document: dict[str, list[dict]] = {}
    for record in records:
        by_document.setdefault(record["document_id"], []).append(record)
    return [
        {
            "key": document_id,
            "document_id": document_id,
            "version_id": group[0]["version_id"],
            "filename": group[0]["filename"],
            "source_relative_path": group[0]["filename"],
            "document_type": group[0]["document_type"],
            "scheme": group[0]["scheme"],
            "semester": group[0]["semester"],
            "branch": group[0]["branch"],
            "page_count": 12,
            "text_pages": 12,
            "non_text_pages": 0,
            "chunk_count": len(group),
        }
        for document_id, group in by_document.items()
    ]


class _Fixture:
    """A temporary canonical dataset plus a built index, torn down afterwards."""

    def __init__(self, records=None, model_id: str = FAKE_MODEL_ID) -> None:
        self._stack = tempfile.TemporaryDirectory()
        root = Path(self._stack.name)
        self.canonical_dir = root / "canonical"
        self.index_dir = root / "index"
        self.records = records if records is not None else _corpus()
        self.embedder = FakeEmbedder(model_id=model_id)
        write_canonical_dataset(self.canonical_dir, self.records, _summaries(self.records))

    def build(self, **kwargs):
        kwargs.setdefault("progress", None)
        return build_index(
            self.canonical_dir, self.index_dir, embedder=self.embedder, **kwargs
        )

    def close(self) -> None:
        self._stack.cleanup()


# --------------------------------------------------------------------------- #
# Pure logic that needs no FAISS
# --------------------------------------------------------------------------- #


class EmbeddingConfigTests(unittest.TestCase):
    """The configuration recorded alongside the vectors."""

    def test_defaults_describe_the_project_model(self):
        config = EmbeddingConfig()
        self.assertEqual(config.model_id, "sentence-transformers/all-MiniLM-L6-v2")
        self.assertEqual(config.dimension, 384)
        self.assertTrue(config.normalize)

    def test_manifest_form_records_every_setting(self):
        self.assertEqual(
            sorted(EmbeddingConfig().to_manifest()),
            ["batch_size", "dimension", "model_id", "normalize"],
        )

    def test_fingerprint_is_stable_and_distinguishes_configurations(self):
        self.assertEqual(EmbeddingConfig().fingerprint, EmbeddingConfig().fingerprint)
        self.assertNotEqual(
            EmbeddingConfig().fingerprint,
            EmbeddingConfig(dimension=768).fingerprint,
        )

    def test_missing_embedding_runtime_is_reported_clearly(self):
        """A missing package is reported, not worked around."""
        saved = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None
        try:
            with self.assertRaises(EmbeddingDependencyError) as caught:
                require_sentence_transformers()
        finally:
            if saved is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = saved
        self.assertIn("sentence-transformers", str(caught.exception))


class EntryMappingTests(unittest.TestCase):
    """The ``faiss_id`` mapping, which does not need a vector index to check."""

    def test_entries_are_numbered_by_position(self):
        entries = build_entries(_corpus())
        self.assertEqual([entry["faiss_id"] for entry in entries], list(range(6)))

    def test_entries_keep_the_chunk_identity_and_pages(self):
        entries = build_entries(_corpus())
        self.assertEqual(entries[0]["chunk_id"], "chunk-a1")
        self.assertEqual(entries[1]["page_numbers"], [2, 3])
        self.assertEqual(entries[1]["page_start"], 2)
        self.assertEqual(entries[1]["page_end"], 3)

    def test_entry_text_is_not_duplicated(self):
        """The canonical dataset stays the single source of chunk text."""
        for entry in build_entries(_corpus()):
            self.assertNotIn("chunk_text", entry)

    def test_a_record_missing_a_field_is_rejected_by_name(self):
        record = _corpus()[0]
        del record["page_numbers"]
        with self.assertRaises(IndexArtifactError) as caught:
            build_entries([record])
        self.assertIn("page_numbers", str(caught.exception))

    def test_duplicate_chunk_ids_are_rejected(self):
        records = _corpus()
        records[1]["chunk_id"] = records[0]["chunk_id"]
        with self.assertRaises(IndexArtifactError):
            build_entries(records)


class MissingVectorRuntimeTests(unittest.TestCase):
    """FAISS being absent is reported, never guessed around."""

    def test_require_faiss_reports_a_dependency_error(self):
        saved = sys.modules.get("faiss")
        sys.modules["faiss"] = None
        try:
            with self.assertRaises(IndexDependencyError) as caught:
                vector_index._require_faiss()
        finally:
            if saved is None:
                sys.modules.pop("faiss", None)
            else:
                sys.modules["faiss"] = saved
        self.assertIn("faiss", str(caught.exception))

    def test_load_index_reports_a_dependency_error(self):
        """With the artifacts present but FAISS absent, the missing package is named."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / INDEX_FILENAME).write_bytes(b"")
            (root / ENTRIES_FILENAME).write_text("", encoding="utf-8")
            (root / MANIFEST_FILENAME).write_text(
                json.dumps({"schema_version": vector_index.INDEX_SCHEMA_VERSION}),
                encoding="utf-8",
            )
            saved = sys.modules.get("faiss")
            sys.modules["faiss"] = None
            try:
                with self.assertRaises(IndexDependencyError) as caught:
                    load_index(root)
            finally:
                if saved is None:
                    sys.modules.pop("faiss", None)
                else:
                    sys.modules["faiss"] = saved
        self.assertIn("faiss", str(caught.exception))


# --------------------------------------------------------------------------- #
# Index build, persistence, and validation (needs FAISS)
# --------------------------------------------------------------------------- #


@unittest.skipIf(_FAISS_ERROR is not None, _FAISS_SKIP_REASON)
class IndexBuildTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _Fixture()
        self.addCleanup(self.fixture.close)

    def test_build_then_load_round_trip(self):
        manifest = self.fixture.build()
        loaded = load_index(self.fixture.index_dir)

        self.assertEqual(manifest["vector_count"], 6)
        self.assertEqual(loaded.vector_count, 6)
        self.assertEqual(loaded.dimension, 32)
        self.assertEqual(loaded.index.ntotal, 6)
        self.assertEqual(loaded.index.d, 32)
        self.assertEqual(loaded.metric, METRIC_INNER_PRODUCT)
        self.assertEqual(manifest["index_type"], "IndexFlatIP")
        self.assertEqual(loaded.model_id, FAKE_MODEL_ID)

    def test_artifact_directory_holds_exactly_the_documented_files(self):
        self.fixture.build()
        names = sorted(path.name for path in self.fixture.index_dir.iterdir())
        self.assertEqual(names, sorted([INDEX_FILENAME, ENTRIES_FILENAME, MANIFEST_FILENAME]))

    def test_the_building_marker_is_removed_after_a_successful_build(self):
        self.fixture.build()
        self.assertFalse((self.fixture.index_dir / BUILDING_MARKER).exists())

    def test_vector_count_matches_the_canonical_chunk_count(self):
        self.fixture.build()
        canonical_manifest, records = read_canonical_dataset(self.fixture.canonical_dir)
        loaded = load_index(self.fixture.index_dir)
        self.assertEqual(loaded.vector_count, len(records))
        self.assertEqual(
            loaded.manifest["canonical"]["chunks_sha256"], canonical_manifest["chunks_sha256"]
        )

    def test_entries_stay_aligned_with_their_vectors(self):
        self.fixture.build()
        loaded = load_index(self.fixture.index_dir)
        self.assertEqual(
            [entry["faiss_id"] for entry in loaded.entries],
            list(range(loaded.vector_count)),
        )
        self.assertEqual(
            [entry["chunk_id"] for entry in loaded.entries],
            [record["chunk_id"] for record in self.fixture.records],
        )

    def test_metadata_and_page_provenance_survive_the_round_trip(self):
        self.fixture.build()
        loaded = load_index(self.fixture.index_dir)
        entry = loaded.entry(1)
        self.assertEqual(entry["chunk_id"], "chunk-a2")
        self.assertEqual(entry["document_id"], "doc-a")
        self.assertEqual(entry["version_id"], "va")
        self.assertEqual(entry["filename"], "a.pdf")
        self.assertEqual(entry["scheme"], "2022")
        self.assertEqual(entry["semester"], "5")
        self.assertEqual(entry["module"], 2)
        self.assertEqual(entry["page_numbers"], [2, 3])
        self.assertEqual(entry["page_start"], 2)
        self.assertEqual(entry["page_end"], 3)

    def test_unknown_metadata_stays_unknown_in_the_index(self):
        self.fixture.build()
        loaded = load_index(self.fixture.index_dir)
        regulation_ids = [
            entry["faiss_id"]
            for entry in loaded.entries
            if entry["document_type"] == REGULATION
        ]
        self.assertEqual(len(regulation_ids), 2)
        for faiss_id in regulation_ids:
            entry = loaded.entry(faiss_id)
            self.assertIsNone(entry["scheme"])
            self.assertIsNone(entry["semester"])
            self.assertIsNone(entry["branch"])

    def test_existing_index_is_reused_without_re_embedding(self):
        self.fixture.build()
        calls_after_build = self.fixture.embedder.encode_calls
        index_bytes = (self.fixture.index_dir / INDEX_FILENAME).read_bytes()

        manifest = self.fixture.build()

        self.assertEqual(manifest["vector_count"], 6)
        self.assertEqual(self.fixture.embedder.encode_calls, calls_after_build)
        self.assertEqual((self.fixture.index_dir / INDEX_FILENAME).read_bytes(), index_bytes)

    def test_rebuild_flag_forces_re_embedding(self):
        self.fixture.build()
        calls_after_build = self.fixture.embedder.encode_calls
        self.fixture.build(rebuild=True)
        self.assertGreater(self.fixture.embedder.encode_calls, calls_after_build)

    def test_rebuild_produces_identical_artifacts(self):
        self.fixture.build()
        first_index = (self.fixture.index_dir / INDEX_FILENAME).read_bytes()
        first_entries = (self.fixture.index_dir / ENTRIES_FILENAME).read_bytes()
        first_manifest = (self.fixture.index_dir / MANIFEST_FILENAME).read_bytes()

        self.fixture.build(rebuild=True)

        self.assertEqual((self.fixture.index_dir / ENTRIES_FILENAME).read_bytes(), first_entries)
        self.assertEqual((self.fixture.index_dir / MANIFEST_FILENAME).read_bytes(), first_manifest)
        self.assertEqual((self.fixture.index_dir / INDEX_FILENAME).read_bytes(), first_index)

    def test_no_timestamp_is_written_into_the_manifest(self):
        self.fixture.build()
        text = (self.fixture.index_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        for forbidden in ("timestamp", "generated_at", "created_at", "build_seconds"):
            self.assertNotIn(forbidden, text)

    def test_unchanged_metadata_makes_a_changed_dataset_force_a_rebuild(self):
        self.fixture.build()
        extra = _record("chunk-a3", "extra chunk", chunk_index=2)
        write_canonical_dataset(
            self.fixture.canonical_dir,
            self.fixture.records + [extra],
            _summaries(self.fixture.records + [extra]),
        )
        manifest = self.fixture.build()
        self.assertEqual(manifest["vector_count"], 7)

    def test_empty_canonical_dataset_is_reported(self):
        write_canonical_dataset(self.fixture.canonical_dir, [], [])
        with self.assertRaises(IndexArtifactError) as caught:
            self.fixture.build()
        self.assertIn("no chunks", str(caught.exception))

    def test_changed_canonical_file_is_rejected(self):
        """A dataset that changed underneath its manifest is not silently indexed."""
        manifest_path = self.fixture.canonical_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chunks_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.fixture.build()

    def test_embedding_configuration_is_recorded(self):
        self.fixture.build()
        loaded = load_index(self.fixture.index_dir)
        self.assertEqual(loaded.manifest["embedding"], self.fixture.embedder.config.to_manifest())
        self.assertEqual(
            loaded.manifest["metric_description"],
            "inner product; vectors are L2-normalised, so this is cosine similarity",
        )


@unittest.skipIf(_FAISS_ERROR is not None, _FAISS_SKIP_REASON)
class IndexArtifactErrorTests(unittest.TestCase):
    """Every broken or incompatible artifact state is reported, not tolerated."""

    def setUp(self):
        self.fixture = _Fixture()
        self.addCleanup(self.fixture.close)
        self.fixture.build()

    def _manifest(self) -> dict:
        return json.loads((self.fixture.index_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    def _write_manifest(self, manifest: dict) -> None:
        (self.fixture.index_dir / MANIFEST_FILENAME).write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def test_missing_directory(self):
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir / "absent")
        self.assertIn("does not exist", str(caught.exception))

    def test_missing_artifact_names_the_file(self):
        (self.fixture.index_dir / INDEX_FILENAME).unlink()
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn(INDEX_FILENAME, str(caught.exception))

    def test_interrupted_build_is_refused(self):
        (self.fixture.index_dir / BUILDING_MARKER).write_text("building\n", encoding="utf-8")
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("incomplete", str(caught.exception))

    def test_unsupported_schema_version(self):
        manifest = self._manifest()
        manifest["schema_version"] = 999
        self._write_manifest(manifest)
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("schema_version", str(caught.exception))

    def test_modified_metadata_sidecar(self):
        entries_path = self.fixture.index_dir / ENTRIES_FILENAME
        lines = entries_path.read_text(encoding="utf-8").splitlines()
        entries_path.write_text("\n".join(lines[:5]) + "\n", encoding="utf-8")
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("modified after the build", str(caught.exception))

    def test_broken_faiss_id_sequence(self):
        entries_path = self.fixture.index_dir / ENTRIES_FILENAME
        entries = [json.loads(line) for line in entries_path.read_text(encoding="utf-8").splitlines()]
        entries[0]["faiss_id"] = 4
        entries_path.write_text(
            "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
        )
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("mapping is broken", str(caught.exception))

    def test_vector_count_disagrees_with_the_manifest(self):
        manifest = self._manifest()
        manifest["vector_count"] = 99
        self._write_manifest(manifest)
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("99", str(caught.exception))

    def test_dimension_disagrees_with_the_manifest(self):
        manifest = self._manifest()
        manifest["dimension"] = 64
        self._write_manifest(manifest)
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("dimension", str(caught.exception).lower())

    def test_metric_disagrees_with_the_index_type(self):
        """A manifest claiming the wrong metric would misreport every score."""
        manifest = self._manifest()
        manifest["metric"] = "l2"
        self._write_manifest(manifest)
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("metric", str(caught.exception))

    def test_unknown_metric(self):
        manifest = self._manifest()
        manifest["metric"] = "cosine"
        self._write_manifest(manifest)
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn("unknown metric", str(caught.exception))

    def test_unreadable_vector_file(self):
        (self.fixture.index_dir / INDEX_FILENAME).write_bytes(b"not a faiss index")
        with self.assertRaises(IndexArtifactError) as caught:
            load_index(self.fixture.index_dir)
        self.assertIn(INDEX_FILENAME, str(caught.exception))


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


@unittest.skipIf(_FAISS_ERROR is not None, _FAISS_SKIP_REASON)
class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _Fixture()
        self.addCleanup(self.fixture.close)
        self.fixture.build()
        self.retriever = Retriever(self.fixture.index_dir, self.fixture.canonical_dir, embedder=self.fixture.embedder)

    def test_metric_and_corpus_are_explicit(self):
        self.assertEqual(self.retriever.metric, METRIC_INNER_PRODUCT)
        self.assertEqual(self.retriever.vector_count, 6)
        self.assertEqual(self.retriever.model_id, FAKE_MODEL_ID)

    def test_the_best_match_is_ranked_first(self):
        results = self.retriever.search("database normalization", top_k=3)
        self.assertTrue(results)
        self.assertEqual(results[0].chunk_id, "chunk-a1")
        self.assertEqual(results[0].score, max(result.score for result in results))

    def test_scores_are_inner_products_of_unit_vectors(self):
        results = self.retriever.search("database normalization", top_k=6)
        for result in results:
            self.assertEqual(result.metric, METRIC_INNER_PRODUCT)
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 1.0 + 1e-6)

    def test_a_shared_word_matches_the_right_document(self):
        results = self.retriever.search("probability distributions", top_k=1)
        self.assertEqual(results[0].chunk_id, "chunk-b1")

    def test_top_k_above_the_corpus_size_returns_everything(self):
        results = self.retriever.search("regulations", top_k=50)
        self.assertEqual(len(results), 6)

    def test_results_return_enough_information_for_a_citation(self):
        result = self.retriever.search("software engineering", top_k=1)[0]
        citation = result.citation()
        self.assertEqual(citation["chunk_id"], "chunk-a2")
        self.assertEqual(citation["document_id"], "doc-a")
        self.assertEqual(citation["version_id"], "va")
        self.assertEqual(citation["filename"], "a.pdf")
        self.assertEqual(citation["page_numbers"], [2, 3])
        self.assertEqual(result.page_numbers, (2, 3))
        self.assertTrue(result.text)

    def test_page_provenance_is_never_renumbered(self):
        result = self.retriever.search("examination evaluation", top_k=1)[0]
        self.assertEqual(result.page_numbers, (11,))
        self.assertEqual(result.citation()["page_start"], 11)

    def test_filtering_by_scheme_excludes_other_schemes(self):
        results = self.retriever.search(
            "database", top_k=6, filters=MetadataFilter(scheme="2025")
        )
        self.assertTrue(results)
        for result in results:
            self.assertEqual(result.entry["scheme"], "2025")

    def test_filtering_changes_the_ranking_of_the_same_query(self):
        unfiltered = self.retriever.search("database", top_k=1)
        filtered = self.retriever.search("database", top_k=1, filters=MetadataFilter(scheme="2025"))
        self.assertEqual(unfiltered[0].chunk_id, "chunk-a1")
        self.assertEqual(filtered[0].chunk_id, "chunk-b2")

    def test_filtering_by_document_type_returns_only_that_type(self):
        results = self.retriever.search(
            "regulations", top_k=6, filters=MetadataFilter(document_type=REGULATION)
        )
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.entry["document_type"], REGULATION)

    def test_a_scheme_filter_does_not_match_unknown_schemes(self):
        """A regulation has no scheme, so it must not answer a 2022-scheme query."""
        results = self.retriever.search(
            "regulations award degree", top_k=6, filters=MetadataFilter(scheme="2022")
        )
        for result in results:
            self.assertNotEqual(result.entry["document_type"], REGULATION)

    def test_filters_combine(self):
        results = self.retriever.search(
            "database",
            top_k=6,
            filters=MetadataFilter(scheme="2022", semester="5", document_type=SYLLABUS),
        )
        self.assertTrue(results)
        for result in results:
            self.assertEqual(result.entry["scheme"], "2022")
            self.assertEqual(result.entry["semester"], "5")

    def test_a_filter_with_no_matches_returns_nothing(self):
        results = self.retriever.search(
            "database", top_k=5, filters=MetadataFilter(document_type="circular")
        )
        self.assertEqual(results, [])

    def test_filter_by_document_ids(self):
        results = self.retriever.search(
            "database", top_k=6, filters=MetadataFilter(document_ids=("doc-b",))
        )
        self.assertTrue(results)
        for result in results:
            self.assertEqual(result.entry["document_id"], "doc-b")

    def test_empty_filter_is_recognised(self):
        self.assertTrue(MetadataFilter().is_empty())
        self.assertFalse(MetadataFilter(scheme="2022").is_empty())
        self.assertEqual(MetadataFilter().to_dict(), {})
        self.assertEqual(MetadataFilter(scheme="2022").to_dict(), {"scheme": "2022"})

    def test_a_non_string_query_is_rejected(self):
        for bad in ("", "   ", None, 7):
            with self.subTest(query=bad):
                with self.assertRaises(ValueError):
                    self.retriever.search(bad)

    def test_a_non_positive_top_k_is_rejected(self):
        for bad in (0, -3):
            with self.subTest(top_k=bad):
                with self.assertRaises(ValueError):
                    self.retriever.search("database", top_k=bad)

    def test_a_query_the_index_cannot_score_still_returns_ranked_chunks(self):
        """No similarity threshold is applied: the caller decides relevance."""
        results = self.retriever.search("zzz nonexistent token", top_k=3)
        self.assertEqual(len(results), 3)


@unittest.skipIf(_FAISS_ERROR is not None, _FAISS_SKIP_REASON)
class RetrievalCompatibilityTests(unittest.TestCase):
    """The retriever refuses to query an index it does not match."""

    def test_a_different_embedding_configuration_is_refused(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        fixture.build()
        other = FakeEmbedder(model_id="fake/other-model")
        with self.assertRaises(IndexArtifactError) as caught:
            Retriever(fixture.index_dir, fixture.canonical_dir, embedder=other)
        self.assertIn("other-model", str(caught.exception))

    def test_a_different_canonical_dataset_is_refused(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        fixture.build()

        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        other_records = _corpus()[:-1]
        write_canonical_dataset(Path(other.name), other_records, _summaries(other_records))

        with self.assertRaises(IndexArtifactError) as caught:
            Retriever(fixture.index_dir, Path(other.name), embedder=fixture.embedder)
        self.assertIn("does not match", str(caught.exception))

    def test_a_regulation_and_a_syllabus_can_be_told_apart_by_filter(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        fixture.build()
        retriever = Retriever(fixture.index_dir, fixture.canonical_dir, embedder=fixture.embedder)
        syllabi = retriever.search("regulations", top_k=6, filters=MetadataFilter(document_type=SYLLABUS))
        regulations = retriever.search("regulations", top_k=6, filters=MetadataFilter(document_type=REGULATION))
        self.assertEqual(len(syllabi) + len(regulations), 6)
        self.assertTrue(all(result.entry["document_type"] == SYLLABUS for result in syllabi))


if __name__ == "__main__":
    unittest.main()
