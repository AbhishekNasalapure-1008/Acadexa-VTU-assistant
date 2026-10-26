"""Build the retrieval-evaluation dataset from the canonical chunk corpus.

The dataset exists to answer one question that nothing in the project could
answer before: how good is the retriever? That needs queries with judged-
relevant answers, and those judgements must be grounded in the actual corpus,
not invented.

Every label here is derived by a **selector** that runs against the real
canonical records:

* ``header``    - the first chunk of a subject, which holds the course code,
                  semester, marks and credit lines.
* ``module``    - the chunk(s) the document itself marks as ``MODULE-N``.
* ``containing``- every chunk whose text contains a given phrase, matched on
                  whitespace-normalised, lower-cased text.
* ``by_ids``    - an explicit, previously verified chunk ID (used only where a
                  question needs an exact, narrow label).

A selector that matches nothing raises, so a stale phrase or a renamed chunk
fails the build instead of silently producing an unanswerable question. The
labels themselves are written to their own artifact
(``data/processed/evaluation/questions.jsonl``) and never into the index or the
canonical metadata, so a judgement about relevance cannot leak into what a real
query is served from.

Scope boundaries: no Gemini, no generation, no refusal logic, no Flask, no
frontend, no network. This module only reads ``data/processed/canonical``.

Not every document yields every category. The syllabus documents establish
course structure (course code, module, semester, credits); the two regulation
documents establish award rules. A category is only used where the corpus
genuinely supports it, which is why the regulation questions carry a
``document_ids`` filter and the syllabus questions a ``document_ids`` or
``scheme``/``semester`` filter.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.evaluation.dataset import (
    DEFAULT_QUESTIONS_PATH,
    EvaluationDataError,
    EvaluationQuestion,
    validate_questions,
    write_questions,
)
from app.ingestion.canonical import CANONICAL_DOCUMENTS, read_canonical_dataset

#: The repository root, used to resolve the default artifact locations.
ROOT = Path(__file__).resolve().parents[2]

#: Where the canonical dataset this builder reads lives.
DEFAULT_CANONICAL_DIR = ROOT / "data" / "processed" / "canonical"

#: Document IDs come from the canonical document table, so there is exactly one
#: place that defines them.
_DOCUMENT_IDS = {document.key: document.document_id for document in CANONICAL_DOCUMENTS}
SEM3_2022 = _DOCUMENT_IDS["2022-cse-3rd"]
SEM5_2022 = _DOCUMENT_IDS["2022-cse-5th"]
SEM3_2025 = _DOCUMENT_IDS["2025-cse-3rd"]
REG_2022 = _DOCUMENT_IDS["2022-regulations"]
REG_2025 = _DOCUMENT_IDS["2025-regulations"]


class Corpus:
    """A read-only view of the canonical chunks with grounding selectors.

    The selectors are the only way this module produces a label. They read the
    real records, so a label cannot name a chunk that does not exist, and they
    return chunk IDs in the canonical file order, so the dataset is stable.
    """

    def __init__(self, records) -> None:
        self._records = [dict(record) for record in records]
        self._order: dict[str, int] = {}
        for record in self._records:
            chunk_id = str(record.get("chunk_id"))
            if not chunk_id or chunk_id == "None":
                raise EvaluationDataError("a canonical record has no chunk_id")
            if chunk_id in self._order:
                raise EvaluationDataError(f"duplicate chunk id in the canonical dataset: {chunk_id}")
            self._order[chunk_id] = int(record.get("chunk_index", 0))

    def chunk_ids(self) -> list[str]:
        """Every chunk ID, in canonical file order."""
        return sorted(self._order, key=lambda chunk_id: (self._order[chunk_id], chunk_id))

    def _order_ids(self, records) -> list[str]:
        rows = sorted(records, key=lambda r: (int(r.get("chunk_index", 0)), str(r.get("chunk_id"))))
        return [str(row["chunk_id"]) for row in rows]

    def _select(self, predicate, description: str) -> list[str]:
        rows = [record for record in self._records if predicate(record)]
        if not rows:
            raise EvaluationDataError(f"selector matched no chunk: {description}")
        return self._order_ids(rows)

    def header(self, document_id: str, subject_code: str) -> list[str]:
        """The subject-header chunk: the subject's first chunk by document order.

        The header carries the course code, semester, marks and credit lines
        the syllabus facts are read from.
        """
        return self._select(
            lambda r: r.get("document_id") == document_id and r.get("subject_code") == subject_code,
            f"header of {subject_code} in {document_id}",
        )[:1]

    def module(self, document_id: str, subject_code: str, module_number: int) -> list[str]:
        """The chunk(s) the document marks as ``MODULE-<n>`` for a subject."""
        return self._select(
            lambda r: (
                r.get("document_id") == document_id
                and r.get("subject_code") == subject_code
                and r.get("module") == module_number
            ),
            f"module {module_number} of {subject_code} in {document_id}",
        )

    def containing(
        self,
        phrase: str,
        *,
        document_id: str | None = None,
        subject_code: str | None = None,
    ) -> list[str]:
        """Every chunk whose normalised text contains ``phrase``.

        Matching is on whitespace-normalised, lower-cased text so a phrase that
        wraps across a PDF line break still matches.
        """
        needle = " ".join(phrase.lower().split())

        def predicate(record) -> bool:
            if document_id is not None and record.get("document_id") != document_id:
                return False
            if subject_code is not None and record.get("subject_code") != subject_code:
                return False
            haystack = " ".join(str(record.get("chunk_text", "")).lower().split())
            return needle in haystack

        scope = document_id or subject_code or "the corpus"
        return self._select(predicate, f"{phrase!r} in {scope}")

    def by_ids(self, *chunk_ids: str) -> list[str]:
        """Explicit, already-verified chunk IDs, checked against the corpus."""
        missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in self._order]
        if missing:
            raise EvaluationDataError(f"labelled chunk(s) absent from the corpus: {missing}")
        return list(chunk_ids)


#: A selector takes the corpus and returns the judged-relevant chunk IDs.
Selector = Callable[[Corpus], list[str]]


@dataclass(frozen=True)
class _Spec:
    """One question before its labels are resolved."""

    question_id: str
    query: str
    category: str
    note: str
    selector: Selector | None = None
    filters: dict = field(default_factory=dict)


def _doc_ids(*document_ids: str) -> dict:
    return {"document_ids": list(document_ids)}


def _specs() -> list[_Spec]:
    """The question set, in a fixed order, with grounded label selectors."""
    return [
        # ---------------------------------------------------------------- facts
        _Spec(
            "q-syl-01",
            "What are the CIE and SEE marks for the course BCS301 Mathematics for Computer Science?",
            "syllabus_fact",
            "The subject header lists 'CIE Marks 50' and 'SEE Marks 50'.",
            lambda c: c.header(SEM3_2022, "BCS301"),
            _doc_ids(SEM3_2022),
        ),
        _Spec(
            "q-syl-02",
            "How many credits does the course BCS501 Software Engineering and Project Management carry?",
            "syllabus_fact",
            "The subject header states 'Credits 03'.",
            lambda c: c.header(SEM5_2022, "BCS501"),
            _doc_ids(SEM5_2022),
        ),
        _Spec(
            "q-syl-03",
            "What is the course code for Digital Design and Computer Organization in the 2025 scheme?",
            "syllabus_fact",
            "Subject header of 1BCS303; the 2025 header spells out 'Scheme 2025'.",
            lambda c: c.header(SEM3_2025, "1BCS303"),
            _doc_ids(SEM3_2025),
        ),
        _Spec(
            "q-syl-04",
            "What is the duration of the semester end examination in hours for the course 1BMATCS301?",
            "syllabus_fact",
            "The subject header states 'Exam Hours 03'.",
            lambda c: c.header(SEM3_2025, "1BMATCS301"),
            _doc_ids(SEM3_2025),
        ),
        _Spec(
            "q-syl-05",
            "Which semester does the course BCS304 belong to?",
            "syllabus_fact",
            "The subject header states 'Semester 3'.",
            lambda c: c.header(SEM3_2022, "BCS304"),
            _doc_ids(SEM3_2022),
        ),
        _Spec(
            "q-syl-06",
            "What is the total number of marks prescribed for the course BCS502 Computer Networks?",
            "syllabus_fact",
            "The subject header states 'Total Marks 100'.",
            lambda c: c.header(SEM5_2022, "BCS502"),
            _doc_ids(SEM5_2022),
        ),
        _Spec(
            "q-syl-07",
            "What is the teaching hours per week pattern for the course BCS403?",
            "syllabus_fact",
            "The subject header lists the 'Teaching Hours/Week (L:T:P: S)' pattern.",
            lambda c: c.header(SEM3_2022, "BCS403"),
            _doc_ids(SEM3_2022),
        ),
        _Spec(
            "q-syl-08",
            "What are the CIE and SEE marks for the course 1BCS305 Data Structures and Applications?",
            "syllabus_fact",
            "Subject header of 1BCS305 in the 2025 syllabus.",
            lambda c: c.header(SEM3_2025, "1BCS305"),
            _doc_ids(SEM3_2025),
        ),
        # -------------------------------------------------------------- modules
        _Spec(
            "q-mod-01",
            "What topics are covered in Module 4 of the Software Engineering and Project Management course?",
            "module",
            "The MODULE-4 chunk of BCS501 (Introduction to Project Management).",
            lambda c: c.module(SEM5_2022, "BCS501", 4),
        ),
        _Spec(
            "q-mod-02",
            "What does Module 5 of the Theory of Computation course cover?",
            "module",
            "The MODULE-5 chunk of BCS503 (Turing machines).",
            lambda c: c.module(SEM5_2022, "BCS503", 5),
        ),
        _Spec(
            "q-mod-03",
            "What is taught in Module 3 of Computer Networks?",
            "module",
            "The MODULE-3 chunk of BCS502.",
            lambda c: c.module(SEM5_2022, "BCS502", 3),
        ),
        _Spec(
            "q-mod-04",
            "What does Module 3 of Artificial Intelligence cover?",
            "module",
            "The MODULE-3 chunk of BCS515B (informed search, logical agents).",
            lambda c: c.module(SEM5_2022, "BCS515B", 3),
        ),
        _Spec(
            "q-mod-05",
            "What topics are listed in Module 2 of the Database Management System course?",
            "module",
            "The MODULE-2 chunk of BCS403.",
            lambda c: c.module(SEM3_2022, "BCS403", 2),
        ),
        _Spec(
            "q-mod-06",
            "What is covered in Module 3 of Analysis and Design of Algorithms?",
            "module",
            "The MODULE-3 chunk of BCS401.",
            lambda c: c.module(SEM3_2022, "BCS401", 3),
        ),
        _Spec(
            "q-mod-07",
            "What does Module 2 of Probability, Distributions and Statistics cover?",
            "module",
            "The MODULE-2 chunk of 1BMATCS301.",
            lambda c: c.module(SEM3_2025, "1BMATCS301", 2),
        ),
        _Spec(
            "q-mod-08",
            "What topics are covered in Module 4 of Data Structures and Applications in the 2025 scheme?",
            "module",
            "The MODULE-4 chunk of 1BCS305 (trees). Filtered because the subject also "
            "appears in the 2022 syllabus as BCS304.",
            lambda c: c.module(SEM3_2025, "1BCS305", 4),
            {"document_ids": [SEM3_2025]},
        ),
        _Spec(
            "q-mod-09",
            "What does Module 2 of Object Oriented Programming with Java cover in the 2025 scheme?",
            "module",
            "The MODULE-2 chunk of 1BCS302. Filtered because a same-named subject exists "
            "in the 2022 syllabus as BCS306A.",
            lambda c: c.module(SEM3_2025, "1BCS302", 2),
            {"document_ids": [SEM3_2025]},
        ),
        _Spec(
            "q-mod-10",
            "What is covered in Module 3 of Operating Systems in the 2022 scheme?",
            "module",
            "The MODULE-3 chunk of BCS303. Filtered because Operating Systems is also a "
            "2025-scheme course (1BCS304).",
            lambda c: c.module(SEM3_2022, "BCS303", 3),
            {"document_ids": [SEM3_2022]},
        ),
        # --------------------------------------------------------------- scheme
        _Spec(
            "q-sch-01",
            "Which scheme does the course with code 1BCS304 belong to?",
            "scheme",
            "The 2025 subject header states 'Scheme 2025'.",
            lambda c: c.header(SEM3_2025, "1BCS304"),
            {"scheme": "2025"},
        ),
        _Spec(
            "q-sch-02",
            "Under the 2022 scheme, what is the course code for Theory of Computation?",
            "scheme",
            "The 2022 subject header states 'Course Code BCS503'.",
            lambda c: c.header(SEM5_2022, "BCS503"),
            {"scheme": "2022"},
        ),
        _Spec(
            "q-sch-03",
            "What is the course code for Operating Systems under the 2025 scheme?",
            "scheme",
            "The 2025 subject header states 'Course Code 1BCS304'.",
            lambda c: c.header(SEM3_2025, "1BCS304"),
            {"scheme": "2025"},
        ),
        _Spec(
            "q-sch-04",
            "What is the course code for Operating Systems under the 2022 scheme?",
            "scheme",
            "The 2022 subject header states 'Course Code BCS303'.",
            lambda c: c.header(SEM3_2022, "BCS303"),
            {"scheme": "2022"},
        ),
        _Spec(
            "q-sch-05",
            "Under the 2025 scheme and the 3rd semester, what is the course code for Data Structures and Applications?",
            "scheme",
            "The 2025 subject header states 'Course Code 1BCS305' and 'Semester 3'.",
            lambda c: c.header(SEM3_2025, "1BCS305"),
            {"scheme": "2025", "semester": "3"},
        ),
        # ------------------------------------------------------------- semester
        _Spec(
            "q-smt-01",
            "Which semester is the course BCS405A Discrete Mathematical Structures offered in?",
            "semester",
            "The subject header states 'Semester IV'.",
            lambda c: c.header(SEM3_2022, "BCS405A"),
            _doc_ids(SEM3_2022),
        ),
        _Spec(
            "q-smt-02",
            "In which semester is the course 1BAIL307A Exploratory Data Analysis offered?",
            "semester",
            "The subject header states 'Semester 3'.",
            lambda c: c.header(SEM3_2025, "1BAIL307A"),
            _doc_ids(SEM3_2025),
        ),
        _Spec(
            "q-smt-03",
            "Which semester does the course 1BCP308 Community Project belong to?",
            "semester",
            "The subject header states 'Semester 3'.",
            lambda c: c.header(SEM3_2025, "1BCP308"),
            {"scheme": "2025", "semester": "3"},
        ),
        _Spec(
            "q-smt-04",
            "What is the semester of the course BCSL456D Technical Writing using LaTeX?",
            "semester",
            "The subject header states 'Semester 4'.",
            lambda c: c.header(SEM3_2022, "BCSL456D"),
            _doc_ids(SEM3_2022),
        ),
        _Spec(
            "q-smt-05",
            "Is the course BCS306A Object Oriented Programming with JAVA part of semester 3?",
            "semester",
            "The subject header states 'Semester 3'.",
            lambda c: c.header(SEM3_2022, "BCS306A"),
            _doc_ids(SEM3_2022),
        ),
        # -------------------------------------------------------- document type
        _Spec(
            "q-dty-01",
            "In the regulations, what percentage of the SEE maximum marks must a student secure to pass a course in the 2025 regulations?",
            "document_type",
            "The 2025 regulation clause 25OB12.0 states 'a minimum of 35 % of the prescribed "
            "maximum marks of the SEE'.",
            lambda c: c.containing("minimum of 35 %", document_id=REG_2025),
            {"document_type": "regulation"},
        ),
        _Spec(
            "q-dty-02",
            "In the regulations, what is the maximum attendance shortage that may be condoned in the 2025 regulations?",
            "document_type",
            "The 2025 regulation states a shortage 'up to a maximum of 10 %' may be condoned.",
            lambda c: c.containing("condoned", document_id=REG_2025),
            {"document_type": "regulation"},
        ),
        _Spec(
            "q-dty-03",
            "In the syllabus documents, which course carries the code BCS515B?",
            "document_type",
            "The 2022 semester-5 subject header of BCS515B (Artificial Intelligence).",
            lambda c: c.header(SEM5_2022, "BCS515B"),
            {"document_type": "syllabus"},
        ),
        _Spec(
            "q-dty-04",
            "In the syllabus documents, what is the course code for the 3rd semester Probability, Distributions and Statistics course?",
            "document_type",
            "The 2025 semester-3 subject header of 1BMATCS301.",
            lambda c: c.header(SEM3_2025, "1BMATCS301"),
            {"document_type": "syllabus"},
        ),
        _Spec(
            "q-dty-05",
            "In the regulations, what is the minimum CIE percentage required to become eligible for the SEE?",
            "document_type",
            "The 2025 regulation states 'a minimum of 40 % of the total prescribed CIE marks'.",
            lambda c: c.containing("minimum of 40 %", document_id=REG_2025),
            {"document_type": "regulation"},
        ),
        # ----------------------------------------------------------- regulation
        _Spec(
            "q-reg-01",
            "Under the 2022 regulations, what attendance must a student maintain in each registered course?",
            "regulation",
            "Both chunks state the 85 % attendance requirement; the second also introduces "
            "the condonation clause.",
            lambda c: c.containing("85%", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-reg-02",
            "Under the 2022 regulations, on what grounds may a shortage of attendance be condoned?",
            "regulation",
            "The condonation clause lists medical grounds and NSS/NCC/sports representation.",
            lambda c: c.containing("condoned", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-reg-03",
            "Under the 2022 regulations, what is the maximum duration for lateral entry students to complete the programme?",
            "regulation",
            "The clause states lateral entry students must complete within six academic years.",
            lambda c: c.containing("six academic years", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-reg-04",
            "Under the 2022 regulations, what happens if a student does not complete the mandatory internship?",
            "regulation",
            "The clause states non-completion of the internship is a failure in that course.",
            lambda c: c.containing("Noncompliance of Internship", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-reg-05",
            "Under the 2025 regulations, what is the minimum passing mark in the semester end examination?",
            "regulation",
            "Clause 25OB12.0 states a minimum of 35 % of the prescribed SEE maximum marks.",
            lambda c: c.containing("minimum of 35 %", document_id=REG_2025),
            _doc_ids(REG_2025),
        ),
        _Spec(
            "q-reg-06",
            "Under the 2025 regulations, what is the minimum CGPA required for the award of the degree?",
            "regulation",
            "Clause 25OB13.0 states a CGPA of 4 or more is required. The label is the clause "
            "itself; the phrase also occurs in the contents listing, which is not evidence, so "
            "an exact ID is used instead of a phrase selector.",
            lambda c: c.by_ids("vtu-2025-regulations-be-btech:8323e40b8bf8400e"),
            _doc_ids(REG_2025),
        ),
        _Spec(
            "q-reg-07",
            "Under the 2022 regulations, how is the CGPA converted into a percentage of marks?",
            "regulation",
            "The clause gives the conversion formula M = CGPA Earned x 10.",
            lambda c: c.containing("Conversions of CGPA into Percentage", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        # ------------------------------------------------------------ exact term
        _Spec(
            "q-ext-01",
            "Where is the Pumping Lemma for Context-Free Languages covered?",
            "exact_term",
            "The phrase occurs in exactly one chunk: MODULE-4 of BCS503.",
            lambda c: c.containing("Pumping Lemma for Context-Free Languages", document_id=SEM5_2022),
        ),
        _Spec(
            "q-ext-02",
            "What is Agility according to the agile development module?",
            "exact_term",
            "The MODULE-3 chunk of BCS501 opens with 'Agile Development: What is Agility?'.",
            lambda c: c.containing("What is Agility?", document_id=SEM5_2022),
        ),
        _Spec(
            "q-ext-03",
            "What does the syllabus state about heuristic functions?",
            "exact_term",
            "The phrase occurs in the MODULE-3 chunk of BCS515B.",
            lambda c: c.containing("Heuristic functions", document_id=SEM5_2022),
        ),
        _Spec(
            "q-ext-04",
            "What is meant by noncompliance of internship?",
            "exact_term",
            "The heading 'Noncompliance of Internship' occurs in one 2022 regulation chunk.",
            lambda c: c.containing("Noncompliance of Internship", document_id=REG_2022),
        ),
        _Spec(
            "q-ext-05",
            "Where is Class Equivalence defined in the 2022 regulations?",
            "exact_term",
            "Two 2022 regulation chunks carry the 'Class Equivalence' heading.",
            lambda c: c.containing("Class Equivalence", document_id=REG_2022),
        ),
        _Spec(
            "q-ext-06",
            "What does the 2025 syllabus say about Circular Queues?",
            "exact_term",
            "Filtered to the 2025 syllabus because the phrase also occurs in the 2022 BCS304 module.",
            lambda c: c.containing("Circular Queues", document_id=SEM3_2025),
        ),
        # -------------------------------------------------------------- semantic
        _Spec(
            "q-sem-01",
            "What happens to a student who never completes the compulsory industry training?",
            "semantic",
            "Paraphrase of the 'Noncompliance of Internship' clause; the query avoids the "
            "words 'internship' and 'noncompliance'.",
            lambda c: c.containing("Noncompliance of Internship", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-sem-02",
            "How is a shortfall of classes treated when a student has a serious medical problem?",
            "semantic",
            "Paraphrase of the 2025 condonation clause (medical reasons).",
            lambda c: c.containing("condoned", document_id=REG_2025),
            _doc_ids(REG_2025),
        ),
        _Spec(
            "q-sem-03",
            "What is the longest time a diploma holder who joins the B.Tech programme directly may take to finish the degree?",
            "semantic",
            "Paraphrase of the lateral-entry six-academic-years clause.",
            lambda c: c.containing("six academic years", document_id=REG_2022),
            _doc_ids(REG_2022),
        ),
        _Spec(
            "q-sem-04",
            "What happens to a student who does not secure the required internal marks in an integrated course?",
            "semantic",
            "Paraphrase of the IPCC clause: such a student 'shall not be permitted to appear for SEE'.",
            lambda c: c.containing("shall not be permitted to appear for SEE", document_id=REG_2025),
            _doc_ids(REG_2025),
        ),
        _Spec(
            "q-sem-05",
            "What overall score, combining internal and external assessment, must a student reach to clear a course in 2025?",
            "semantic",
            "Paraphrase of the clause requiring a combined CIE and SEE total of at least 40 out of 100.",
            lambda c: c.containing("combined total of CIE and SEE", document_id=REG_2025),
            _doc_ids(REG_2025),
        ),
        _Spec(
            "q-sem-06",
            "How does the university decide the final class categories from a graduate's overall percentage of marks?",
            "semantic",
            "The four class bands (FCD, FC, SC, P) are split across three 2022 regulation chunks.",
            lambda c: c.by_ids(
                "vtu-2022-regulations-be-btech:25a3c40d31f89f7a",
                "vtu-2022-regulations-be-btech:fe0a85dd2d20ffbc",
                "vtu-2022-regulations-be-btech:ac1241262c11d6a9",
            ),
            _doc_ids(REG_2022),
        ),
        # ------------------------------------------------- insufficient evidence
        _Spec(
            "q-uns-01",
            "What are the details of the quantum computing elective offered in the 8th semester?",
            "insufficient_evidence",
            "No chunk in the corpus mentions quantum computing.",
        ),
        _Spec(
            "q-uns-02",
            "What are the eligibility criteria for the MBA programme?",
            "insufficient_evidence",
            "The corpus covers B.E./B.Tech. only; no MBA programme is described.",
        ),
        _Spec(
            "q-uns-03",
            "How can a student obtain a bus pass from the university?",
            "insufficient_evidence",
            "No chunk describes a bus pass process.",
        ),
        _Spec(
            "q-uns-04",
            "How much is the annual tuition charged for the B.E. programme?",
            "insufficient_evidence",
            "No chunk states a tuition amount; the word 'tuition' does not occur.",
        ),
        _Spec(
            "q-uns-05",
            "Does the university reserve seats for students from an agriculture background?",
            "insufficient_evidence",
            "No chunk mentions agriculture or an agriculture quota.",
        ),
        _Spec(
            "q-uns-06",
            "Which companies recruited students in the campus placement drive?",
            "insufficient_evidence",
            "No chunk lists recruiting companies.",
        ),
    ]


def build_questions(records) -> list[EvaluationQuestion]:
    """Resolve the spec table against the canonical records.

    Raises :class:`EvaluationDataError` when a selector matches nothing or when
    the resulting dataset fails validation, so a broken build is loud.
    """
    corpus = Corpus(records)
    questions = [
        EvaluationQuestion(
            question_id=spec.question_id,
            query=spec.query,
            category=spec.category,
            filters=dict(spec.filters),
            relevant_chunk_ids=tuple(spec.selector(corpus)) if spec.selector else (),
            note=spec.note,
        )
        for spec in _specs()
    ]
    problems = validate_questions(questions, known_chunk_ids=set(corpus.chunk_ids()))
    if problems:
        raise EvaluationDataError("built dataset is invalid:\n  " + "\n  ".join(problems))
    return questions


def main(argv: list[str] | None = None) -> int:
    """Build the dataset from the on-disk canonical chunks and write it out."""
    parser = argparse.ArgumentParser(
        description="Build the retrieval-evaluation dataset from the canonical chunks."
    )
    parser.add_argument("--canonical-dir", default=str(DEFAULT_CANONICAL_DIR))
    parser.add_argument("--out", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument(
        "--show",
        action="store_true",
        help="print each question with its resolved labels",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _manifest, records = read_canonical_dataset(Path(args.canonical_dir))
    questions = build_questions(records)
    write_questions(Path(args.out), questions)

    print(f"canonical chunks: {len(records)}")
    print(f"questions written: {len(questions)} -> {args.out}")
    if args.show:
        for question in questions:
            labels = ", ".join(chunk_id.split(":")[1] for chunk_id in question.relevant_chunk_ids)
            print(f"  {question.question_id} [{question.category}] {labels or '-'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
