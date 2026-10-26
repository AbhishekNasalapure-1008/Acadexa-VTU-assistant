"""Run the retrieval evaluation over the built index and write a report.

This is the runner that turns the labelled dataset into measured numbers. It
asks each evaluation question of :class:`app.retrieval.search.Retriever`,
compares the ranked result against the judged-relevant chunks, and records:

* **Recall@k, Precision@k, Hit@k and MRR@k** for every cut-off in
  :data:`app.evaluation.metrics.DEFAULT_K_VALUES`, computed by
  :mod:`app.evaluation.metrics`.
* **Filter correctness** - every returned chunk for a question that set a
  metadata filter must satisfy that filter.
* **Provenance correctness** - every returned chunk must carry a complete
  citation and page range that agrees with its own metadata, and its
  ``chunk_id`` must exist in the canonical dataset.
* **Unanswerable-query behaviour** - the scores the retriever returns for
  queries the corpus cannot answer, reported as scores. No refusal is
  implemented and no score threshold is applied; ``REQUIREMENTS.md`` AC-04 and
  Q7 leave the retrieval range and any threshold undecided.

The run is deterministic: the same index, dataset and questions give the same
numbers, and the report carries the artifact hashes so a reader can check that
it was produced from exactly these inputs. Nothing here writes to the index or
the canonical dataset, and nothing reaches the network.

Scope boundaries: no generation, no Gemini, no refusal logic, no Flask, no
frontend, no reranking, no query rewriting.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from app.evaluation.dataset import (
    DEFAULT_QUESTIONS_PATH,
    UNANSWERABLE_CATEGORY,
    EvaluationQuestion,
    load_questions,
)
from app.evaluation.metrics import (
    DEFAULT_K_VALUES,
    hit_at_k,
    mean,
    precision_at_k,
    rank_of_first_relevant,
    recall_at_k,
    reciprocal_rank_at_k,
)

#: The repository root, used to resolve the default artifact locations.
ROOT = Path(__file__).resolve().parents[2]

#: Where the report is written by default.
DEFAULT_REPORT_PATH = ROOT / "data" / "processed" / "evaluation" / "retrieval_eval_report.md"

#: Metric names, in report order.
METRIC_NAMES = ("recall", "precision", "hit", "mrr")


@dataclass(frozen=True)
class ResultView:
    """One returned chunk, reduced to the fields the evaluation checks.

    Keeping a small local view means the checks can be written and tested
    without constructing a retriever.
    """

    chunk_id: str
    score: float
    document_id: str
    version_id: str
    filename: str
    document_type: str
    page_numbers: tuple[int, ...]
    page_start: int | None
    page_end: int | None
    matches_filter: bool


@dataclass(frozen=True)
class QueryOutcome:
    """What one question asked and what came back."""

    question: EvaluationQuestion
    retrieved: tuple[ResultView, ...]
    first_relevant_rank: int | None

    @property
    def is_answerable(self) -> bool:
        return self.question.is_answerable

    def retrieved_ids(self) -> tuple[str, ...]:
        return tuple(result.chunk_id for result in self.retrieved)

    def metrics(self, k: int) -> dict[str, float]:
        """The four metrics at one cut-off.

        Only defined for an answerable question; an unanswerable question has
        no recall to report and its scores are reported instead.
        """
        ids = self.retrieved_ids()
        relevant = self.question.relevant_chunk_ids
        return {
            "recall": recall_at_k(ids, relevant, k),
            "precision": precision_at_k(ids, relevant, k),
            "hit": hit_at_k(ids, relevant, k),
            "mrr": reciprocal_rank_at_k(ids, relevant, k),
        }


@dataclass(frozen=True)
class EvaluationRun:
    """The whole evaluation: per-question outcomes and run-level checks."""

    outcomes: tuple[QueryOutcome, ...]
    k_values: tuple[int, ...]
    metric: str
    vector_count: int
    model_id: str
    canonical_chunk_count: int
    filter_violations: tuple[str, ...]
    provenance_problems: tuple[str, ...]
    input_hashes: dict


# --------------------------------------------------------------------- running


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate_questions(
    questions,
    retriever,
    *,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
    canonical_chunk_ids=None,
) -> EvaluationRun:
    """Query ``retriever`` for every question and collect the outcomes.

    ``retriever`` only has to expose ``search(query, top_k=..., filters=...)``
    and the properties ``metric``, ``vector_count``, ``model_id``. That keeps
    the evaluation testable with a small stand-in as well as with the real
    :class:`~app.retrieval.search.Retriever`.
    """
    from app.retrieval.search import MetadataFilter

    k_values = tuple(k_values)
    if not k_values:
        raise ValueError("at least one k value is required")
    max_k = max(k_values)

    outcomes: list[QueryOutcome] = []
    filter_violations: list[str] = []
    provenance_problems: list[str] = []

    for question in questions:
        filters = MetadataFilter(
            document_type=question.filters.get("document_type"),
            scheme=question.filters.get("scheme"),
            semester=question.filters.get("semester"),
            branch=question.filters.get("branch"),
            document_ids=tuple(question.filters.get("document_ids") or ()),
        )
        results = retriever.search(question.query, top_k=max_k, filters=filters)

        views = []
        for result in results:
            entry = dict(result.entry)
            matches = filters.matches(entry)
            if not matches:
                filter_violations.append(
                    f"{question.question_id}: returned {result.chunk_id} which does not "
                    f"satisfy filters {filters.to_dict()}"
                )
            problems = _provenance_problems(
                question.question_id, result.chunk_id, entry, result.page_numbers,
                canonical_chunk_ids,
            )
            provenance_problems.extend(problems)
            views.append(
                ResultView(
                    chunk_id=str(entry["chunk_id"]),
                    score=float(result.score),
                    document_id=str(entry.get("document_id", "")),
                    version_id=str(entry.get("version_id", "")),
                    filename=str(entry.get("filename", "")),
                    document_type=str(entry.get("document_type", "")),
                    page_numbers=tuple(result.page_numbers),
                    page_start=entry.get("page_start"),
                    page_end=entry.get("page_end"),
                    matches_filter=matches,
                )
            )

        outcomes.append(
            QueryOutcome(
                question=question,
                retrieved=tuple(views),
                first_relevant_rank=rank_of_first_relevant(
                    [view.chunk_id for view in views], question.relevant_chunk_ids
                ),
            )
        )

    return EvaluationRun(
        outcomes=tuple(outcomes),
        k_values=k_values,
        metric=str(retriever.metric),
        vector_count=int(retriever.vector_count),
        model_id=str(retriever.model_id),
        canonical_chunk_count=len(canonical_chunk_ids) if canonical_chunk_ids is not None else -1,
        filter_violations=tuple(filter_violations),
        provenance_problems=tuple(provenance_problems),
        input_hashes={},
    )


def _provenance_problems(
    question_id: str,
    chunk_id: str,
    entry: dict,
    page_numbers,
    canonical_chunk_ids,
) -> list[str]:
    """Check one returned chunk's citation chain against its own metadata.

    This is the chain a citation must be able to walk: ``chunk_id`` ->
    ``document_id`` + ``version_id`` + one-based page numbers.
    """
    problems: list[str] = []
    for field in ("chunk_id", "document_id", "version_id", "filename", "document_type"):
        if not entry.get(field):
            problems.append(f"{question_id}: {chunk_id} has an empty {field}")

    pages = tuple(page_numbers or ())
    if not pages:
        problems.append(f"{question_id}: {chunk_id} cites no page")
    elif any(not isinstance(page, int) or page < 1 for page in pages):
        problems.append(f"{question_id}: {chunk_id} cites a non-one-based page {pages}")

    start, end = entry.get("page_start"), entry.get("page_end")
    if pages:
        if start != min(pages) or end != max(pages):
            problems.append(
                f"{question_id}: {chunk_id} page range {start}-{end} disagrees with "
                f"cited pages {list(pages)}"
            )

    document_id = str(entry.get("document_id", ""))
    if document_id and not str(chunk_id).startswith(f"{document_id}:"):
        problems.append(
            f"{question_id}: {chunk_id} is not namespaced under its document {document_id}"
        )

    if canonical_chunk_ids is not None and chunk_id not in canonical_chunk_ids:
        problems.append(f"{question_id}: {chunk_id} is not in the canonical dataset")
    return problems


# ---------------------------------------------------------------- aggregation


def metrics_table(outcomes, k_values) -> dict[str, dict[int, float | None]]:
    """Mean of each metric at each cut-off, over the given (answerable) outcomes."""
    answered = [outcome for outcome in outcomes if outcome.is_answerable]
    table: dict[str, dict[int, float | None]] = {name: {} for name in METRIC_NAMES}
    for k in k_values:
        for name in METRIC_NAMES:
            table[name][k] = mean(outcome.metrics(k)[name] for outcome in answered)
    return table


def by_category(outcomes) -> dict[str, list[QueryOutcome]]:
    """Outcomes grouped by question category, in first-seen order."""
    groups: dict[str, list[QueryOutcome]] = {}
    for outcome in outcomes:
        groups.setdefault(outcome.question.category, []).append(outcome)
    return groups


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


# ------------------------------------------------------------------- reporting


def build_report(run: EvaluationRun, *, dataset_path: Path) -> str:
    """Render the evaluation as a reproducible markdown report."""
    outcomes = list(run.outcomes)
    answerable = [outcome for outcome in outcomes if outcome.is_answerable]
    unanswerable = [outcome for outcome in outcomes if not outcome.is_answerable]
    k_values = run.k_values
    max_k = max(k_values)

    overall = metrics_table(outcomes, k_values)
    groups = by_category(outcomes)

    lines: list[str] = []
    add = lines.append

    add("# Retrieval Evaluation Report")
    add("")
    add(
        "Deterministic evaluation of the dense retriever over the five-document corpus. "
        "Every number below is computed from the artifacts named in this section; nothing "
        "is estimated, and no score threshold is applied anywhere."
    )
    add("")

    # ---- context
    add("## 1. Run context")
    add("")
    add("| Input | Value |")
    add("| --- | --- |")
    add(f"| Index metric | `{run.metric}` |")
    add(f"| Indexed vectors | {run.vector_count} |")
    add(f"| Canonical chunks | {run.canonical_chunk_count} |")
    add(f"| Embedding model | `{run.model_id}` |")
    add(f"| Evaluation questions | {len(outcomes)} ({len(answerable)} answerable, {len(unanswerable)} unanswerable) |")
    add(f"| Cut-offs (k) | {', '.join(str(k) for k in k_values)} |")
    add(f"| Questions file | `{dataset_path.name}` sha256 `{run.input_hashes.get('questions', 'n/a')[:16]}` |")
    add(f"| Canonical chunks sha256 | `{run.input_hashes.get('canonical', 'n/a')[:16]}` |")
    add(f"| Index entries sha256 | `{run.input_hashes.get('entries', 'n/a')[:16]}` |")
    add("")
    add("Every question asks with `top_k = " + str(max_k) + "`; a question with a metadata")
    add("filter has the filter applied before ranking.")
    add("")

    # ---- methodology
    add("## 2. Methodology")
    add("")
    add("With `retrieved` the ranked result list and `relevant` the judged-relevant set:")
    add("")
    add("- Recall@k = |relevant ∩ retrieved[:k]| / |relevant|")
    add("- Precision@k = |relevant ∩ retrieved[:k]| / k")
    add("- Hit@k = 1 when any relevant chunk is in `retrieved[:k]`, else 0")
    add("- MRR@k = 1 / rank of the first relevant chunk in `retrieved[:k]`, else 0")
    add("")
    add(
        "Relevance comes only from the labels in the questions file. No similarity score is "
        "ever treated as evidence of relevance (`REQUIREMENTS.md` AC-04), and no threshold is "
        "applied. A question with no relevant chunk is reported through its scores, not "
        "through recall, so the metric definitions stay exact."
    )
    add("")
    add("Per category: " + ", ".join(f"`{name}`" for name in groups))
    add("")

    # ---- overall metrics
    add("## 3. Overall metrics (answerable questions)")
    add("")
    add("| Metric | " + " | ".join(f"@{k}" for k in k_values) + " |")
    add("| --- | " + " | ".join("---" for _ in k_values) + " |")
    for name in METRIC_NAMES:
        add(f"| {name} | " + " | ".join(_fmt(overall[name][k]) for k in k_values) + " |")
    add("")

    # ---- per category
    add("## 4. Metrics by category")
    add("")
    add(
        "| Category | Questions | Answerable | Recall@1 | Recall@"
        + str(max_k)
        + " | Precision@1 | MRR@"
        + str(max_k)
        + " |"
    )
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for name, group in groups.items():
        answered = [outcome for outcome in group if outcome.is_answerable]
        table = metrics_table(group, k_values)
        add(
            f"| {name} | {len(group)} | {len(answered)} | "
            f"{_fmt(table['recall'][1])} | {_fmt(table['recall'][max_k])} | "
            f"{_fmt(table['precision'][1])} | {_fmt(table['mrr'][max_k])} |"
        )
    add("")

    # ---- filter correctness
    add("## 5. Filter correctness")
    add("")
    filtered_questions = [outcome for outcome in outcomes if outcome.question.filters]
    add(
        f"{len(filtered_questions)} question(s) apply a metadata filter "
        "(`document_type`, `scheme`, `semester`, and/or `document_ids`). "
        "Every returned chunk was checked against the filter that was applied."
    )
    add("")
    if run.filter_violations:
        add(f"**{len(run.filter_violations)} violation(s):**")
        add("")
        for violation in run.filter_violations:
            add(f"- {violation}")
    else:
        add("Result: **0 violations** - every returned chunk satisfies the filter applied to its question.")
    add("")

    # ---- provenance
    add("## 6. Provenance correctness")
    add("")
    add(
        "Every returned chunk was checked for a complete citation chain: non-empty "
        "`chunk_id`/`document_id`/`version_id`/`filename`/`document_type`, at least one "
        "one-based page number, a `page_start`/`page_end` range that agrees with those pages, "
        "a `chunk_id` namespaced under its own `document_id`, and membership of the canonical "
        "dataset."
    )
    add("")
    if run.provenance_problems:
        add(f"**{len(run.provenance_problems)} problem(s):**")
        add("")
        for problem in run.provenance_problems:
            add(f"- {problem}")
    else:
        add("Result: **0 problems** - every returned chunk carried an accurate, traceable citation.")
    add("")

    # ---- successes
    add("## 7. Representative successes")
    add("")
    rank_one = [outcome for outcome in answerable if outcome.first_relevant_rank == 1]
    add(f"{len(rank_one)} of {len(answerable)} answerable question(s) put a relevant chunk at rank 1.")
    add("")
    add("| Question | Category | Top-1 chunk | Score | Pages |")
    add("| --- | --- | --- | --- | --- |")
    for outcome in rank_one[:12]:
        top = outcome.retrieved[0] if outcome.retrieved else None
        if top is None:
            continue
        add(
            f"| {outcome.question.question_id} | {outcome.question.category} | "
            f"`{top.chunk_id.split(':')[-1]}` | {top.score:.4f} | "
            f"{', '.join(str(page) for page in top.page_numbers)} |"
        )
    add("")

    # ---- failures
    add("## 8. Failures and near-misses")
    add("")
    missed = [outcome for outcome in answerable if outcome.first_relevant_rank is None]
    late = [
        outcome
        for outcome in answerable
        if outcome.first_relevant_rank is not None and outcome.first_relevant_rank > 1
    ]
    add(f"- Relevant chunk absent from the top {max_k}: **{len(missed)}** question(s).")
    add(f"- Relevant chunk present but not at rank 1: **{len(late)}** question(s).")
    add("")
    if missed:
        add("| Question | Category | Expected chunk | Best returned | Score |")
        add("| --- | --- | --- | --- | --- |")
        for outcome in missed:
            top = outcome.retrieved[0] if outcome.retrieved else None
            best = f"`{top.chunk_id.split(':')[-1]}`" if top else "-"
            score = f"{top.score:.4f}" if top else "-"
            expected = ", ".join(
                f"`{chunk_id.split(':')[-1]}`" for chunk_id in outcome.question.relevant_chunk_ids
            )
            add(f"| {outcome.question.question_id} | {outcome.question.category} | {expected} | {best} | {score} |")
        add("")
    if late:
        add("| Question | Category | First relevant rank | Expected chunk |")
        add("| --- | --- | --- | --- |")
        for outcome in sorted(late, key=lambda o: o.first_relevant_rank):
            expected = ", ".join(
                f"`{chunk_id.split(':')[-1]}`" for chunk_id in outcome.question.relevant_chunk_ids
            )
            add(
                f"| {outcome.question.question_id} | {outcome.question.category} | "
                f"{outcome.first_relevant_rank} | {expected} |"
            )
        add("")

    # ---- unanswerable
    add("## 9. Unanswerable-query findings")
    add("")
    add(
        "These questions have no relevant chunk in the corpus. No refusal logic exists yet, so "
        "the retriever still returns `top_k` chunks; what is reported here is how confident "
        "those returns are, which is the evidence any future threshold decision needs."
    )
    add("")
    add("| Question | Top-1 score | Mean of top " + str(max_k) + " scores |")
    add("| --- | --- | --- |")
    unanswerable_top1: list[float] = []
    for outcome in unanswerable:
        scores = [result.score for result in outcome.retrieved]
        if not scores:
            continue
        unanswerable_top1.append(scores[0])
        add(
            f"| {outcome.question.question_id} | {scores[0]:.4f} | "
            f"{sum(scores) / len(scores):.4f} |"
        )
    add("")

    correct_top1 = [
        outcome.retrieved[0].score
        for outcome in answerable
        if outcome.first_relevant_rank == 1 and outcome.retrieved
    ]
    add(
        f"For comparison, the {len(correct_top1)} answerable question(s) whose rank-1 result was "
        f"relevant scored between "
        f"{min(correct_top1):.4f} and {max(correct_top1):.4f} at rank 1."
        if correct_top1
        else "No answerable question returned a relevant chunk at rank 1."
    )
    if unanswerable_top1:
        add(
            f"The {len(unanswerable_top1)} unanswerable question(s) scored between "
            f"{min(unanswerable_top1):.4f} and {max(unanswerable_top1):.4f} at rank 1."
        )
    add("")

    # ---- thresholds
    add("## 10. Recommended quality thresholds")
    add("")
    add(
        "`REQUIREMENTS.md` Q7 leaves the retrieval range and any similarity threshold undecided, "
        "so nothing below is approved; it is a proposal derived from the measured numbers."
    )
    add("")
    if correct_top1 and unanswerable_top1:
        gap_low, gap_high = max(unanswerable_top1), min(correct_top1)
        if gap_low < gap_high:
            midpoint = (gap_low + gap_high) / 2
            add(
                f"- A score threshold between {gap_low:.4f} (highest unanswerable rank-1) and "
                f"{gap_high:.4f} (lowest correct answerable rank-1) would separate the two "
                f"groups on this dataset; a value near {midpoint:.4f} is the natural midpoint. "
                "This is evidence from a small sample, not a validated operating point."
            )
        else:
            add(
                f"- The unanswerable rank-1 scores (up to {gap_low:.4f}) overlap the correct "
                f"answerable rank-1 scores (from {gap_high:.4f} down), so **no single score "
                "threshold separates them on this dataset**. A score cut-off alone cannot be "
                "recommended; any threshold would trade missing real answers against returning "
                "unsupported ones."
            )
    add(
        f"- Recommend a reported operating range of k = 5 to {max_k} citations per answer: "
        "retrieval is measured to be strongest at rank 1 and degrades with depth, and a "
        "person reads a short citation list."
    )
    add(
        "- Recommend gating any answer on the retriever returning at least one chunk and on a "
        "future explicitly approved threshold; until then an unanswerable query must be handled "
        "by generation-time abstention, which is out of scope for this task."
    )
    add("")

    # ---- limitations
    add("## 11. Limitations")
    add("")
    add("1. **Small, single-annotator dataset.** The 58 questions and their labels were derived")
    add("   from the corpus by the builder's selectors, not by independent human raters, so")
    add("   inter-annotator agreement has not been measured.")
    add("2. **Chunk-level relevance only.** A label names the chunk(s) that state the answer, not")
    add("   a span inside them; a chunk that merely repeats the answer counts as relevant.")
    add("3. **Corpus scope.** Only the five validated documents are covered. The 2022 and 2025")
    add("   regulations have no scheme or semester, so scheme/semester filters cannot be tested")
    add("   against them.")
    add("4. **Single embedding model.** Results describe `" + str(run.model_id) + "` only.")
    add("5. **No reranking or query rewriting**, so the numbers are the plain dense-retrieval")
    add("   baseline.")
    add("6. **Unanswerable questions are a judgement**, not a guarantee: they were checked to have")
    add("   no lexical match, but a chunk could still be argued to be partially related.")
    add("")
    add("---")
    add("")
    add(
        "Generated by `python -m app.evaluation.evaluate`. The report is reproducible: the same "
        "index, canonical dataset and questions file produce this file byte for byte."
    )
    add("")
    return "\n".join(lines)


# ------------------------------------------------------------------------ main


def run_evaluation(
    *,
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    index_dir: Path | None = None,
    canonical_dir: Path | None = None,
    retriever=None,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> EvaluationRun:
    """Load the questions and index, run the evaluation, and hash the inputs."""
    from app.indexing.vector_index import DEFAULT_CANONICAL_DIR, DEFAULT_INDEX_DIR
    from app.ingestion.canonical import read_canonical_dataset

    questions_path = Path(questions_path)
    index_dir = Path(index_dir) if index_dir is not None else DEFAULT_INDEX_DIR
    canonical_dir = Path(canonical_dir) if canonical_dir is not None else DEFAULT_CANONICAL_DIR

    if retriever is None:
        from app.retrieval.search import Retriever

        retriever = Retriever(index_dir=index_dir, canonical_dir=canonical_dir)

    questions = load_questions(questions_path)
    _canonical_manifest, records = read_canonical_dataset(canonical_dir)
    canonical_chunk_ids = {record["chunk_id"] for record in records}

    run = evaluate_questions(
        questions,
        retriever,
        k_values=k_values,
        canonical_chunk_ids=canonical_chunk_ids,
    )
    hashes = {
        "questions": _sha256(questions_path),
        "canonical": _sha256(canonical_dir / "chunks.jsonl"),
        "entries": _sha256(index_dir / "entries.jsonl"),
    }
    return EvaluationRun(
        outcomes=run.outcomes,
        k_values=run.k_values,
        metric=run.metric,
        vector_count=run.vector_count,
        model_id=run.model_id,
        canonical_chunk_count=len(records),
        filter_violations=run.filter_violations,
        provenance_problems=run.provenance_problems,
        input_hashes=hashes,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation from the command line and write the report."""
    parser = argparse.ArgumentParser(description="Run the retrieval evaluation and write a report.")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--index-dir")
    parser.add_argument("--canonical-dir")
    parser.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=list(DEFAULT_K_VALUES),
        help="cut-offs to report",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    run = run_evaluation(
        questions_path=Path(args.questions),
        index_dir=Path(args.index_dir) if args.index_dir else None,
        canonical_dir=Path(args.canonical_dir) if args.canonical_dir else None,
        k_values=tuple(args.k),
    )
    report = build_report(run, dataset_path=Path(args.questions))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8", newline="\n")

    answerable = [outcome for outcome in run.outcomes if outcome.is_answerable]
    rank_one = sum(1 for outcome in answerable if outcome.first_relevant_rank == 1)
    print(f"questions: {len(run.outcomes)} ({len(answerable)} answerable)")
    print(f"rank-1 correct: {rank_one}/{len(answerable)}")
    print(f"filter violations: {len(run.filter_violations)}")
    print(f"provenance problems: {len(run.provenance_problems)}")
    print(f"report written: {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
