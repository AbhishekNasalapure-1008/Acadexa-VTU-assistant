"""Build the canonical, index-ready chunk dataset for the five dataset PDFs.

This module turns the five validated VTU documents into **one** authoritative
chunk dataset that the later embedding and FAISS-indexing stages read. It is
generated fresh from the corrected extraction and chunking implementation, so
the canonical dataset can never contain the stale output of an earlier pilot
run.

Scope boundaries:

* No embeddings, FAISS, Gemini, Flask, or OCR code lives here. It writes JSON
  records and a manifest, nothing else.
* The source PDFs are read only. This module never writes to, moves, renames,
  or copies them.
* No metadata is invented. A ``scheme``, ``semester`` or ``branch`` is stored
  only where the document's own structure establishes it; a regulation is
  given none, so its unknown fields stay absent (``REQUIREMENTS.md``
  FR-META-02). Nothing is inferred from a filename here.

Layout of the output directory:

* ``chunks.jsonl`` - one JSON record per chunk, documents in registry order.
  Each record is exactly :meth:`app.ingestion.chunking.Chunk.to_record`, which
  already carries ``document_id``, ``version_id``, ``filename`` and the
  one-based ``page_numbers``, so every chunk can be traced back to its source.
* ``manifest.json`` - the per-document summary, the chunker settings and a
  SHA-256 of ``chunks.jsonl``. The hash lets the indexing stage detect a
  canonical dataset that does not match its own artifacts.

Both files are written deterministically: the same source documents with the
same settings produce byte-identical output. No timestamp is written into
either file, because a timestamp would break that property; elapsed time is
printed to the console instead.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

#: The PDF-extraction and chunking modules are imported inside the functions
#: that use them, not at module level, because only *building* the dataset needs
#: PyMuPDF. Reading the format back — which is what the embedding, indexing and
#: retrieval stages do — does not, and those stages must not fail to import just
#: because the PDF toolkit is absent from the interpreter that runs them.

#: Bumped only if the record shape or the manifest shape changes, so a reader
#: can tell an old artifact from a new one.
CANONICAL_SCHEMA_VERSION = 1

#: Where the validated local dataset lives. Outside the repository, and never
#: written to by this module.
DATASET_ROOT = Path(r"C:\Users\hp\Desktop\Dataset")

#: A regulation is a clause document, not a module-based syllabus, so it is
#: given no scheme, semester or branch.
SYLLABUS = "syllabus"
REGULATION = "regulation"


@dataclass(frozen=True)
class CanonicalDocument:
    """One source document and the metadata its own structure establishes.

    ``scheme``, ``semester`` and ``branch`` are ``None`` where the document
    does not establish them. That is a deliberate absence, not a default: the
    two regulations carry none, so their fields stay absent all the way into
    the chunk records and the index metadata.
    """

    key: str
    #: Path of the PDF relative to the dataset root.
    source_relative: Path
    document_id: str
    document_type: str
    scheme: str | None = None
    semester: str | None = None
    branch: str | None = None


#: The five documents this project is allowed to process. The order here is the
#: order records are written in, so the canonical dataset is reproducible.
CANONICAL_DOCUMENTS: tuple[CanonicalDocument, ...] = (
    CanonicalDocument(
        key="2022-cse-3rd",
        source_relative=Path("Syllabus") / "2022-scheme" / "3rd_sem_syllabi.pdf",
        document_id="vtu-2022-scheme-sem3-syllabus",
        document_type=SYLLABUS,
        scheme="2022",
        semester="3",
    ),
    CanonicalDocument(
        key="2022-cse-5th",
        source_relative=Path("Syllabus") / "2022-scheme" / "5th_sem_syllabi.pdf",
        document_id="vtu-2022-scheme-sem5-syllabus",
        document_type=SYLLABUS,
        scheme="2022",
        semester="5",
    ),
    CanonicalDocument(
        key="2025-cse-3rd",
        source_relative=Path("Syllabus") / "2025-scheme" / "3rd_sem_syllabi.pdf",
        document_id="vtu-2025-scheme-sem3-syllabus",
        document_type=SYLLABUS,
        scheme="2025",
        semester="3",
    ),
    CanonicalDocument(
        key="2022-regulations",
        source_relative=Path("Regulations") / "Regulations-Clr-BE-BTECH-2022-611-02052023.pdf",
        document_id="vtu-2022-regulations-be-btech",
        document_type=REGULATION,
    ),
    CanonicalDocument(
        key="2025-regulations",
        source_relative=Path("Regulations") / "B.E.B.Tech2025.pdf",
        document_id="vtu-2025-regulations-be-btech",
        document_type=REGULATION,
    ),
)


def sha256_of_file(path: Path) -> str:
    """The SHA-256 of a file's bytes, read in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_records(
    document: CanonicalDocument,
    extraction,
    version_id: str,
    settings: ChunkingSettings,
) -> list[dict]:
    """Chunk one extraction result into the canonical JSON records.

    Pure: it touches no files, so it can be tested with a synthetic extraction.
    The records carry the document's ID, version ID and one-based page numbers,
    which is the whole traceability chain a later citation needs.
    """
    from app.ingestion.chunking import DocumentMetadata, chunk_document

    metadata = DocumentMetadata(
        document_id=document.document_id,
        version_id=version_id,
        filename=document.source_relative.name,
        document_type=document.document_type,
        scheme=document.scheme,
        semester=document.semester,
        branch=document.branch,
    )
    result = chunk_document(extraction, metadata, settings)
    return [chunk.to_record() for chunk in result.chunks]


def document_summary(
    document: CanonicalDocument,
    extraction,
    version_id: str,
    records: list[dict],
) -> dict:
    """The manifest entry for one document."""
    from app.ingestion.pdf_extract import PAGE_TEXT

    text_pages = sum(1 for page in extraction.pages if page.outcome == PAGE_TEXT)
    return {
        "key": document.key,
        "document_id": document.document_id,
        "version_id": version_id,
        "filename": document.source_relative.name,
        # Only the dataset-relative path is stored. The absolute local path is
        # not part of the dataset and is deliberately not written.
        "source_relative_path": document.source_relative.as_posix(),
        "document_type": document.document_type,
        "scheme": document.scheme,
        "semester": document.semester,
        "branch": document.branch,
        "page_count": extraction.page_count,
        "text_pages": text_pages,
        "non_text_pages": extraction.page_count - text_pages,
        "chunk_count": len(records),
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def write_canonical_dataset(
    output_dir: Path,
    records: list[dict],
    summaries: list[dict],
    settings: ChunkingSettings | None = None,
) -> dict:
    """Write ``chunks.jsonl`` and ``manifest.json``, and return the manifest.

    Separated from :func:`build_canonical_dataset` so the dataset can also be
    written from records that did not come from the five PDFs — that is what
    lets the automated suite exercise the format with a small fixture instead
    of re-processing every document. There is still exactly one writer, so the
    on-disk shape cannot drift between the real dataset and a fixture.
    """
    from app.ingestion.chunking import ChunkingSettings

    settings = settings or ChunkingSettings()
    output_dir.mkdir(parents=True, exist_ok=True)

    # A guard against a bug that emitted the same chunk twice: the index would
    # then hold duplicate vectors under one ID.
    chunk_ids = [record["chunk_id"] for record in records]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise ValueError("duplicate chunk_id in the canonical dataset")

    chunks_path = output_dir / "chunks.jsonl"
    _write_jsonl(chunks_path, records)

    manifest = {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "document_count": len(summaries),
        "chunk_count": len(records),
        "chunker": {
            "target_tokens": settings.target_tokens,
            "overlap_tokens": settings.overlap_tokens,
            "chars_per_token": settings.chars_per_token,
            "target_chars": settings.target_chars,
            "overlap_chars": settings.overlap_chars,
        },
        "chunks_sha256": sha256_of_file(chunks_path),
        "documents": summaries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def read_canonical_dataset(output_dir: Path) -> tuple[dict, list[dict]]:
    """Read a canonical dataset back as ``(manifest, records)``.

    The records keep their file order, which is the order the indexing stage
    assigns ``faiss_id`` values in. The recorded SHA-256 is checked against the
    file on disk: an index built from a dataset that changed underneath it
    would cite the wrong pages, so a mismatch is raised rather than tolerated.

    Raises ``FileNotFoundError`` when an artifact is absent and ``ValueError``
    when the two artifacts disagree with each other.
    """
    output_dir = Path(output_dir)
    chunks_path = output_dir / "chunks.jsonl"
    manifest_path = output_dir / "manifest.json"
    if not chunks_path.is_file():
        raise FileNotFoundError(f"canonical chunks not found: {chunks_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"canonical manifest not found: {manifest_path}")

    records = [
        json.loads(line)
        for line in chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("schema_version") != CANONICAL_SCHEMA_VERSION:
        raise ValueError(
            f"canonical manifest schema_version is {manifest.get('schema_version')!r}, "
            f"expected {CANONICAL_SCHEMA_VERSION}"
        )
    if manifest.get("chunk_count") != len(records):
        raise ValueError(
            f"canonical manifest records {manifest.get('chunk_count')} chunks but "
            f"chunks.jsonl holds {len(records)}"
        )
    recorded = manifest.get("chunks_sha256")
    actual = sha256_of_file(chunks_path)
    if recorded and recorded != actual:
        raise ValueError(
            f"chunks.jsonl does not match the hash recorded in manifest.json "
            f"({actual[:16]}... != {recorded[:16]}...); rebuild the canonical dataset"
        )
    return manifest, records


def build_canonical_dataset(
    output_dir: Path,
    dataset_root: Path = DATASET_ROOT,
    settings: ChunkingSettings | None = None,
) -> dict:
    """Build ``chunks.jsonl`` and ``manifest.json`` for all five documents.

    Writes only into ``output_dir``. Returns the manifest that was written, so
    a caller can report it. Raises ``FileNotFoundError`` naming the exact
    missing path if a source PDF is absent, rather than silently skipping it —
    a canonical dataset that quietly omitted a document would be worse than a
    clear failure.
    """
    from app.ingestion.chunking import ChunkingSettings
    from app.ingestion.pdf_extract import extract_pdf

    settings = settings or ChunkingSettings()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_records: list[dict] = []
    summaries: list[dict] = []

    for document in CANONICAL_DOCUMENTS:
        source = dataset_root / document.source_relative
        if not source.is_file():
            raise FileNotFoundError(f"source PDF not found: {source}")

        started = time.perf_counter()
        extraction = extract_pdf(str(source))
        version_id = sha256_of_file(source)[:16]
        records = canonical_records(document, extraction, version_id, settings)
        elapsed = time.perf_counter() - started

        all_records.extend(records)
        summary = document_summary(document, extraction, version_id, records)
        summaries.append(summary)

        # Reused from the summary rather than recomputed, so the printed page
        # count and the recorded one cannot disagree.
        print(
            f"{document.key:18} pages={extraction.page_count} "
            f"({summary['text_pages']} text)  "
            f"chunks={len(records):4}  version_id={version_id}  {elapsed:.2f}s"
        )

    return write_canonical_dataset(output_dir, all_records, summaries, settings)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: build the canonical dataset into a directory."""
    argv = list(sys.argv[1:] if argv is None else argv)
    output_dir = Path(argv[0]) if argv else Path(__file__).resolve().parents[2] / "data" / "processed" / "canonical"
    started = time.perf_counter()
    manifest = build_canonical_dataset(output_dir)
    print(
        f"\ndocuments={manifest['document_count']}  chunks={manifest['chunk_count']}  "
        f"chunks_sha256={manifest['chunks_sha256'][:16]}...  "
        f"total={time.perf_counter() - started:.2f}s"
    )
    print(f"wrote {output_dir / 'chunks.jsonl'} and {output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
