"""Minimal dense-retrieval interface over the FAISS index.

This is a validation interface, not a conversational endpoint. It takes a query,
embeds it with the same configuration the index was built with, and returns the
top-k chunks with their metadata and their similarity or distance score. It does
not generate answers, does not call Gemini, and is not wired to Flask.

Ranking and filtering
---------------------

The metric is explicit and comes from the index manifest: an inner-product index
over L2-normalised vectors, which is cosine similarity. There is no score
threshold anywhere in this module. A high score is a ranking fact, not evidence
that a passage answers the question (``REQUIREMENTS.md`` AC-04), so the caller
decides what to do with the order; nothing here discards results by a score
cut-off that has not been evaluated.

When metadata filters are supplied, the candidate set is masked **before** the
scores are computed, so passages from another scheme, semester, branch or
document type can neither crowd out the correct material nor appear at all
(FR-RET-01, RET-03). The index is an exact ``IndexFlat`` index, so scoring only
the matching rows gives exactly the ranking that ranking-then-filtering would
give, without relying on over-fetching. A future approximate index would need a
different approach, because over-fetching before filtering can silently lose
results.

Filtering never invents a value. A filter for ``scheme="2022"`` does not match a
regulation, whose scheme is unknown — an unknown stays unknown and simply does
not match.

Scope boundaries: no generation, no refusal logic, no Flask routes, no frontend.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from app.indexing.embedding import EmbeddingConfig, SentenceTransformerEmbedder
from app.indexing.vector_index import (
    DEFAULT_CANONICAL_DIR,
    DEFAULT_INDEX_DIR,
    METRIC_INNER_PRODUCT,
    METRIC_L2,
    IndexArtifactError,
    LoadedIndex,
    check_against_embedding,
    load_index,
)
from app.ingestion.canonical import read_canonical_dataset

#: The metadata fields a caller may filter on. Each is ``None`` by default,
#: which means "no constraint on this field".
FILTER_FIELDS = ("document_type", "scheme", "semester", "branch")


@dataclass(frozen=True)
class MetadataFilter:
    """A conjunction of metadata constraints applied before ranking.

    Only the fields that are set are applied. ``None`` means the field is not
    constrained, which is different from a field whose value is legitimately
    unknown in the document.
    """

    document_type: str | None = None
    scheme: str | None = None
    semester: str | None = None
    branch: str | None = None
    document_ids: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """True when this filter constrains nothing."""
        return not any(getattr(self, field) is not None for field in FILTER_FIELDS) and not self.document_ids

    def to_dict(self) -> dict:
        """The applied constraints, for echo in a result set or a log."""
        applied = {
            field: getattr(self, field)
            for field in FILTER_FIELDS
            if getattr(self, field) is not None
        }
        if self.document_ids:
            applied["document_ids"] = list(self.document_ids)
        return applied

    def matches(self, entry: Mapping) -> bool:
        """Whether one index entry satisfies every constraint."""
        for field in FILTER_FIELDS:
            wanted = getattr(self, field)
            if wanted is not None and entry.get(field) != wanted:
                return False
        if self.document_ids and entry.get("document_id") not in self.document_ids:
            return False
        return True


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved chunk: its score, its index metadata, and its text."""

    faiss_id: int
    chunk_id: str
    score: float
    metric: str
    entry: dict
    record: dict

    @property
    def text(self) -> str:
        return self.record.get("chunk_text", "")

    @property
    def page_numbers(self) -> tuple[int, ...]:
        """The original one-based PDF pages this chunk draws text from."""
        return tuple(self.entry.get("page_numbers") or ())

    def citation(self) -> dict:
        """The identity a citation needs, taken from stored metadata only.

        Nothing here is derived from the chunk text or from the model output, so
        a citation cannot point at a page the chunk did not come from.
        """
        return {
            "chunk_id": self.entry["chunk_id"],
            "document_id": self.entry["document_id"],
            "version_id": self.entry["version_id"],
            "filename": self.entry["filename"],
            "document_type": self.entry["document_type"],
            "page_numbers": list(self.page_numbers),
            "page_start": self.entry["page_start"],
            "page_end": self.entry["page_end"],
        }


class Retriever:
    """Queries a built index and returns chunks with their metadata."""

    def __init__(
        self,
        index_dir: Path = DEFAULT_INDEX_DIR,
        canonical_dir: Path = DEFAULT_CANONICAL_DIR,
        *,
        embedder=None,
    ) -> None:
        self._loaded: LoadedIndex = load_index(index_dir)
        self._embedder = embedder or SentenceTransformerEmbedder()
        # The query must be embedded exactly as the documents were.
        check_against_embedding(self._loaded, self._embedder.config)

        canonical_manifest, records = read_canonical_dataset(canonical_dir)
        indexed_hash = (self._loaded.manifest.get("canonical") or {}).get("chunks_sha256")
        if canonical_manifest.get("chunks_sha256") != indexed_hash:
            raise IndexArtifactError(
                f"the canonical dataset at {canonical_dir} does not match the one this "
                "index was built from; the chunk text would not line up with the vectors"
            )

        self._records_by_chunk_id = {record["chunk_id"]: record for record in records}
        missing = [
            entry["chunk_id"]
            for entry in self._loaded.entries
            if entry["chunk_id"] not in self._records_by_chunk_id
        ]
        if missing:
            raise IndexArtifactError(
                f"{len(missing)} indexed chunk(s) are absent from the canonical dataset "
                f"(first: {missing[0]}); rebuild both artifacts"
            )
        self._vectors: np.ndarray | None = None

    @property
    def metric(self) -> str:
        """The explicit metric the scores are in: ``inner_product`` or ``l2``."""
        return self._loaded.metric

    @property
    def vector_count(self) -> int:
        return self._loaded.vector_count

    @property
    def model_id(self) -> str:
        return self._loaded.model_id

    @property
    def manifest(self) -> dict:
        return self._loaded.manifest

    def _vector_matrix(self) -> np.ndarray:
        """All stored vectors, reconstructed once and reused.

        Reconstructing from the index avoids keeping a second copy of the corpus
        vectors on disk.
        """
        if self._vectors is None:
            self._vectors = np.asarray(
                self._loaded.index.reconstruct_n(0, self._loaded.index.ntotal),
                dtype=np.float32,
            )
        return self._vectors

    def _rank(
        self,
        vector: np.ndarray,
        top_k: int,
        filters: MetadataFilter,
    ) -> list[tuple[int, float]]:
        """Return ``(faiss_id, score)`` pairs, best first."""
        total = self._loaded.vector_count
        if total == 0:
            return []

        if filters.is_empty():
            scores, ids = self._loaded.index.search(
                vector.reshape(1, -1), min(top_k, total)
            )
            return [
                (int(faiss_id), float(score))
                for score, faiss_id in zip(scores[0], ids[0])
                if faiss_id != -1
            ]

        candidates = [
            faiss_id
            for faiss_id, entry in enumerate(self._loaded.entries)
            if filters.matches(entry)
        ]
        if not candidates:
            return []

        matrix = self._vector_matrix()[candidates]
        if self.metric == METRIC_INNER_PRODUCT:
            scores = matrix @ vector
            order = np.argsort(-scores, kind="stable")
        elif self.metric == METRIC_L2:
            scores = ((matrix - vector) ** 2).sum(axis=1)
            order = np.argsort(scores, kind="stable")
        else:  # pragma: no cover - load_index rejects unknown metrics
            raise IndexArtifactError(f"unsupported metric {self.metric!r}")

        return [
            (candidates[index], float(scores[index])) for index in order[:top_k]
        ]

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        """Return up to ``top_k`` chunks matching ``query``, best first.

        ``top_k`` above the number of candidate chunks is not an error: fewer
        results are returned and the caller can see how many. An empty result
        list means no chunk matched, and is not filled with unrelated chunks.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        top_k = int(top_k)
        if top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        filters = filters or MetadataFilter()
        vector = np.asarray(self._embedder.encode_query(query), dtype=np.float32)

        results = []
        for faiss_id, score in self._rank(vector, top_k, filters):
            entry = self._loaded.entries[faiss_id]
            results.append(
                RetrievedChunk(
                    faiss_id=faiss_id,
                    chunk_id=entry["chunk_id"],
                    score=score,
                    metric=self.metric,
                    entry=entry,
                    record=self._records_by_chunk_id[entry["chunk_id"]],
                )
            )
        return results


def main(argv: list[str] | None = None) -> int:
    """Query the built index from the command line, for validation."""
    parser = argparse.ArgumentParser(description="Query the FAISS index (retrieval validation).")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--canonical-dir", default=str(DEFAULT_CANONICAL_DIR))
    parser.add_argument("--document-type")
    parser.add_argument("--scheme")
    parser.add_argument("--semester")
    parser.add_argument("--branch")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    filters = MetadataFilter(
        document_type=args.document_type,
        scheme=args.scheme,
        semester=args.semester,
        branch=args.branch,
    )
    try:
        retriever = Retriever(Path(args.index_dir), Path(args.canonical_dir))
    except IndexArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    results = retriever.search(args.query, top_k=args.top_k, filters=filters)
    print(
        f"query={args.query!r}  metric={retriever.metric}  vectors={retriever.vector_count}  "
        f"filters={filters.to_dict() or 'none'}  returned={len(results)}"
    )
    if not results:
        print("no chunk matched the query and filters.")
        return 0
    for rank, result in enumerate(results, start=1):
        citation = result.citation()
        print(
            f"\n{rank}. score={result.score:.4f} ({result.metric})  "
            f"pages={citation['page_numbers']}\n"
            f"   {citation['filename']}  [{citation['document_type']}]  "
            f"scheme={result.entry['scheme']} semester={result.entry['semester']} "
            f"module={result.entry['module']}  chunk={result.chunk_id[:12]}"
        )
        preview = " ".join(result.text.split())[:180]
        print(f"   {preview}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
