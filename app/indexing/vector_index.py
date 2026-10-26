"""Build, save, load, and validate the FAISS index over the canonical chunks.

The index is one artifact set in one directory:

* ``index.faiss``   - the FAISS index itself (``faiss.write_index`` output).
* ``entries.jsonl`` - one metadata entry per vector, in ``faiss_id`` order.
* ``manifest.json`` - the index configuration, the counts, and the hashes that
  let a reader detect an index that does not match its dataset or its model.

Identity and traceability
-------------------------

``faiss_id`` is the row position of a vector in the index, and the line position
of the same chunk in ``entries.jsonl``. It is the single link between a vector
and its metadata (``REQUIREMENTS.md`` FR-META-03, FR-IDX-01). A ``faiss_id`` is
never treated as a document ID or a page number: the entry it selects carries
``chunk_id``, ``document_id``, ``version_id``, ``filename`` and the one-based
``page_numbers``.

The sidecar deliberately does **not** duplicate ``chunk_text``. The canonical
dataset stays the single source of chunk text, and the retrieval layer joins the
two by ``chunk_id``, so the corpus is not stored twice.

Consistency
-----------

``BUILDING`` is written before the artifacts and removed only after the vector
file is in place. :func:`load_index` refuses an index while that marker exists,
so a partially written index is never served (FR-IDX-05, ING-CON-03).

Nothing in here is written with a timestamp: the same canonical dataset with the
same embedding configuration must produce byte-identical artifacts, so a rebuild
can be compared with the build it replaces.

Scope boundaries: no retrieval interface, no generation, no Flask, no OCR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.indexing.embedding import (
    EmbeddingConfig,
    SentenceTransformerEmbedder,
    EmbeddingError,
)
from app.ingestion.canonical import read_canonical_dataset, sha256_of_file

#: Bumped only when the artifact layout or the manifest shape changes.
INDEX_SCHEMA_VERSION = 1

INDEX_FILENAME = "index.faiss"
ENTRIES_FILENAME = "entries.jsonl"
MANIFEST_FILENAME = "manifest.json"
#: Present only while a build is in progress; its presence makes the directory
#: unusable on purpose.
BUILDING_MARKER = "BUILDING"

#: Explicit metric names, recorded in the manifest.
METRIC_INNER_PRODUCT = "inner_product"
METRIC_L2 = "l2"

METRIC_DESCRIPTIONS = {
    METRIC_INNER_PRODUCT: (
        "inner product; vectors are L2-normalised, so this is cosine similarity"
    ),
    METRIC_L2: "squared Euclidean distance in the embedding space",
}

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANONICAL_DIR = _REPO_ROOT / "data" / "processed" / "canonical"
DEFAULT_INDEX_DIR = _REPO_ROOT / "data" / "processed" / "index"

#: The chunk-record fields carried into the index metadata. ``chunk_text`` is
#: deliberately absent (see the module docstring).
ENTRY_FIELDS = (
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
    "module",
    "module_label",
    "page_number",
    "page_start",
    "page_end",
    "page_numbers",
    "approx_token_count",
)


class IndexArtifactError(RuntimeError):
    """An index artifact is missing, incompatible, or internally inconsistent."""


class IndexDependencyError(IndexArtifactError):
    """The vector-index runtime is not installed in the interpreter that is running."""


def _require_faiss():
    """Import FAISS, or report exactly what is missing.

    Deferred to here so that importing this module, and running the tests that
    only exercise the pure logic, works without FAISS installed.
    """
    try:
        import faiss
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise IndexDependencyError(
            "faiss is not installed in this interpreter "
            f"({sys.executable}). Install faiss-cpu into the project environment, "
            "or run this stage with an interpreter that already has it."
        ) from exc
    return faiss


def _say(progress, message: str) -> None:
    if progress is not None:
        progress(message)


def entry_from_record(record: dict, faiss_id: int) -> dict:
    """Build one index entry from a canonical chunk record."""
    missing = [field for field in ENTRY_FIELDS if field not in record]
    if missing:
        raise IndexArtifactError(
            f"canonical chunk record is missing {', '.join(missing)}; "
            "the canonical dataset does not match this index schema"
        )
    entry = {"faiss_id": faiss_id}
    for field in ENTRY_FIELDS:
        entry[field] = record[field]
    return entry


def build_entries(records: list[dict]) -> list[dict]:
    """Map every chunk record to an entry, assigning ``faiss_id`` by position."""
    entries = [entry_from_record(record, faiss_id) for faiss_id, record in enumerate(records)]
    chunk_ids = [entry["chunk_id"] for entry in entries]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise IndexArtifactError(
            "the canonical dataset repeats a chunk_id; a vector would then have "
            "two metadata entries"
        )
    return entries


def _index_manifest(
    *,
    metric: str,
    dimension: int,
    vector_count: int,
    embedding: EmbeddingConfig,
    canonical_manifest: dict,
    entries_sha256: str,
    index_type: str,
) -> dict:
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "index_type": index_type,
        "metric": metric,
        "metric_description": METRIC_DESCRIPTIONS[metric],
        "dimension": dimension,
        "vector_count": vector_count,
        "embedding": embedding.to_manifest(),
        "chunker": canonical_manifest.get("chunker"),
        "canonical": {
            "schema_version": canonical_manifest.get("schema_version"),
            "document_count": canonical_manifest.get("document_count"),
            "chunk_count": canonical_manifest.get("chunk_count"),
            "chunks_sha256": canonical_manifest.get("chunks_sha256"),
        },
        "documents": canonical_manifest.get("documents"),
        "entries_sha256": entries_sha256,
        # No timestamp and no elapsed time: the same dataset with the same
        # configuration must produce byte-identical artifacts, so that a rebuild
        # can be compared with the build it replaces. Elapsed time is printed to
        # the console instead.
    }


def _new_index(faiss, metric: str, dimension: int):
    if metric == METRIC_INNER_PRODUCT:
        return faiss.IndexFlatIP(dimension)
    if metric == METRIC_L2:
        return faiss.IndexFlatL2(dimension)
    raise IndexArtifactError(
        f"unsupported metric {metric!r}; expected {METRIC_INNER_PRODUCT!r} or {METRIC_L2!r}"
    )


def _embed_records(embedder, records: list[dict], batch_size, progress) -> np.ndarray:
    """Embed chunk text in batches into one pre-allocated array.

    The array is allocated once and filled batch by batch, so the corpus is not
    held as a list of per-batch arrays that would then be concatenated.
    """
    total = len(records)
    dimension = embedder.config.dimension
    vectors = np.zeros((total, dimension), dtype=np.float32)
    step = batch_size or embedder.config.batch_size
    for start in range(0, total, step):
        batch = records[start : start + step]
        texts = [record["chunk_text"] for record in batch]
        vectors[start : start + len(batch)] = embedder.encode(texts, batch_size=step)
        _say(progress, f"  embedded {min(start + step, total)}/{total}")
    return vectors


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")


def _write_artifacts(index_dir: Path, index, entries: list[dict], manifest: dict, faiss) -> None:
    """Write the artifacts, refusing to leave a half-written index loadable."""
    index_dir.mkdir(parents=True, exist_ok=True)
    marker = index_dir / BUILDING_MARKER
    marker.write_text("rebuild in progress\n", encoding="utf-8")
    try:
        _write_jsonl(index_dir / ENTRIES_FILENAME, entries)
        (index_dir / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # Written under a temporary name and moved into place, so readers never
        # observe a truncated vector file.
        temporary = index_dir / (INDEX_FILENAME + ".tmp")
        faiss.write_index(index, str(temporary))
        os.replace(temporary, index_dir / INDEX_FILENAME)
    except Exception:
        # The marker stays behind on purpose: the artifacts on disk are
        # incomplete, and load_index must keep refusing them.
        raise
    marker.unlink()


def _try_existing_manifest(index_dir: Path, canonical_manifest: dict, embedding: EmbeddingConfig, metric: str):
    """Return the existing manifest when it is still valid for this build, else None."""
    try:
        loaded = load_index(index_dir)
    except IndexArtifactError as exc:
        _say(print, f"existing index is not reusable ({exc}); rebuilding")
        return None

    problems = []
    if loaded.manifest.get("canonical", {}).get("chunks_sha256") != canonical_manifest.get(
        "chunks_sha256"
    ):
        problems.append("the canonical dataset has changed")
    if loaded.manifest.get("embedding") != embedding.to_manifest():
        problems.append("the embedding configuration has changed")
    if loaded.manifest.get("metric") != metric:
        problems.append("the metric has changed")
    if problems:
        _say(print, f"existing index is not reusable ({'; '.join(problems)}); rebuilding")
        return None
    return loaded.manifest


def build_index(
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    index_dir: Path = DEFAULT_INDEX_DIR,
    embedder=None,
    *,
    metric: str = METRIC_INNER_PRODUCT,
    batch_size: int | None = None,
    rebuild: bool = False,
    progress=print,
) -> dict:
    """Build and save the FAISS index over the canonical chunk dataset.

    Returns the manifest that describes the index now on disk. When a compatible
    index already exists and ``rebuild`` is false, the existing manifest is
    returned and no embedding is performed, so a restart does not pay for a
    rebuild it does not need.
    """
    canonical_dir = Path(canonical_dir)
    index_dir = Path(index_dir)
    embedder = embedder or SentenceTransformerEmbedder()

    canonical_manifest, records = read_canonical_dataset(canonical_dir)
    if not records:
        raise IndexArtifactError(
            f"the canonical dataset at {canonical_dir} holds no chunks; nothing to index"
        )

    if not rebuild:
        existing = _try_existing_manifest(index_dir, canonical_manifest, embedder.config, metric)
        if existing is not None:
            _say(
                progress,
                f"index already built and compatible: {index_dir} "
                f"({existing['vector_count']} vectors); not rebuilding",
            )
            return existing

    faiss = _require_faiss()
    if metric not in METRIC_DESCRIPTIONS:
        raise IndexArtifactError(f"unsupported metric {metric!r}")

    started = time.perf_counter()
    entries = build_entries(records)
    _say(progress, f"embedding {len(records)} chunks with {embedder.config.model_id}")

    vectors = _embed_records(embedder, records, batch_size, progress)

    index = _new_index(faiss, metric, embedder.config.dimension)
    index.add(vectors)
    if index.ntotal != len(entries):
        raise IndexArtifactError(
            f"index holds {index.ntotal} vectors but there are {len(entries)} entries"
        )

    entries_path = index_dir / ENTRIES_FILENAME
    manifest = _index_manifest(
        metric=metric,
        dimension=embedder.config.dimension,
        vector_count=index.ntotal,
        embedding=embedder.config,
        canonical_manifest=canonical_manifest,
        entries_sha256=_entries_sha256(entries),
        index_type=type(index).__name__,
    )
    _write_artifacts(index_dir, index, entries, manifest, faiss)
    _say(
        progress,
        f"wrote {index_dir / INDEX_FILENAME}, {entries_path.name} and "
        f"{MANIFEST_FILENAME} ({index.ntotal} vectors, {embedder.config.dimension} dimensions) "
        f"in {time.perf_counter() - started:.2f}s",
    )
    return manifest


def _entries_sha256(entries: list[dict]) -> str:
    """The SHA-256 of the exact bytes ``entries.jsonl`` will contain."""
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _read_entries(path: Path) -> list[dict]:
    entries = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IndexArtifactError(f"{path} line {line_number} is not valid JSON: {exc}") from exc
        expected_id = len(entries)
        if entry.get("faiss_id") != expected_id:
            raise IndexArtifactError(
                f"{path} line {line_number} has faiss_id {entry.get('faiss_id')!r}, "
                f"expected {expected_id}; the vector-to-metadata mapping is broken"
            )
        if "chunk_id" not in entry:
            raise IndexArtifactError(f"{path} line {line_number} has no chunk_id")
        entries.append(entry)
    chunk_ids = [entry["chunk_id"] for entry in entries]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise IndexArtifactError(f"{path} repeats a chunk_id")
    return entries


@dataclass(frozen=True)
class LoadedIndex:
    """A FAISS index together with the metadata entries aligned to its vectors."""

    directory: Path
    manifest: dict
    entries: tuple[dict, ...]
    index: object

    @property
    def vector_count(self) -> int:
        return len(self.entries)

    @property
    def dimension(self) -> int:
        return int(self.manifest["dimension"])

    @property
    def metric(self) -> str:
        return self.manifest["metric"]

    @property
    def model_id(self) -> str:
        return self.manifest["embedding"]["model_id"]

    def entry(self, faiss_id: int) -> dict:
        """The metadata entry for one vector ID."""
        return self.entries[faiss_id]


def load_index(index_dir: Path = DEFAULT_INDEX_DIR) -> LoadedIndex:
    """Load and validate the index in ``index_dir``.

    Every way the artifacts can disagree with each other is checked here rather
    than discovered later as a wrong citation: a missing file, a rebuild in
    progress, an unexpected schema version, a vector count that does not match
    the entry count, a broken ``faiss_id`` sequence, a dimension mismatch, or a
    metric that disagrees with the FAISS index type.
    """
    index_dir = Path(index_dir)
    if not index_dir.is_dir():
        raise IndexArtifactError(f"index directory does not exist: {index_dir}")
    if (index_dir / BUILDING_MARKER).exists():
        raise IndexArtifactError(
            f"index at {index_dir} is incomplete: a rebuild is in progress "
            f"({BUILDING_MARKER} is present)"
        )

    missing = [
        name
        for name in (INDEX_FILENAME, ENTRIES_FILENAME, MANIFEST_FILENAME)
        if not (index_dir / name).is_file()
    ]
    if missing:
        raise IndexArtifactError(
            f"index at {index_dir} is missing {', '.join(missing)}; rebuild it"
        )

    manifest_path = index_dir / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexArtifactError(f"{manifest_path} is not valid JSON: {exc}") from exc

    if manifest.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise IndexArtifactError(
            f"{manifest_path} schema_version is {manifest.get('schema_version')!r}, "
            f"expected {INDEX_SCHEMA_VERSION}"
        )

    entries = _read_entries(index_dir / ENTRIES_FILENAME)

    recorded_entries_hash = manifest.get("entries_sha256")
    if recorded_entries_hash and recorded_entries_hash != _entries_sha256(entries):
        raise IndexArtifactError(
            f"{ENTRIES_FILENAME} does not match the hash recorded in {MANIFEST_FILENAME}; "
            "the metadata sidecar was modified after the build"
        )

    faiss = _require_faiss()
    try:
        index = faiss.read_index(str(index_dir / INDEX_FILENAME))
    except Exception as exc:
        raise IndexArtifactError(f"could not read {index_dir / INDEX_FILENAME}: {exc}") from exc

    if index.ntotal != len(entries):
        raise IndexArtifactError(
            f"{INDEX_FILENAME} holds {index.ntotal} vectors but {ENTRIES_FILENAME} holds "
            f"{len(entries)} entries; the index and its metadata disagree"
        )
    if int(index.d) != int(manifest.get("dimension", -1)):
        raise IndexArtifactError(
            f"{INDEX_FILENAME} has {index.d} dimensions but {MANIFEST_FILENAME} records "
            f"{manifest.get('dimension')}"
        )
    if manifest.get("vector_count") != index.ntotal:
        raise IndexArtifactError(
            f"{MANIFEST_FILENAME} records {manifest.get('vector_count')} vectors but "
            f"the index holds {index.ntotal}"
        )

    metric = manifest.get("metric")
    if metric not in METRIC_DESCRIPTIONS:
        raise IndexArtifactError(f"{MANIFEST_FILENAME} records unknown metric {metric!r}")
    expected_metric_type = {
        METRIC_INNER_PRODUCT: faiss.METRIC_INNER_PRODUCT,
        METRIC_L2: faiss.METRIC_L2,
    }[metric]
    if index.metric_type != expected_metric_type:
        raise IndexArtifactError(
            f"{INDEX_FILENAME} uses FAISS metric type {index.metric_type} but "
            f"{MANIFEST_FILENAME} records {metric!r}; the recorded metric would "
            "misrepresent the scores"
        )

    return LoadedIndex(
        directory=index_dir,
        manifest=manifest,
        entries=tuple(entries),
        index=index,
    )


def check_against_embedding(loaded: LoadedIndex, embedding: EmbeddingConfig) -> None:
    """Fail unless ``loaded`` was built with exactly this embedding configuration.

    A query embedded with a different model or a different normalisation would
    produce scores that cannot be compared with the stored vectors, so this is
    checked instead of silently proceeding.
    """
    recorded = loaded.manifest.get("embedding") or {}
    if recorded != embedding.to_manifest():
        raise IndexArtifactError(
            f"index was built with {json.dumps(recorded, sort_keys=True)} but the "
            f"query configuration is {json.dumps(embedding.to_manifest(), sort_keys=True)}"
        )


def main(argv: list[str] | None = None) -> int:
    """Build the index over the canonical dataset."""
    parser = argparse.ArgumentParser(description="Build the FAISS index over the canonical chunks.")
    parser.add_argument("--canonical-dir", default=str(DEFAULT_CANONICAL_DIR))
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--metric", default=METRIC_INNER_PRODUCT, choices=sorted(METRIC_DESCRIPTIONS))
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--rebuild", action="store_true", help="rebuild even if a valid index exists")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        manifest = build_index(
            Path(args.canonical_dir),
            Path(args.index_dir),
            metric=args.metric,
            batch_size=args.batch_size,
            rebuild=args.rebuild,
        )
    except (IndexArtifactError, EmbeddingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"\nindex_type={manifest['index_type']}  metric={manifest['metric']}  "
        f"vectors={manifest['vector_count']}  dimension={manifest['dimension']}  "
        f"model={manifest['embedding']['model_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
