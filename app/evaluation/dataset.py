"""The evaluation-question schema, its loader, and its validator.

An evaluation question is a query plus the chunks that genuinely answer it.
That relevance judgement is the whole point of the file: without it there is
nothing to measure the retriever against. The labels are kept in this dataset,
completely separate from the production index metadata, so a judgement about
what is relevant can never leak into the artifacts a real query is served from.

Record shape (one JSON object per line)::

    {
      "id": "q07",
      "query": "What does Module 4 of Software Engineering and Project Management cover?",
      "category": "module",
      "filters": {},
      "relevant_chunk_ids": ["vtu-2022-scheme-sem5-syllabus:..."],
      "note": "How the label was derived and where the answer sits."
    }

``filters`` is the metadata context the question is asked under, using the same
field names as :class:`app.retrieval.search.MetadataFilter` (``document_type``,
``scheme``, ``semester``, ``branch``, ``document_ids``). An empty ``filters``
means the question is asked with no context, which is how most questions are
asked.

``relevant_chunk_ids`` is empty for exactly one category,
``insufficient_evidence``: those queries have no answer in the indexed corpus,
and the point of measuring them is their scores, not their recall.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The categories the dataset is required to cover. ``insufficient_evidence`` is
#: the only one allowed to carry no relevant chunks.
CATEGORIES: tuple[str, ...] = (
    "syllabus_fact",
    "module",
    "scheme",
    "semester",
    "document_type",
    "regulation",
    "exact_term",
    "semantic",
    "insufficient_evidence",
)

#: The metadata filter fields a question may set, mirroring ``MetadataFilter``.
FILTER_KEYS: tuple[str, ...] = ("document_type", "scheme", "semester", "branch", "document_ids")

#: A category whose questions are expected to be unanswerable from the corpus.
UNANSWERABLE_CATEGORY = "insufficient_evidence"

#: Where the built dataset lives by default.
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "processed" / "evaluation" / "questions.jsonl"
)


class EvaluationDataError(ValueError):
    """The evaluation dataset is missing, malformed, or disagrees with the corpus."""


@dataclass(frozen=True)
class EvaluationQuestion:
    """One evaluation question and the chunks that answer it."""

    question_id: str
    query: str
    category: str
    filters: dict
    relevant_chunk_ids: tuple[str, ...]
    note: str = ""

    @property
    def is_answerable(self) -> bool:
        """True when the question has at least one judged-relevant chunk."""
        return bool(self.relevant_chunk_ids)

    def to_record(self) -> dict:
        """The JSON-serialisable form, written back by the builder."""
        return {
            "id": self.question_id,
            "query": self.query,
            "category": self.category,
            "filters": dict(self.filters),
            "relevant_chunk_ids": list(self.relevant_chunk_ids),
            "note": self.note,
        }


def _parse_record(record: dict, line_number: int) -> EvaluationQuestion:
    if not isinstance(record, dict):
        raise EvaluationDataError(f"line {line_number} is not a JSON object")
    for key in ("id", "query", "category", "relevant_chunk_ids"):
        if key not in record:
            raise EvaluationDataError(f"line {line_number} is missing {key!r}")
    return EvaluationQuestion(
        question_id=str(record["id"]),
        query=str(record["query"]),
        category=str(record["category"]),
        filters=dict(record.get("filters") or {}),
        relevant_chunk_ids=tuple(str(item) for item in record["relevant_chunk_ids"]),
        note=str(record.get("note", "")),
    )


def load_questions(path: Path = DEFAULT_QUESTIONS_PATH) -> list[EvaluationQuestion]:
    """Read the evaluation dataset from a JSONL file.

    Raises :class:`EvaluationDataError` for a missing file, an unreadable line,
    or an empty dataset, rather than returning a partial set that would silently
    lower the reported coverage.
    """
    path = Path(path)
    if not path.is_file():
        raise EvaluationDataError(f"evaluation dataset not found: {path}")
    questions = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationDataError(f"{path} line {line_number} is not valid JSON: {exc}") from exc
        questions.append(_parse_record(record, line_number))
    if not questions:
        raise EvaluationDataError(f"evaluation dataset {path} holds no questions")
    return questions


def validate_questions(
    questions: list[EvaluationQuestion],
    known_chunk_ids: set[str] | None = None,
) -> list[str]:
    """Check the dataset for the errors that would make a score meaningless.

    Every problem found is returned as a message, so a caller sees all of them
    at once. When ``known_chunk_ids`` is supplied, each labelled chunk must
    exist in the canonical dataset: a label naming a chunk that is not in the
    corpus would be a fabricated judgement.
    """
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_queries: set[str] = set()

    for question in questions:
        if question.question_id in seen_ids:
            problems.append(f"duplicate question id {question.question_id!r}")
        seen_ids.add(question.question_id)

        normalized = " ".join(question.query.split()).lower()
        if not normalized:
            problems.append(f"{question.question_id}: empty query")
        if normalized in seen_queries:
            problems.append(f"{question.question_id}: duplicate query text")
        seen_queries.add(normalized)

        if question.category not in CATEGORIES:
            problems.append(f"{question.question_id}: unknown category {question.category!r}")

        unknown = [key for key in question.filters if key not in FILTER_KEYS]
        if unknown:
            problems.append(f"{question.question_id}: unknown filter field(s) {unknown}")
        document_ids = question.filters.get("document_ids")
        if document_ids is not None and not isinstance(document_ids, (list, tuple)):
            problems.append(f"{question.question_id}: document_ids must be a list")

        expects_answer = question.category != UNANSWERABLE_CATEGORY
        if expects_answer and not question.relevant_chunk_ids:
            problems.append(
                f"{question.question_id}: category {question.category!r} must have relevant chunks"
            )
        if not expects_answer and question.relevant_chunk_ids:
            problems.append(
                f"{question.question_id}: {UNANSWERABLE_CATEGORY} must not have relevant chunks"
            )

        if len(set(question.relevant_chunk_ids)) != len(question.relevant_chunk_ids):
            problems.append(f"{question.question_id}: repeated relevant chunk id")

        if known_chunk_ids is not None:
            for chunk_id in question.relevant_chunk_ids:
                if chunk_id not in known_chunk_ids:
                    problems.append(
                        f"{question.question_id}: relevant chunk {chunk_id!r} is not in the canonical dataset"
                    )
    return problems


def write_questions(path: Path, questions: list[EvaluationQuestion]) -> None:
    """Write the dataset as JSONL, deterministically.

    Records keep the order given, and no timestamp is written, so the same
    specifications always produce byte-identical output.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for question in questions:
            handle.write(json.dumps(question.to_record(), ensure_ascii=False))
            handle.write("\n")
