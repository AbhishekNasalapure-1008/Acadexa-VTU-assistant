"""Tests for the retrieval-evaluation layer in :mod:`app.evaluation`.

Run from the repository root:

    python -m unittest discover -s tests -t . -v

Three groups of tests live here:

* **Metric arithmetic** (:mod:`app.evaluation.metrics`) - checked against
  hand-computed values, including the cases the metrics deliberately refuse.
* **Evaluation-data integrity** (:mod:`app.evaluation.dataset`,
  :mod:`app.evaluation.build_dataset`) - checked with hand-built questions and a
  small synthetic corpus, so a fabricated label or a stale selector fails loudly.
* **Evaluation runner** (:mod:`app.evaluation.evaluate`) - checked with a tiny
  stand-in retriever, so filter and provenance checking is exercised without
  FAISS or an embedding model. The tests that do need FAISS are skipped when it
  is not installed in the running interpreter, and the tests that read the real
  artifacts are skipped when those artifacts are absent.

Nothing here loads a real embedding model, reads a PDF, or reaches the network.
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

from app.evaluation.build_dataset import Corpus, build_questions
from app.evaluation.dataset import (
    CATEGORIES,
    DEFAULT_QUESTIONS_PATH,
    EvaluationDataError,
    EvaluationQuestion,
    load_questions,
    validate_questions,
    write_questions,
)
from app.evaluation.evaluate import (
    METRIC_NAMES,
    build_report,
    by_category,
    evaluate_questions,
    metrics_table,
)
from app.evaluation.metrics import (
    DEFAULT_K_VALUES,
    MetricError,
    hit_at_k,
    mean,
    precision_at_k,
    rank_of_first_relevant,
    recall_at_k,
    reciprocal_rank_at_k,
)
from app.ingestion.canonical import REGULATION, read_canonical_dataset

#: The real artifacts, used by the integration tests. Their presence is checked
#: rather than assumed, so the suite still runs on a checkout without them.
CANONICAL_DIR = REPO_ROOT / "data" / "processed" / "canonical"
CANONICAL_CHUNKS = CANONICAL_DIR / "chunks.jsonl"
INDEX_ENTRIES = REPO_ROOT / "data" / "processed" / "index" / "entries.jsonl"
QUESTIONS_PATH = DEFAULT_QUESTIONS_PATH

_CANONICAL_AVAILABLE = CANONICAL_CHUNKS.is_file()
_CANONICAL_SKIP_REASON = f"the canonical dataset is absent: {CANONICAL_CHUNKS}"
_QUESTIONS_SKIP_REASON = f"the evaluation dataset is absent: {QUESTIONS_PATH}"

#: The index build and retrieval tests share the offline FAISS stand-ins from
#: ``tests.test_indexing`` (a deterministic bag-of-words embedder plus a
#: temporary six-chunk corpus), so this module repeats neither.
from tests import test_indexing


def _question(
    question_id: str = "q1",
    query: str = "what is the attendance requirement",
    category: str = "regulation",
    filters: dict | None = None,
    relevant_chunk_ids: tuple[str, ...] = ("doc-a:c1",),
    note: str = "",
) -> EvaluationQuestion:
    return EvaluationQuestion(
        question_id=question_id,
        query=query,
        category=category,
        filters=dict(filters or {}),
        relevant_chunk_ids=tuple(relevant_chunk_ids),
        note=note,
    )


def _chunk(
    chunk_id: str,
    text: str,
    *,
    chunk_index: int = 0,
    document_id: str = "doc-a",
    subject_code: str = "BCS101",
    module: int | None = 1,
) -> dict:
    """The subset of a canonical record :class:`Corpus` reads."""
    return {
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
        "document_id": document_id,
        "subject_code": subject_code,
        "module": module,
        "chunk_text": text,
    }


# --------------------------------------------------------------------------- #
# Metric arithmetic
# --------------------------------------------------------------------------- #


class MetricArithmeticTests(unittest.TestCase):
    """Every metric is checked against a value computed by hand."""

    #: best-first ranking used below
    RETRIEVED = ["a", "b", "c", "d"]

    def test_recall_counts_the_relevant_fraction_found(self):
        relevant = {"b", "d"}
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 1), 0.0)
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 2), 0.5)
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 3), 0.5)
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 4), 1.0)

    def test_precision_uses_k_as_its_denominator(self):
        relevant = {"b", "d"}
        self.assertEqual(precision_at_k(self.RETRIEVED, relevant, 1), 0.0)
        self.assertEqual(precision_at_k(self.RETRIEVED, relevant, 2), 0.5)
        self.assertEqual(precision_at_k(self.RETRIEVED, relevant, 3), 1 / 3)
        self.assertEqual(precision_at_k(self.RETRIEVED, relevant, 4), 0.5)

    def test_precision_is_not_rewarded_when_the_retriever_returns_fewer_than_k(self):
        self.assertEqual(precision_at_k(["a"], {"a"}, 4), 0.25)

    def test_reciprocal_rank_reports_the_first_relevant_position(self):
        relevant = {"b", "c"}
        self.assertEqual(reciprocal_rank_at_k(self.RETRIEVED, relevant, 1), 0.0)
        self.assertEqual(reciprocal_rank_at_k(self.RETRIEVED, relevant, 2), 0.5)
        self.assertEqual(reciprocal_rank_at_k(self.RETRIEVED, relevant, 4), 0.5)

    def test_hit_is_one_until_the_first_relevant_chunk_is_reached(self):
        relevant = {"c"}
        self.assertEqual(hit_at_k(self.RETRIEVED, relevant, 1), 0.0)
        self.assertEqual(hit_at_k(self.RETRIEVED, relevant, 2), 0.0)
        self.assertEqual(hit_at_k(self.RETRIEVED, relevant, 3), 1.0)

    def test_a_relevant_chunk_beyond_k_scores_zero(self):
        relevant = {"d"}
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 3), 0.0)
        self.assertEqual(hit_at_k(self.RETRIEVED, relevant, 3), 0.0)
        self.assertEqual(reciprocal_rank_at_k(self.RETRIEVED, relevant, 3), 0.0)

    def test_a_question_with_no_relevant_chunk_scores_zero(self):
        relevant = {"zzz"}
        self.assertEqual(recall_at_k(self.RETRIEVED, relevant, 4), 0.0)
        self.assertEqual(precision_at_k(self.RETRIEVED, relevant, 4), 0.0)
        self.assertEqual(hit_at_k(self.RETRIEVED, relevant, 4), 0.0)
        self.assertEqual(reciprocal_rank_at_k(self.RETRIEVED, relevant, 4), 0.0)

    def test_repeated_retrieved_ids_are_not_double_counted(self):
        self.assertEqual(recall_at_k(["a", "a", "a"], {"a"}, 3), 1.0)
        self.assertEqual(precision_at_k(["a", "a", "a"], {"a"}, 3), 1 / 3)

    def test_an_empty_relevance_set_is_rejected_rather_than_scored(self):
        for function in (recall_at_k, precision_at_k, reciprocal_rank_at_k, hit_at_k):
            with self.subTest(metric=function.__name__):
                with self.assertRaises(MetricError):
                    function(self.RETRIEVED, set(), 3)

    def test_a_non_positive_or_non_integer_k_is_rejected(self):
        for bad in (0, -1, True, 1.5, "3"):
            with self.subTest(k=bad):
                with self.assertRaises(MetricError):
                    recall_at_k(self.RETRIEVED, {"a"}, bad)

    def test_rank_of_first_relevant_is_one_based_and_none_when_absent(self):
        self.assertEqual(rank_of_first_relevant(self.RETRIEVED, {"c"}), 3)
        self.assertIsNone(rank_of_first_relevant(self.RETRIEVED, {"zzz"}))

    def test_mean_of_nothing_is_none_not_zero(self):
        self.assertIsNone(mean([]))
        self.assertAlmostEqual(mean([0.0, 1.0]), 0.5)

    def test_the_reported_cut_offs_are_the_documented_ones(self):
        self.assertEqual(DEFAULT_K_VALUES, (1, 3, 5, 10))


# --------------------------------------------------------------------------- #
# Evaluation-data integrity
# --------------------------------------------------------------------------- #


class ValidationTests(unittest.TestCase):
    """``validate_questions`` names every problem that would void a score."""

    def test_a_well_formed_question_set_has_no_problems(self):
        questions = [
            _question("q1", "first", "regulation"),
            _question("q2", "second", "module", relevant_chunk_ids=("doc-a:c1", "doc-a:c2")),
            _question("q3", "third", "insufficient_evidence", relevant_chunk_ids=()),
        ]
        self.assertEqual(validate_questions(questions), [])

    def test_a_duplicate_question_id_is_reported(self):
        questions = [_question("q1", "first"), _question("q1", "second")]
        problems = validate_questions(questions)
        self.assertTrue(any("duplicate question id" in problem for problem in problems))

    def test_a_duplicate_query_is_reported_across_case_and_spacing(self):
        questions = [_question("q1", "Attendance   requirement"), _question("q2", " attendance requirement ")]
        problems = validate_questions(questions)
        self.assertTrue(any("duplicate query" in problem for problem in problems))

    def test_an_empty_query_is_reported(self):
        problems = validate_questions([_question("q1", "   ")])
        self.assertTrue(any("empty query" in problem for problem in problems))

    def test_an_unknown_category_is_reported(self):
        problems = validate_questions([_question("q1", "x", "opinion")])
        self.assertTrue(any("unknown category" in problem for problem in problems))

    def test_an_unknown_filter_field_is_reported(self):
        problems = validate_questions([_question("q1", "x", filters={"faculty": "CSE"})])
        self.assertTrue(any("unknown filter field" in problem for problem in problems))

    def test_document_ids_must_be_a_list(self):
        problems = validate_questions([_question("q1", "x", filters={"document_ids": "doc-a"})])
        self.assertTrue(any("document_ids must be a list" in problem for problem in problems))

    def test_an_answerable_category_without_chunks_is_reported(self):
        problems = validate_questions([_question("q1", "x", "module", relevant_chunk_ids=())])
        self.assertTrue(any("must have relevant chunks" in problem for problem in problems))

    def test_the_unanswerable_category_must_not_carry_chunks(self):
        problems = validate_questions(
            [_question("q1", "x", "insufficient_evidence", relevant_chunk_ids=("doc-a:c1",))]
        )
        self.assertTrue(any("must not have relevant chunks" in problem for problem in problems))

    def test_a_repeated_relevant_chunk_id_is_reported(self):
        problems = validate_questions(
            [_question("q1", "x", relevant_chunk_ids=("doc-a:c1", "doc-a:c1"))]
        )
        self.assertTrue(any("repeated relevant chunk id" in problem for problem in problems))

    def test_a_label_absent_from_the_corpus_is_reported(self):
        """A judgement naming a chunk that does not exist is a fabrication."""
        questions = [_question("q1", "x", relevant_chunk_ids=("doc-a:absent",))]
        problems = validate_questions(questions, known_chunk_ids={"doc-a:c1"})
        self.assertTrue(any("not in the canonical dataset" in problem for problem in problems))

    def test_all_problems_are_returned_at_once(self):
        questions = [
            _question("q1", "x", "opinion", filters={"faculty": "CSE"}),
            _question("q1", "x", "insufficient_evidence", relevant_chunk_ids=("doc-a:c1",)),
        ]
        problems = validate_questions(questions)
        self.assertGreaterEqual(len(problems), 4)


class DatasetFileTests(unittest.TestCase):
    """Loading, writing, and the determinism of the questions file."""

    def test_a_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(EvaluationDataError):
                load_questions(Path(directory) / "absent.jsonl")

    def test_invalid_json_is_reported_with_its_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            valid = json.dumps(
                {
                    "id": "q1",
                    "query": "x",
                    "category": "module",
                    "relevant_chunk_ids": ["doc-a:c1"],
                }
            )
            path.write_text(valid + "\nnot json\n", encoding="utf-8")
            with self.assertRaises(EvaluationDataError) as caught:
                load_questions(path)
            self.assertIn("line 2", str(caught.exception))

    def test_an_empty_dataset_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            path.write_text("\n\n", encoding="utf-8")
            with self.assertRaises(EvaluationDataError):
                load_questions(path)

    def test_a_record_missing_a_required_key_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            path.write_text(json.dumps({"id": "q1", "query": "x", "category": "module"}) + "\n", encoding="utf-8")
            with self.assertRaises(EvaluationDataError) as caught:
                load_questions(path)
            self.assertIn("relevant_chunk_ids", str(caught.exception))

    def test_write_then_load_round_trips_and_is_byte_identical(self):
        questions = [
            _question("q1", "first", "regulation"),
            _question("q2", "second", "insufficient_evidence", relevant_chunk_ids=()),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            write_questions(path, questions)
            first = path.read_bytes()
            write_questions(path, questions)
            self.assertEqual(path.read_bytes(), first)

            reloaded = load_questions(path)
            self.assertEqual([q.to_record() for q in reloaded], [q.to_record() for q in questions])

    def test_no_timestamp_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            write_questions(path, [_question("q1", "first")])
            text = path.read_text(encoding="utf-8")
            for forbidden in ("timestamp", "generated_at", "created_at"):
                self.assertNotIn(forbidden, text)


# --------------------------------------------------------------------------- #
# The builder's grounding selectors
# --------------------------------------------------------------------------- #


class CorpusSelectorTests(unittest.TestCase):
    """Every label comes from a selector that reads the real records."""

    def setUp(self):
        self.records = [
            _chunk("doc-a:c1", "Course Code BCS101 Semester 3", chunk_index=0),
            _chunk("doc-a:c2", "MODULE-1 Introduction to databases", chunk_index=1),
            _chunk("doc-a:c3", "MODULE-2 Database normalization", chunk_index=2, module=2),
            _chunk("doc-a:c4", "Text mentioning third normal\n   form across lines",
                   chunk_index=3, module=2),
        ]
        self.corpus = Corpus(self.records)

    def test_chunk_ids_come_back_in_canonical_order(self):
        self.assertEqual(
            self.corpus.chunk_ids(), ["doc-a:c1", "doc-a:c2", "doc-a:c3", "doc-a:c4"]
        )

    def test_header_returns_the_subjects_first_chunk_only(self):
        self.assertEqual(self.corpus.header("doc-a", "BCS101"), ["doc-a:c1"])

    def test_module_returns_the_chunks_marked_for_that_module(self):
        self.assertEqual(self.corpus.module("doc-a", "BCS101", 2), ["doc-a:c3", "doc-a:c4"])

    def test_containing_is_case_insensitive(self):
        self.assertEqual(self.corpus.containing("DATABASE NORMALIZATION"), ["doc-a:c3"])

    def test_containing_matches_across_line_breaks(self):
        self.assertEqual(self.corpus.containing("third normal form"), ["doc-a:c4"])

    def test_by_ids_returns_verified_ids_in_the_order_given(self):
        self.assertEqual(
            self.corpus.by_ids("doc-a:c3", "doc-a:c1"), ["doc-a:c3", "doc-a:c1"]
        )

    def test_a_header_for_an_absent_subject_raises(self):
        with self.assertRaises(EvaluationDataError):
            self.corpus.header("doc-a", "BCS999")

    def test_a_module_for_an_absent_module_raises(self):
        with self.assertRaises(EvaluationDataError):
            self.corpus.module("doc-a", "BCS101", 9)

    def test_a_phrase_that_does_not_occur_raises(self):
        with self.assertRaises(EvaluationDataError):
            self.corpus.containing("quantum computing")

    def test_an_unknown_explicit_id_raises(self):
        with self.assertRaises(EvaluationDataError):
            self.corpus.by_ids("doc-a:absent")

    def test_a_duplicate_chunk_id_in_the_corpus_raises(self):
        duplicate = self.records + [_chunk("doc-a:c1", "again", chunk_index=4)]
        with self.assertRaises(EvaluationDataError):
            Corpus(duplicate)


# --------------------------------------------------------------------------- #
# The evaluation runner, driven by a small stand-in retriever
# --------------------------------------------------------------------------- #


class _StubResult:
    """The four attributes :func:`evaluate_questions` reads from a result."""

    def __init__(self, entry: dict, score: float) -> None:
        self.entry = entry
        self.score = float(score)
        self.chunk_id = entry["chunk_id"]

    @property
    def page_numbers(self) -> tuple[int, ...]:
        return tuple(self.entry.get("page_numbers") or ())


class _StubRetriever:
    """A retriever with fixed rankings: no FAISS, no model, no network.

    It returns exactly what its ``rankings`` say, filters included, so the
    evaluation's own filter and provenance checks can be exercised on purpose.
    """

    def __init__(self, rankings: dict[str, list[tuple[str, float]]], records: list[dict]) -> None:
        self._rankings = rankings
        self._by_id = {record["chunk_id"]: record for record in records}
        self.metric = "inner_product"
        self.vector_count = len(records)
        self.model_id = "stub/model"

    def search(self, query: str, *, top_k: int = 5, filters=None):
        results = []
        for chunk_id, score in self._rankings.get(query, [])[:top_k]:
            entry = dict(self._by_id[chunk_id])
            entry.pop("chunk_text", None)
            results.append(_StubResult(entry, score))
        return results


def _stub_records() -> list[dict]:
    """Index-entry-shaped records: no ``chunk_text``, complete provenance."""
    return [
        {
            "chunk_id": "doc-a:c1",
            "document_id": "doc-a",
            "version_id": "va",
            "filename": "a.pdf",
            "document_type": "syllabus",
            "scheme": "2022",
            "semester": "3",
            "page_numbers": [1, 2],
            "page_start": 1,
            "page_end": 2,
        },
        {
            "chunk_id": "doc-b:c1",
            "document_id": "doc-b",
            "version_id": "vb",
            "filename": "b.pdf",
            "document_type": "regulation",
            "scheme": None,
            "semester": None,
            "page_numbers": [7],
            "page_start": 7,
            "page_end": 7,
        },
    ]


class EvaluationRunnerTests(unittest.TestCase):
    """Filter, provenance and metric wiring, checked without FAISS."""

    def setUp(self):
        self.records = _stub_records()
        self.chunk_ids = {record["chunk_id"] for record in self.records}

    def _run(self, questions, rankings):
        retriever = _StubRetriever(rankings, self.records)
        return evaluate_questions(questions, retriever, canonical_chunk_ids=self.chunk_ids)

    def test_a_correct_top_ranked_result_scores_one(self):
        questions = [_question("q1", "attendance", "regulation", relevant_chunk_ids=("doc-a:c1",))]
        run = self._run(questions, {"attendance": [("doc-a:c1", 0.9), ("doc-b:c1", 0.1)]})
        outcome = run.outcomes[0]
        self.assertEqual(outcome.first_relevant_rank, 1)
        self.assertEqual(
            outcome.metrics(1),
            {"recall": 1.0, "precision": 1.0, "hit": 1.0, "mrr": 1.0},
        )
        self.assertEqual(run.filter_violations, ())
        self.assertEqual(run.provenance_problems, ())

    def test_run_level_facts_come_from_the_retriever(self):
        questions = [_question("q1", "attendance", relevant_chunk_ids=("doc-a:c1",))]
        run = self._run(questions, {"attendance": [("doc-a:c1", 0.5)]})
        self.assertEqual(run.metric, "inner_product")
        self.assertEqual(run.vector_count, 2)
        self.assertEqual(run.model_id, "stub/model")
        self.assertEqual(run.canonical_chunk_count, 2)
        self.assertEqual(run.k_values, DEFAULT_K_VALUES)

    def test_a_returned_chunk_that_violates_the_filter_is_caught(self):
        questions = [
            _question("q1", "attendance", filters={"document_ids": ["doc-b"]},
                      relevant_chunk_ids=("doc-b:c1",))
        ]
        run = self._run(questions, {"attendance": [("doc-a:c1", 0.9)]})
        self.assertEqual(len(run.filter_violations), 1)
        self.assertIn("q1", run.filter_violations[0])

    def test_a_scheme_filter_does_not_match_an_unknown_scheme(self):
        questions = [_question("q1", "attendance", filters={"scheme": "2022"}, relevant_chunk_ids=("doc-a:c1",))]
        run = self._run(questions, {"attendance": [("doc-b:c1", 0.9)]})
        self.assertEqual(len(run.filter_violations), 1)

    def test_an_empty_filters_dict_never_violates(self):
        questions = [_question("q1", "attendance", filters=None, relevant_chunk_ids=("doc-b:c1",))]
        run = self._run(questions, {"attendance": [("doc-b:c1", 0.9)]})
        self.assertEqual(run.filter_violations, ())

    def test_an_empty_provenance_field_is_caught(self):
        broken = _stub_records()
        broken[0]["version_id"] = ""
        retriever = _StubRetriever({"attendance": [("doc-a:c1", 0.9)]}, broken)
        questions = [_question("q1", "attendance", relevant_chunk_ids=("doc-a:c1",))]
        run = evaluate_questions(
            questions, retriever, canonical_chunk_ids={record["chunk_id"] for record in broken}
        )
        self.assertTrue(any("version_id" in problem for problem in run.provenance_problems))

    def test_a_page_range_that_disagrees_with_the_cited_pages_is_caught(self):
        broken = _stub_records()
        broken[0]["page_start"], broken[0]["page_end"] = 1, 9
        retriever = _StubRetriever({"attendance": [("doc-a:c1", 0.9)]}, broken)
        questions = [_question("q1", "attendance", relevant_chunk_ids=("doc-a:c1",))]
        run = evaluate_questions(
            questions, retriever, canonical_chunk_ids={record["chunk_id"] for record in broken}
        )
        self.assertTrue(any("page range" in problem for problem in run.provenance_problems))

    def test_a_returned_chunk_absent_from_the_canonical_dataset_is_caught(self):
        questions = [_question("q1", "attendance", relevant_chunk_ids=("doc-a:c1",))]
        run = self._run(questions, {"attendance": [("doc-a:c1", 0.9)]})
        self.assertEqual(run.provenance_problems, ())

        retriever = _StubRetriever({"attendance": [("doc-a:c1", 0.9)]}, self.records)
        run = evaluate_questions(questions, retriever, canonical_chunk_ids={"doc-b:c1"})
        self.assertTrue(any("not in the canonical dataset" in problem for problem in run.provenance_problems))

    def test_an_unanswerable_question_is_reported_without_metrics(self):
        questions = [
            _question("q1", "quantum computing", "insufficient_evidence", relevant_chunk_ids=()),
            _question("q2", "attendance", "regulation", relevant_chunk_ids=("doc-a:c1",)),
        ]
        run = self._run(questions, {
            "quantum computing": [("doc-a:c1", 0.42)],
            "attendance": [("doc-a:c1", 0.9)],
        })
        unanswerable = [outcome for outcome in run.outcomes if not outcome.is_answerable]
        self.assertEqual(len(unanswerable), 1)
        self.assertTrue(unanswerable[0].retrieved)
        with self.assertRaises(MetricError):
            unanswerable[0].metrics(1)

    def test_aggregation_covers_only_answerable_questions(self):
        questions = [
            _question("q1", "one", "regulation", relevant_chunk_ids=("doc-a:c1",)),
            _question("q2", "two", "insufficient_evidence", relevant_chunk_ids=()),
        ]
        run = self._run(questions, {
            "one": [("doc-a:c1", 0.9)],
            "two": [("doc-b:c1", 0.3)],
        })
        table = metrics_table(run.outcomes, run.k_values)
        self.assertEqual(sorted(table), sorted(METRIC_NAMES))
        self.assertEqual(table["recall"][1], 1.0)
        groups = by_category(run.outcomes)
        self.assertEqual(groups["insufficient_evidence"][0].is_answerable, False)

    def test_a_question_set_with_no_answerable_question_aggregates_to_none(self):
        questions = [_question("q1", "quantum computing", "insufficient_evidence", relevant_chunk_ids=())]
        run = self._run(questions, {"quantum computing": [("doc-a:c1", 0.42)]})
        table = metrics_table(run.outcomes, run.k_values)
        for name in METRIC_NAMES:
            for k in run.k_values:
                self.assertIsNone(table[name][k])

    def test_no_k_values_is_refused(self):
        retriever = _StubRetriever({}, self.records)
        with self.assertRaises(ValueError):
            evaluate_questions([_question()], retriever, k_values=())

    def test_the_report_records_the_checks_and_the_definitions(self):
        questions = [
            _question("q1", "attendance", "regulation", relevant_chunk_ids=("doc-a:c1",)),
            _question("q2", "quantum computing", "insufficient_evidence", relevant_chunk_ids=()),
        ]
        run = self._run(questions, {
            "attendance": [("doc-a:c1", 0.9)],
            "quantum computing": [("doc-b:c1", 0.42)],
        })
        report = build_report(run, dataset_path=Path("questions.jsonl"))
        self.assertIn("# Retrieval Evaluation Report", report)
        self.assertIn("## 5. Filter correctness", report)
        self.assertIn("## 6. Provenance correctness", report)
        self.assertIn("0 violations", report)
        self.assertIn("0 problems", report)
        self.assertIn("Recall@k = |relevant ∩ retrieved[:k]| / |relevant|", report)
        self.assertIn("insufficient_evidence", report)


# --------------------------------------------------------------------------- #
# FAISS-backed evaluation over the synthetic corpus
# --------------------------------------------------------------------------- #


@unittest.skipIf(test_indexing._FAISS_ERROR is not None, test_indexing._FAISS_SKIP_REASON)
class EvaluationAgainstRealRetrieverTests(unittest.TestCase):
    """``evaluate_questions`` driving the real :class:`Retriever` over FAISS.

    The records use the real corpus's ``<document_id>:<hash>`` chunk-ID form,
    because the provenance check requires a chunk ID to be namespaced under its
    own document - an invariant the canonical dataset holds and this fixture
    must reproduce for the check to be meaningful.
    """

    def setUp(self):
        records = [
            test_indexing._record(
                "doc-a:c1", "database normalization third normal form",
                page_numbers=[1, 2], page_start=1, page_end=2,
            ),
            test_indexing._record(
                "doc-b:c1", "probability distributions and statistics",
                document_id="doc-b", version_id="vb", filename="b.pdf",
                scheme="2025", semester="3", page_numbers=[5], page_start=5, page_end=5,
            ),
            test_indexing._record(
                "doc-c:c1", "regulations attendance requirement",
                document_id="doc-c", version_id="vc", filename="c.pdf",
                document_type=REGULATION, scheme=None, semester=None, branch=None,
                page_numbers=[10], page_start=10, page_end=10, module=None, module_label=None,
            ),
        ]
        self.fixture = test_indexing._Fixture(records=records)
        self.addCleanup(self.fixture.close)
        self.fixture.build()
        from app.retrieval.search import Retriever

        self.retriever = Retriever(
            self.fixture.index_dir, self.fixture.canonical_dir, embedder=self.fixture.embedder
        )
        self.chunk_ids = {record["chunk_id"] for record in self.fixture.records}

    def test_filter_and_provenance_pass_on_the_real_index(self):
        questions = [
            _question("q1", "database normalization", "exact_term",
                      filters={"document_ids": ["doc-a"]}, relevant_chunk_ids=("doc-a:c1",)),
            _question("q2", "probability distributions", "semantic",
                      filters={"scheme": "2025"}, relevant_chunk_ids=("doc-b:c1",)),
            _question("q3", "regulations attendance", "regulation",
                      filters={"document_type": "regulation"}, relevant_chunk_ids=("doc-c:c1",)),
            _question("q4", "quantum computing", "insufficient_evidence", relevant_chunk_ids=()),
        ]
        run = evaluate_questions(
            questions, self.retriever, canonical_chunk_ids=self.chunk_ids
        )
        self.assertEqual(run.filter_violations, ())
        self.assertEqual(run.provenance_problems, ())
        self.assertEqual(run.vector_count, 3)
        self.assertEqual(run.metric, "inner_product")

    def test_a_relevant_chunk_really_is_ranked_first(self):
        questions = [
            _question("q1", "database normalization", "exact_term",
                      filters={"document_ids": ["doc-a"]}, relevant_chunk_ids=("doc-a:c1",))
        ]
        run = evaluate_questions(
            questions, self.retriever, canonical_chunk_ids=self.chunk_ids
        )
        self.assertEqual(run.outcomes[0].first_relevant_rank, 1)
        self.assertEqual(run.outcomes[0].metrics(1)["recall"], 1.0)

    def test_a_filtered_out_relevant_chunk_is_reported_as_a_miss(self):
        questions = [
            _question("q1", "database normalization", "exact_term",
                      filters={"document_ids": ["doc-b"]}, relevant_chunk_ids=("doc-a:c1",))
        ]
        run = evaluate_questions(
            questions, self.retriever, canonical_chunk_ids=self.chunk_ids
        )
        self.assertIsNone(run.outcomes[0].first_relevant_rank)
        self.assertEqual(run.outcomes[0].metrics(1)["recall"], 0.0)


# --------------------------------------------------------------------------- #
# The real dataset and artifacts
# --------------------------------------------------------------------------- #


@unittest.skipUnless(_CANONICAL_AVAILABLE, _CANONICAL_SKIP_REASON)
class RealDatasetBuildTests(unittest.TestCase):
    """The builder reproduces the shipped questions file from the real corpus."""

    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.records = read_canonical_dataset(CANONICAL_DIR)
        cls.questions = build_questions(cls.records)

    def test_every_label_exists_in_the_canonical_dataset(self):
        known = {record["chunk_id"] for record in self.records}
        self.assertEqual(validate_questions(self.questions, known_chunk_ids=known), [])

    def test_every_required_category_is_covered(self):
        covered = {question.category for question in self.questions}
        self.assertEqual(covered, set(CATEGORIES))

    def test_at_least_one_question_is_unanswerable(self):
        unanswerable = [question for question in self.questions if not question.is_answerable]
        self.assertTrue(unanswerable)
        for question in unanswerable:
            self.assertEqual(question.category, "insufficient_evidence")

    def test_the_build_is_deterministic(self):
        first = [question.to_record() for question in self.questions]
        second = [question.to_record() for question in build_questions(self.records)]
        self.assertEqual(first, second)

    def test_the_builder_reproduces_the_shipped_file_byte_for_byte(self):
        if not QUESTIONS_PATH.is_file():
            self.skipTest(_QUESTIONS_SKIP_REASON)
        with tempfile.TemporaryDirectory() as directory:
            rebuilt = Path(directory) / "questions.jsonl"
            write_questions(rebuilt, self.questions)
            self.assertEqual(rebuilt.read_bytes(), QUESTIONS_PATH.read_bytes())

    def test_relevance_labels_stay_out_of_the_production_artifacts(self):
        """A judgement must never leak into what a real query is served from."""
        for path in (CANONICAL_CHUNKS, INDEX_ENTRIES):
            if not path.is_file():
                self.skipTest(f"artifact is absent: {path}")
            with self.subTest(artifact=path.name):
                self.assertNotIn("relevant_chunk_ids", path.read_text(encoding="utf-8"))
        for line in QUESTIONS_PATH.read_text(encoding="utf-8").splitlines():
            self.assertEqual(
                sorted(json.loads(line)),
                sorted(["id", "query", "category", "filters", "relevant_chunk_ids", "note"]),
            )
            break


if __name__ == "__main__":
    unittest.main()
