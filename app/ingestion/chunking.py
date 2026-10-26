"""Structure-aware, page-traceable chunking of extracted PDF text.

This module turns one :class:`~app.ingestion.pdf_extract.ExtractionResult`
into chunks that a later stage can embed and cite. It is the second step of
the ingestion pipeline, after extraction and before embedding.

Scope boundaries:

* No embeddings, FAISS, Gemini, Flask, or OCR code lives here.
* No chunk is created across two documents. The input is one document's
  extraction result, and every chunk carries that document's ID.
* No metadata is invented. A subject name, subject code, or module number
  is stored only when it was detected from the document's own structure or
  supplied by the caller; otherwise the field is ``None``
  (``REQUIREMENTS.md`` §3.4 FR-META-02, §6.3 META-02).

Requirement traceability:

* FR-ING-03 / CHK-01 - splitting prefers document structure (subject,
  module, unit headings) before any size limit is applied.
* CHK-02 / FR-ING-03 - a maximum chunk size is enforced after structural
  splitting.
* CHK-03 - a block that still exceeds the maximum is hard-split at a safe
  boundary, and the chunk records that this happened.
* FR-ING-04 / CHK-04 - every chunk stores its parent document ID and page
  provenance, using ``page_start``/``page_end`` when it spans pages and a
  single ``page_number`` when it does not.
* CHK-05 - chunks never contain text from two different documents.
* FR-META-01 / META-01 - chunk text is held separately from chunk metadata,
  and the metadata is stored per chunk because citation works at chunk
  granularity.
* FR-ING-04 / CHK-04 / AC-02 - every page that contributed text to a chunk,
  including text repeated into the chunk as overlap, is listed in the chunk's
  ``page_numbers``. A chunk therefore never cites only part of its own text.
  The repeated excerpt is a suffix of the previous chunk that can run through
  several of its paragraphs, so it is mapped back to *every* paragraph it
  overlaps, not only the last one.
* FR-META-02 / META-02 - a part of a subject that the document itself does not
  assign to a module (course outcomes, assessment details, learning resources)
  starts its own section whose module stays unknown. The module above it is
  never carried down as a guess.

Token counting
--------------

The target size is expressed in tokens, because that is the unit the
retrieval token budget is written in. No tokenizer is installed and none
may be added for this, so the size is enforced through a **transparent
character approximation**: ``APPROX_CHARS_PER_TOKEN = 4`` characters are
treated as one token. ``approx_token_count`` is that division, rounded up,
and it is deliberately named "approx" because it is not a real tokenizer
count. The relationship enforced in code is exact and testable in
characters: ``len(chunk.text) <= target_tokens * chars_per_token``.

``REQUIREMENTS.md`` Q4 records that the maximum chunk size and token budget
values are still awaiting approval, so the defaults below are pilot values,
not approved constants. They are parameters, not hard-coded limits.

The preamble of a subject (course objectives, teaching-learning notes) sits
before the first module heading, so it already forms a section whose module is
unknown. The trailing part of a subject (course outcomes, assessment details,
learning resources) has the same property, but the document places it *after*
Module 5. It is detected from a small fixed set of headings
(``_NON_MODULE_HEADINGS``) and given its own unknown-module section, so it is
never folded into the module above it. A heading that adds a trailing qualifier
(``Suggested Learning Resources: (Text Book/ Reference Book/ Manuals):``) is
reduced to its key first, so the qualifier does not hide the heading.

Page coverage and chunks without text
-------------------------------------

A page is accounted for whether or not it yields a chunk. A run that produces
no chunk from a page still reports that page in
:attr:`ChunkingResult.pages_without_content`, so page coverage is never derived
from the chunks alone. The one case that produces no chunk today is a group of
lines with no letter in it at all - page counters and stamps that survived the
furniture pass. Such a group is not emitted as a chunk, because digits that
are not attached to a word are not citable evidence, and a chunk of four
characters of page numbers would otherwise be the smallest item in the corpus.
The lines themselves are not deleted from the page or from the page count.

Page furniture
--------------

Some lines repeat on many pages without carrying syllabus content: annexure and
template labels at the top of a page, the bare page counter printed under them,
and the date or version stamp printed at the foot. They are removed only with
two kinds of evidence at once, so a genuine subject title or a body sentence
that happens to sit at the top of a page is kept:

* **position** - the line is the leading label of its page, the line directly
  under such a label, or the final line of its page;
* **repetition** - the identical line appears in the same position on at least
  ``_FURNITURE_MIN_PAGES`` pages.

Every removal is recorded as a :class:`FurnitureRemoval` (kind, text, pages) on
:attr:`ChunkingResult.furniture`, so a run reports what it dropped instead of
editing the text silently. The source PDF is never written to.

Known limitations
-----------------

* The subject/module detector is label-based (see ``_COURSE_CODE_LABEL``,
  ``_SEMESTER_LABEL``, ``_MODULE_HEADING_RE``) and was written against the
  real structure of a VTU 2022-scheme syllabus. A document with different
  headings yields one section whose subject and module are unknown, rather
  than a guess. That is the intended failure mode.
* The non-module heading set (``_NON_MODULE_HEADINGS``) is a fixed list of
  wordings read from the pilot documents. A heading worded some other way is
  not recognised, so its text stays with the module above it; that is a stated
  limitation of the detector, not a claim that the attribution is correct.
* Overlap is only inserted between consecutive chunks of the same section,
  and it never crosses a detected section boundary. The repeated text is a
  trailing excerpt of the previous chunk, trimmed forward to a line or word
  boundary, and it is attributed to every paragraph of the previous chunk that
  the excerpt overlaps.
* Overlap is dropped when it would leave no room for the next paragraph, so
  the size guarantee holds for every chunk. Consequently the final chunk of
  a section carries no overlap, and a document whose sections each fit in a
  single chunk produces no overlap at all.
* Only the furniture shapes above are handled, and a leading line is only a
  furniture position when it looks like an annexure/template label. A running
  header on another document (for example a university name and document title
  repeated at the top of every page) is left in place until its shape is
  observed and added deliberately.
* A line with no letter in it is kept on the page and in the page count, but
  never becomes a chunk of its own; see "Page coverage" above.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from app.ingestion.pdf_extract import PAGE_TEXT, ExtractionResult

__all__ = [
    "APPROX_CHARS_PER_TOKEN",
    "DEFAULT_OVERLAP_TOKENS",
    "DEFAULT_TARGET_TOKENS",
    "BOUNDARY_DETECTED",
    "BOUNDARY_SUPPLIED",
    "BOUNDARY_UNKNOWN",
    "Chunk",
    "ChunkingError",
    "ChunkingResult",
    "ChunkingSettings",
    "ChunkMetadata",
    "DocumentMetadata",
    "FurnitureRemoval",
    "SectionSummary",
    "approx_token_count",
    "chunk_document",
]

#: A subject or module boundary that was read from the document's own
#: structure.
BOUNDARY_DETECTED = "detected"

#: A boundary the caller stated for the whole input document, because the
#: document itself does not state it.
BOUNDARY_SUPPLIED = "supplied"

#: No boundary could be established. The field stays absent rather than
#: guessed.
BOUNDARY_UNKNOWN = "unknown"

#: Characters treated as one token by the size approximation. This is an
#: approximation, not a tokenizer measurement.
APPROX_CHARS_PER_TOKEN = 4

#: Pilot default target size. ``REQUIREMENTS.md`` Q4 still lists the
#: approved values as pending, so this is a parameter default, not a
#: requirement constant.
DEFAULT_TARGET_TOKENS = 500

#: Pilot default overlap. Must stay smaller than the target size.
DEFAULT_OVERLAP_TOKENS = 75

#: Units inside one chunk are separated by a blank line, so the original
#: paragraph structure survives into the chunk text.
_UNIT_SEPARATOR = "\n\n"

_SPACE_RE = re.compile(r"[ \t\u00a0\u2007\u202f]+")
_COURSE_CODE_LABEL = "course code"
_SEMESTER_LABEL = "semester"
#: A VTU course code, e.g. ``BCS501`` or ``BCG515A`` (2022 scheme) and
#: ``1BMATCS301`` or ``1BCSL307A`` (2025 scheme). The leading digit is
#: optional because the 2025 scheme prints a programme prefix in front of the
#: code; matching the exact letter-only shape would miss every 2025 subject.
_COURSE_CODE_RE = re.compile(r"^[0-9]?[A-Z]{2,6}\s?\d{3,4}\s?[A-Z]?$")
_TITLE_RE = re.compile(r"[A-Za-z]{2}")
_MODULE_HEADING_RE = re.compile(r"^(module|unit)\s*[-.\u2013\u2014:]*\s*(\d{1,2})(.*)$", re.IGNORECASE)
#: A title separated from the module number by a delimiter, e.g.
#: ``Module-1: Modular Arithmetic``. The delimiter is required: a bare
#: trailing phrase such as ``Module-3 Assessment`` is not treated as a heading.
_MODULE_TITLE_RE = re.compile(r"^[:\u2013\u2014.\-]\s*\S")
_HOURS_RE = re.compile(r"^\(?\s*\d{1,3}\s*(hours?|hrs?|h)\b.*$", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?:;])\s+")

#: Section headings that open a part of a subject the document does not assign
#: to any module. The wordings are the ones actually observed in the pilot
#: documents; a heading worded some other way is deliberately left unrecognised
#: rather than guessed. A line is matched after :func:`_non_module_heading_key`
#: has reduced it, so a heading that adds a trailing qualifier - as
#: ``Suggested Learning Resources: (Text Book/ Reference Book/ Manuals):`` does -
#: is still recognised as the heading it is.
_NON_MODULE_HEADINGS = frozenset(
    {
        "course outcome",
        "course outcomes",
        "assessment details",
        "assessment details for cie",
        "assessment structure",
        "suggested learning resources",
        "web links and video lectures",
        "web links and e-resources",
        "practical component of ipcc",
        "tutorial component of pcc",
    }
)

#: A trailing parenthetical qualifier, e.g. the ``(Text Book/ Reference Book/
#: Manuals)`` in a learning-resources heading. Dropped before the heading set is
#: consulted, so the qualifier does not hide the heading.
_TRAILING_PARENTHETICAL_RE = re.compile(r"\([^()]*\)$")

#: A letter, in any script. A line that contains none is a page counter or a
#: stamp rather than text, so it never becomes a chunk of its own.
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)

#: How many pages must show the identical line in the identical position
#: before it is treated as repeated page furniture. One occurrence is never
#: removed, so a genuine subject title or a body sentence that happens to sit
#: at the top or foot of a page survives.
_FURNITURE_MIN_PAGES = 3

#: A leading page line that is an annexure or template label, e.g.
#: ``Annexure II``, ``Annexure-II 1``, ``MKV-TEMPLATE for IPCC (26.04.2022)``,
#: ``TEMPLATE for AEC (if the course is a theory) Annexure-IV``. A trailing
#: counter or note is allowed, and the word ``template`` is matched wherever it
#: appears in the line, so a header that glues the version stamp straight onto
#: it (``VTU/PCC-PEC-OEC (3 Credits) template30032026 1``) is recognised too.
#: The label is matched without matching the whole line.
_FURNITURE_LABEL_RE = re.compile(
    r"^(?:annexure[\s\u2013\-]*(?:ii|iii|iv)\b.*|.*template.*)$", re.IGNORECASE
)

#: A bare page counter line, as printed directly under an annexure label.
_FURNITURE_COUNTER_RE = re.compile(r"^\d{1,3}$")

#: A footer stamp: a date- or version-like number with no letter in it, e.g.
#: ``12082024`` or ``15.09.2023``. At least six digits must be present, which
#: keeps a short content number such as ``50`` or ``2022`` out; the digits may
#: be separated by ``.``, ``/`` or ``-``, and the stray punctuation PDF
#: extraction leaves in front of a stamp (``@# 16032024``) is allowed.
_FURNITURE_FOOTER_RE = re.compile(r"^[^\w]*\d(?:[\d\s./\-\u2013\u2014]*\d){5,}[^\w]*$")


class ChunkingError(Exception):
    """Raised when chunking is asked to do something it cannot do safely.

    Invalid settings (a non-positive target, an overlap at least as large as
    the target) and a missing or empty ``document_id`` raise this error
    rather than producing chunks that would be untraceable.
    """


@dataclass(frozen=True)
class ChunkingSettings:
    """The size parameters used for one chunking run.

    ``target_tokens`` and ``overlap_tokens`` are the requested sizes;
    ``chars_per_token`` is the approximation that converts them into the
    character limits the code actually enforces.
    """

    target_tokens: int = DEFAULT_TARGET_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS
    chars_per_token: int = APPROX_CHARS_PER_TOKEN

    def __post_init__(self) -> None:
        if self.target_tokens <= 0:
            raise ChunkingError(f"target_tokens must be positive, got {self.target_tokens}")
        if self.chars_per_token <= 0:
            raise ChunkingError(
                f"chars_per_token must be positive, got {self.chars_per_token}"
            )
        if self.overlap_tokens < 0:
            raise ChunkingError(f"overlap_tokens cannot be negative, got {self.overlap_tokens}")
        if self.overlap_tokens >= self.target_tokens:
            raise ChunkingError(
                "overlap_tokens must be smaller than target_tokens, got "
                f"{self.overlap_tokens} >= {self.target_tokens}"
            )

    @property
    def target_chars(self) -> int:
        """The enforced maximum number of characters in one chunk."""
        return self.target_tokens * self.chars_per_token

    @property
    def overlap_chars(self) -> int:
        """The maximum number of shared characters between two chunks."""
        return self.overlap_tokens * self.chars_per_token

    @property
    def fingerprint(self) -> str:
        """A short string identifying these settings, used in chunk IDs."""
        return f"t{self.target_tokens}-o{self.overlap_tokens}-c{self.chars_per_token}"


def approx_token_count(text: str, chars_per_token: int = APPROX_CHARS_PER_TOKEN) -> int:
    """Approximate a token count as ``ceil(len(text) / chars_per_token)``.

    This is a documented approximation, not a tokenizer measurement. It
    exists so the pilot can enforce a tokens-shaped limit without adding a
    dependency. An empty string has no tokens.
    """
    if chars_per_token <= 0:
        raise ChunkingError(f"chars_per_token must be positive, got {chars_per_token}")
    if not text:
        return 0
    return -(-len(text) // chars_per_token)


@dataclass(frozen=True)
class DocumentMetadata:
    """What the caller knows about the document being chunked.

    ``document_id`` is required: it is the logical work (FR-ING-02), for
    example "the 2022-scheme 5th-semester syllabus", and it is what keeps
    chunks from different documents apart. Every other field may be
    ``None``, and a ``None`` is stored as absent rather than replaced by a
    default (FR-META-02).

    ``subject_name`` and ``subject_code`` are *defaults for the whole
    document*. They are used only where the document's own structure does
    not state a subject, and the chunk records that the value was supplied
    rather than detected.
    """

    document_id: str
    version_id: str | None = None
    filename: str | None = None
    source_url: str | None = None
    document_type: str | None = None
    scheme: str | None = None
    branch: str | None = None
    semester: str | None = None
    subject_name: str | None = None
    subject_code: str | None = None
    effective_date: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ChunkingError("document_id must be a non-empty string")


@dataclass(frozen=True)
class ChunkMetadata:
    """The metadata of one chunk, stored separately from its text.

    ``page_numbers`` is the ordered list of original one-based PDF pages the
    chunk's text actually came from, which can skip a page if that page
    contributed nothing. ``page_start``/``page_end`` are the range it spans
    (CHK-04), and :attr:`page_number` is set only when the chunk sits on a
    single page.
    """

    document_id: str
    version_id: str | None
    chunk_index: int
    filename: str | None
    document_type: str | None
    scheme: str | None
    branch: str | None
    semester: str | None
    subject_name: str | None
    subject_code: str | None
    subject_boundary: str
    module_number: int | None
    module_label: str | None
    module_boundary: str
    page_start: int
    page_end: int
    page_numbers: tuple[int, ...]
    char_count: int
    approx_token_count: int
    hard_split: bool

    @property
    def page_number(self) -> int | None:
        """The single page number, or ``None`` when the chunk spans pages."""
        return self.page_start if self.page_start == self.page_end else None

    @property
    def spans_pages(self) -> bool:
        """True when the chunk's text comes from more than one PDF page."""
        return self.page_start != self.page_end


@dataclass(frozen=True)
class Chunk:
    """One chunk: its text, its stable ID, and its metadata.

    The text is a field of its own rather than being mixed into the metadata
    dictionary, so the two can be stored in different places later.
    """

    chunk_id: str
    text: str
    metadata: ChunkMetadata

    def to_record(self) -> dict:
        """Return the chunk as a JSON-serialisable record.

        Keys follow the chunk metadata names in ``REQUIREMENTS.md``
        FR-META-01. ``faiss_id`` is deliberately absent: no vector index
        exists yet, and an absent value stays absent (FR-META-02).
        """
        meta = self.metadata
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": meta.chunk_index,
            "document_id": meta.document_id,
            "version_id": meta.version_id,
            "filename": meta.filename,
            "document_type": meta.document_type,
            "scheme": meta.scheme,
            "branch": meta.branch,
            "semester": meta.semester,
            "subject_name": meta.subject_name,
            "subject_code": meta.subject_code,
            "subject_boundary": meta.subject_boundary,
            "module": meta.module_number,
            "module_label": meta.module_label,
            "module_boundary": meta.module_boundary,
            "page_number": meta.page_number,
            "page_start": meta.page_start,
            "page_end": meta.page_end,
            "page_numbers": list(meta.page_numbers),
            "char_count": meta.char_count,
            "approx_token_count": meta.approx_token_count,
            "hard_split": meta.hard_split,
            "chunk_text": self.text,
        }


@dataclass(frozen=True)
class SectionSummary:
    """One detected section (a subject, or one module inside a subject).

    Kept so a run can report what structure it believed it found, rather
    than only shipping the chunks.
    """

    index: int
    subject_name: str | None
    subject_code: str | None
    subject_boundary: str
    module_number: int | None
    module_label: str | None
    module_boundary: str
    page_start: int
    page_end: int
    first_line: str
    chunk_count: int


@dataclass(frozen=True)
class FurnitureRemoval:
    """One repeated page-furniture pattern that was removed before chunking.

    ``kind`` is ``"header"`` (a leading annexure or template label),
    ``"page_counter"`` (the bare number under such a label), or ``"footer"``
    (the repeated foot-of-page stamp). ``page_numbers`` lists every page the
    line was removed from. Recording this is what makes the removal auditable
    rather than a silent edit of the document text.
    """

    kind: str
    text: str
    page_numbers: tuple[int, ...]


@dataclass(frozen=True)
class ChunkingResult:
    """Everything one chunking run produced for one document."""

    document_id: str
    version_id: str | None
    settings: ChunkingSettings
    chunks: tuple[Chunk, ...] = ()
    sections: tuple[SectionSummary, ...] = ()
    skipped_pages: tuple[int, ...] = ()
    #: Text pages that no chunk cites. Page coverage is reported here rather
    #: than inferred from the chunks, so a page that yielded no citable text is
    #: still accounted for. Pages that were not classified as text are reported
    #: separately in :attr:`skipped_pages`.
    pages_without_content: tuple[int, ...] = ()
    ambiguous_heading_lines: tuple[str, ...] = ()
    furniture: tuple[FurnitureRemoval, ...] = ()

    @property
    def chunk_count(self) -> int:
        """How many chunks this run produced."""
        return len(self.chunks)

    @property
    def is_empty(self) -> bool:
        """True when no chunk could be produced from the supplied pages."""
        return not self.chunks

    @property
    def cited_pages(self) -> tuple[int, ...]:
        """Every original page number that at least one chunk cites."""
        return tuple(sorted({page for chunk in self.chunks for page in chunk.metadata.page_numbers}))


@dataclass(frozen=True)
class _Line:
    """One non-empty normalised line, with the page it came from."""

    text: str
    page_number: int
    starts_paragraph: bool


@dataclass(frozen=True)
class _Unit:
    """A paragraph-sized piece of text, ready to be packed into a chunk."""

    text: str
    pages: tuple[int, ...]
    hard_split: bool


@dataclass(frozen=True)
class _Group:
    """One chunk's worth of units, plus the repeated text before them.

    ``seed_text`` is a trailing excerpt of the previous chunk, carried over as
    overlap. It is stored apart from the unit indices so the chunk's own
    provenance is never confused with the repeated text's provenance.
    """

    seed_text: str
    seed_pages: tuple[int, ...]
    unit_indices: tuple[int, ...]


@dataclass(frozen=True)
class _Boundary:
    """A detected subject or module start, at a line index."""

    line_index: int
    kind: str
    subject_name: str | None
    subject_code: str | None
    module_number: int | None
    module_label: str | None


def _normalise_line(raw: str) -> str:
    """Collapse padding whitespace and trim, without touching other characters.

    PDF text extraction pads headings with long runs of spaces (for example
    ``"MODULE-1              10 hours"``). Collapsing those runs makes the
    heading detectable and the chunk text readable. No character is added or
    removed otherwise.
    """
    return _SPACE_RE.sub(" ", raw).strip()


def _page_non_empty_lines(page) -> tuple[str, ...]:
    """The page's non-empty normalised lines, in the order they appear."""
    lines: list[str] = []
    for raw in page.text.splitlines():
        normalised = _normalise_line(raw)
        if normalised:
            lines.append(normalised)
    return tuple(lines)


def _detect_page_furniture(
    pages, min_pages: int = _FURNITURE_MIN_PAGES
) -> tuple[tuple["FurnitureRemoval", ...], dict[int, frozenset[int]]]:
    """Find repeated page furniture, and say which page lines to drop.

    Returns ``(removals, drop)`` where ``removals`` is the audit record and
    ``drop`` maps a page number to the positions (among that page's non-empty
    lines) that are furniture.

    Two kinds of evidence are required together, so nothing is removed on a
    hunch: the line must sit in a furniture position, and the identical line
    must occupy the same position on at least ``min_pages`` pages. A line seen
    once is always kept, which is why a genuine subject title or a body
    sentence that happens to open or close a page survives.
    """
    text_pages = [(page.page_number, _page_non_empty_lines(page)) for page in pages]
    text_pages = [(number, lines) for number, lines in text_pages if lines]

    leading_labels: dict[int, tuple[str, ...]] = {}
    leading_counters: dict[int, str | None] = {}
    for number, lines in text_pages:
        labels: list[str] = []
        index = 0
        while index < len(lines) and _FURNITURE_LABEL_RE.match(lines[index]):
            labels.append(lines[index])
            index += 1
        counter: str | None = None
        if labels and index < len(lines) and _FURNITURE_COUNTER_RE.match(lines[index]):
            counter = lines[index]
        leading_labels[number] = tuple(labels)
        leading_counters[number] = counter

    label_counts = Counter(text for labels in leading_labels.values() for text in labels)
    confirmed_labels = {text for text, count in label_counts.items() if count >= min_pages}

    footer_counts = Counter(lines[-1] for _, lines in text_pages)
    confirmed_footers = {
        text
        for text, count in footer_counts.items()
        if count >= min_pages and _FURNITURE_FOOTER_RE.match(text)
    }

    drop: dict[int, frozenset[int]] = {}
    label_pages: dict[str, list[int]] = {}
    counter_pages: dict[str, list[int]] = {}
    footer_pages: dict[str, list[int]] = {}

    for number, lines in text_pages:
        positions: set[int] = set()
        labels = leading_labels[number]
        dropped_labels = 0
        for offset, text in enumerate(labels):
            if text not in confirmed_labels:
                break
            positions.add(offset)
            label_pages.setdefault(text, []).append(number)
            dropped_labels += 1
        # The counter is removed only when it directly follows labels that were
        # themselves removed, so a bare number elsewhere on the page is safe.
        if labels and dropped_labels == len(labels):
            counter = leading_counters[number]
            if counter is not None:
                positions.add(dropped_labels)
                counter_pages.setdefault(counter, []).append(number)
        if lines[-1] in confirmed_footers:
            positions.add(len(lines) - 1)
            footer_pages.setdefault(lines[-1], []).append(number)
        if positions:
            drop[number] = frozenset(positions)

    removals: list[FurnitureRemoval] = []
    for kind, page_map in (
        ("header", label_pages),
        ("page_counter", counter_pages),
        ("footer", footer_pages),
    ):
        for text, page_numbers in page_map.items():
            removals.append(
                FurnitureRemoval(
                    kind=kind, text=text, page_numbers=tuple(page_numbers)
                )
            )
    removals.sort(key=lambda removal: (removal.kind, removal.text))
    return tuple(removals), drop


def _lines_from_pages(
    pages, drop: dict[int, frozenset[int]] | None = None
) -> tuple[_Line, ...]:
    """Build the normalised line stream, keeping each line's page number.

    Blank lines are dropped but remembered: a line that follows a blank line,
    or that is the first *kept* line of a page, is marked as starting a
    paragraph. Pages whose outcome is not ``text`` contribute no lines at all.
    A line listed in ``drop`` for its page is page furniture and is skipped
    without affecting the paragraph flag of the line after it.
    """
    lines: list[_Line] = []
    for page in pages:
        if page.outcome != PAGE_TEXT:
            continue
        dropped = (drop or {}).get(page.page_number, frozenset())
        first_on_page = True
        blank_pending = False
        position = 0
        for raw in page.text.splitlines():
            normalised = _normalise_line(raw)
            if not normalised:
                blank_pending = True
                continue
            current = position
            position += 1
            if current in dropped:
                continue
            lines.append(
                _Line(
                    text=normalised,
                    page_number=page.page_number,
                    starts_paragraph=first_on_page or blank_pending,
                )
            )
            first_on_page = False
            blank_pending = False
    return tuple(lines)


def _match_module_heading(text: str) -> tuple[int, str] | None:
    """Return ``(module_number, remainder)`` when a line looks like a heading."""
    match = _MODULE_HEADING_RE.match(text)
    if match is None:
        return None
    return int(match.group(2)), match.group(3).strip()


def _is_module_remainder(remainder: str) -> bool:
    """Whether the text after ``Module-N`` still leaves a heading.

    A heading is a module line whose trailing text is absent, is an hours
    annotation (``MODULE-1 10 hours``), or is a title introduced by a delimiter
    (``Module-1: Modular Arithmetic``). A bare trailing phrase with no
    delimiter such as ``Module-3 Assessment`` is none of these and stays
    ambiguous, so body text that merely mentions a module is never promoted to
    a boundary.
    """
    if not remainder:
        return True
    if _HOURS_RE.match(remainder):
        return True
    return bool(_MODULE_TITLE_RE.match(remainder))


def _subject_header(lines: tuple[_Line, ...], code_label_index: int) -> tuple[str | None, int]:
    """Find the subject header block ending at a ``Course Code`` label.

    Two layouts have been observed. The 2022 scheme puts the semester between
    the title and the label::

        <subject title>
        Semester
        V
        Course Code
        BCS501

    The 2025 scheme prints the semester *below* the label, so only the title
    sits above it::

        <subject title>
        Course Code
        1BMATCS301
        Scheme
        2025
        Semester
        3

    So the subject name is the line directly above the ``Course Code`` label,
    or directly above an intervening ``Semester`` label when one is present.
    Returns ``(subject_name, boundary_index)``, where ``boundary_index`` is the
    top of the header block so the title falls inside the subject rather than
    leaking into the section before it. The search stays on the same page and
    never crosses a page break.

    A candidate is accepted only when it at least looks like a title. If it
    does not, the block starts at the label anchor with no name: reporting a
    page counter as a subject name would be a fabricated value (FR-META-02).
    """
    page_number = lines[code_label_index].page_number
    anchor = code_label_index
    for index in range(code_label_index - 1, -1, -1):
        if lines[index].page_number != page_number:
            break
        if lines[index].text.lower() == _SEMESTER_LABEL:
            anchor = index
            break
    candidate = anchor - 1
    has_candidate = candidate >= 0 and lines[candidate].page_number == page_number
    if has_candidate and _TITLE_RE.search(lines[candidate].text):
        return lines[candidate].text, candidate
    return None, anchor


def _non_module_heading_key(text: str) -> str:
    """Reduce a line to the key used to match :data:`_NON_MODULE_HEADINGS`.

    A heading may carry a trailing qualifier and one or two colons - the
    documents print both ``Suggested Learning Resources: (Text Book/ Reference
    Book/ Manuals):`` and ``Assessment Details for CIE  (both CIE and SEE)`` -
    so the trailing colon and the trailing parenthetical are peeled off until
    neither is left, whitespace is collapsed, and the result is lowercased. Any
    other line reduces to something that does not match the set.
    """
    key = " ".join(text.split()).lower()
    while True:
        stripped = key.rstrip(":").rstrip()
        stripped = _TRAILING_PARENTHETICAL_RE.sub("", stripped).rstrip()
        if stripped == key:
            return key
        key = stripped


def _detect_boundaries(
    lines: tuple[_Line, ...],
) -> tuple[tuple[_Boundary, ...], tuple[str, ...]]:
    """Find subject, module, and non-module boundaries, plus skipped module-like lines.

    A line is only treated as a module heading when the text after the number
    is empty, is an hours annotation, or is a delimiter-introduced title. A line
    such as ``"Module-3 Assessment"`` is none of those, so it is not treated as
    a boundary; it is returned in the ambiguous list so a run can report it
    instead of quietly guessing.

    A line whose text is one of the fixed :data:`_NON_MODULE_HEADINGS` opens a
    section the document does not assign to a module (course outcomes,
    assessment details, learning resources). That section's module is left
    unknown rather than inherited from the module above it.
    """
    boundaries: list[_Boundary] = []
    ambiguous: list[str] = []
    previous_index = -1

    for index, line in enumerate(lines):
        lowered = line.text.lower()
        if (
            lowered == _COURSE_CODE_LABEL
            and index + 1 < len(lines)
            and _COURSE_CODE_RE.match(lines[index + 1].text.upper())
        ):
            code = lines[index + 1].text.upper().replace(" ", "")
            name, start = _subject_header(lines, index)
            start = max(start, previous_index + 1)
            boundaries.append(
                _Boundary(
                    line_index=start,
                    kind="subject",
                    subject_name=name,
                    subject_code=code,
                    module_number=None,
                    module_label=None,
                )
            )
            previous_index = start
            continue

        if _non_module_heading_key(line.text) in _NON_MODULE_HEADINGS:
            boundaries.append(
                _Boundary(
                    line_index=index,
                    kind="non_module",
                    subject_name=None,
                    subject_code=None,
                    module_number=None,
                    module_label=None,
                )
            )
            previous_index = index
            continue

        heading = _match_module_heading(line.text)
        if heading is None:
            continue
        number, remainder = heading
        if not _is_module_remainder(remainder):
            ambiguous.append(line.text)
            continue
        boundaries.append(
            _Boundary(
                line_index=index,
                kind="module",
                subject_name=None,
                subject_code=None,
                module_number=number,
                module_label=f"Module-{number}",
            )
        )
        previous_index = index

    return tuple(boundaries), tuple(ambiguous)


def _split_oversized(text: str, limit: int) -> tuple[tuple[str, ...], bool]:
    """Split ``text`` into pieces of at most ``limit`` characters.

    Sentence boundaries are tried first; a sentence that is still too long is
    hard-split at the last space before the limit, and at the limit itself if
    there is no space. Returns the pieces and whether a hard split happened
    (CHK-03).
    """
    if len(text) <= limit:
        return (text,), False

    pieces: list[str] = []
    hard = False
    buffer = ""
    for sentence in _SENTENCE_RE.split(text):
        if not sentence:
            continue
        candidate = sentence if not buffer else f"{buffer} {sentence}"
        if len(candidate) <= limit:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        if len(sentence) <= limit:
            buffer = sentence
            continue
        # A single sentence longer than the limit: hard-split it.
        hard = True
        remaining = sentence
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            pieces.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        buffer = remaining
    if buffer:
        pieces.append(buffer)
    return tuple(pieces), hard


def _units_for_lines(lines: tuple[_Line, ...], start: int, end: int, limit: int) -> tuple[_Unit, ...]:
    """Group the lines of one section into paragraph units.

    A new unit begins where the source had a blank line, where a new page
    started, or where a module heading was detected. Note that headings are
    also section boundaries, so this covers a heading that shares a
    paragraph with body text.
    """
    units: list[_Unit] = []
    buffer: list[_Line] = []

    def flush() -> None:
        if not buffer:
            return
        text = "\n".join(line.text for line in buffer)
        pieces, hard = _split_oversized(text, limit)
        for piece in pieces:
            # A piece with no letter in it at all is a page counter or a stamp
            # that survived the furniture pass, not citable evidence, so it is
            # never emitted as a chunk of its own. The lines stay on the page
            # and in the page count; the page is reported instead in
            # :attr:`ChunkingResult.pages_without_content` when no chunk cites
            # it.
            if piece.strip() and _LETTER_RE.search(piece):
                units.append(_Unit(text=piece, pages=_pages_of(buffer), hard_split=hard))
        buffer.clear()

    for index in range(start, end):
        line = lines[index]
        heading = _match_module_heading(line.text)
        starts_heading = heading is not None and _is_module_remainder(heading[1])
        if buffer and (line.starts_paragraph or starts_heading):
            flush()
        buffer.append(line)
    flush()
    return tuple(units)


def _pages_of(lines: list[_Line]) -> tuple[int, ...]:
    """The distinct page numbers of these lines, in the order first seen."""
    seen: list[int] = []
    for line in lines:
        if line.page_number not in seen:
            seen.append(line.page_number)
    return tuple(seen)


def _overlap_seed(text: str, limit: int) -> str:
    """The trailing excerpt of a chunk, to repeat at the start of the next one.

    The excerpt is taken from the very end of ``text`` and then trimmed forward
    to the next line or word boundary, so it never begins in the middle of a
    word. Because it is a genuine suffix of the previous chunk, the repeated
    text still matches the page it came from.

    Paragraph-granular overlap would have been simpler, but a paragraph in the
    pilot document is routinely longer than the whole overlap budget, which
    meant no overlap was ever inserted. Working in characters keeps the
    requested overlap size meaningful.
    """
    if limit <= 0 or not text:
        return ""
    tail = text[-limit:]
    for separator in ("\n", " "):
        cut = tail.find(separator)
        if cut != -1:
            return tail[cut + 1 :].strip()
    return tail.strip()


def _render_group(group: _Group, units: tuple[_Unit, ...]) -> str:
    """The text of one chunk: the overlap excerpt, then the chunk's paragraphs."""
    body = _UNIT_SEPARATOR.join(units[index].text for index in group.unit_indices)
    if group.seed_text:
        return f"{group.seed_text}{_UNIT_SEPARATOR}{body}"
    return body


def _seed_provenance(group: _Group, units: tuple[_Unit, ...], seed: str) -> tuple[int, ...]:
    """The pages of every part of a chunk that the overlap ``seed`` repeats.

    The seed is a trailing excerpt of the rendered chunk, so it can begin
    inside an earlier paragraph rather than at the last one. Attributing it to
    only the final paragraph would let the chunk cite text whose page is
    missing from its ``page_numbers``. Walking the rendered layout and keeping
    every segment the excerpt overlaps keeps the citation complete.
    """
    if not seed:
        return ()
    rendered = _render_group(group, units)
    start = rendered.rfind(seed)
    if start == -1:
        return ()

    segments: list[tuple[int, int, tuple[int, ...]]] = []
    offset = 0
    if group.seed_text:
        segments.append((offset, offset + len(group.seed_text), group.seed_pages))
        offset += len(group.seed_text)
    for position, unit_index in enumerate(group.unit_indices):
        if position or group.seed_text:
            offset += len(_UNIT_SEPARATOR)
        text = units[unit_index].text
        segments.append((offset, offset + len(text), units[unit_index].pages))
        offset += len(text)

    pages: list[int] = []
    for _, segment_end, segment_pages in segments:
        if segment_end <= start:
            continue
        for page in segment_pages:
            if page not in pages:
                pages.append(page)
    return tuple(pages)


def _pack_units(units: tuple[_Unit, ...], settings: ChunkingSettings) -> tuple[_Group, ...]:
    """Greedily pack units into chunks, with overlap, never exceeding the limit.

    The loop is guaranteed to make progress: units are pre-split to at most the
    target size, so a chunk that starts without an overlap seed can always
    accept the next unit, and an overlap seed that would block the next unit is
    discarded before it is reused.
    """
    if not units:
        return ()

    limit = settings.target_chars
    groups: list[_Group] = []
    cursor = 0
    seed_text = ""
    seed_pages: tuple[int, ...] = ()

    while cursor < len(units):
        indices: list[int] = []
        prefix = bool(seed_text)
        size = len(seed_text)

        while cursor < len(units):
            addition = len(units[cursor].text) + (len(_UNIT_SEPARATOR) if (indices or prefix) else 0)
            if (indices or prefix) and size + addition > limit:
                break
            indices.append(cursor)
            size += addition
            cursor += 1

        group = _Group(seed_text=seed_text, seed_pages=seed_pages, unit_indices=tuple(indices))
        groups.append(group)

        if cursor >= len(units):
            break

        seed_text = _overlap_seed(_render_group(group, units), settings.overlap_chars)
        # A seed that leaves no room for the next unit would stall the loop, so
        # it is dropped. This also stops a short chunk being repeated wholesale.
        if len(seed_text) + len(_UNIT_SEPARATOR) + len(units[cursor].text) > limit:
            seed_text = ""
        # The excerpt is a suffix of the chunk that can run back through several
        # of its paragraphs, so it is attributed to every paragraph it overlaps.
        seed_pages = _seed_provenance(group, units, seed_text)

    return tuple(groups)


def _chunk_id(document_id: str, version_id: str | None, fingerprint: str, index: int, text: str) -> str:
    """A deterministic, content-sensitive chunk ID.

    The same document, version, settings, position, and text always produce
    the same ID, so re-running an unchanged ingestion is a no-op rather than
    a duplicate (FR-ING-07, FR-ING-10).
    """
    payload = "\x1f".join((document_id, version_id or "", fingerprint, str(index), text))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{document_id}:{digest}"


def chunk_document(
    result: ExtractionResult,
    metadata: DocumentMetadata,
    settings: ChunkingSettings | None = None,
) -> ChunkingResult:
    """Chunk one document's extracted pages.

    Args:
        result: the extraction result for exactly one document. Only pages
            whose outcome is ``text`` supply content; the rest are reported
            in :attr:`ChunkingResult.skipped_pages` and supply nothing.
        metadata: what the caller knows about the document. ``document_id``
            is required and is what keeps this document's chunks separate
            from any other document's (CHK-05).
        settings: the size parameters. Defaults to the pilot settings.

    Returns:
        A :class:`ChunkingResult`. A document whose pages yield no text
        returns an empty result rather than raising, because a document with
        nothing to index is a fact about the document, not a failure.
    """
    settings = settings or ChunkingSettings()

    furniture, drop = _detect_page_furniture(result.pages)
    lines = _lines_from_pages(result.pages, drop)
    skipped = tuple(page.page_number for page in result.pages if page.outcome != PAGE_TEXT)
    text_pages = tuple(page.page_number for page in result.pages if page.outcome == PAGE_TEXT)

    if not lines:
        return ChunkingResult(
            document_id=metadata.document_id,
            version_id=metadata.version_id,
            settings=settings,
            skipped_pages=skipped,
            pages_without_content=text_pages,
            furniture=furniture,
        )

    boundaries, ambiguous = _detect_boundaries(lines)

    # Build sections: each is a run of lines sharing one subject and one
    # module. A boundary starts a section; the lines before the first
    # boundary form a lead-in section whose subject and module stay unknown.
    starts: list[tuple[int, _Boundary | None]] = []
    for boundary in boundaries:
        starts.append((boundary.line_index, boundary))
    starts.append((len(lines), None))

    # A section is (start, end, subject_boundary, subject_name, subject_code,
    # module_boundary, module_number, module_label). The per-section values are
    # snapshotted when the section closes, before the next boundary updates the
    # running state.
    sections: list[
        tuple[int, int, str, str | None, str | None, str, int | None, str | None]
    ] = []
    subject_name = metadata.subject_name
    subject_code = metadata.subject_code
    subject_boundary = (
        BOUNDARY_SUPPLIED
        if (metadata.subject_name or metadata.subject_code)
        else BOUNDARY_UNKNOWN
    )
    module_number: int | None = None
    module_label: str | None = None
    module_boundary = BOUNDARY_UNKNOWN
    cursor = 0

    for line_index, boundary in starts:
        if line_index > cursor:
            sections.append(
                (
                    cursor,
                    line_index,
                    subject_boundary,
                    subject_name,
                    subject_code,
                    module_boundary,
                    module_number,
                    module_label,
                )
            )

        if boundary is None:
            cursor = line_index
            continue

        if boundary.kind == "subject":
            # A subject boundary resets the module: module numbering restarts
            # in the new subject, so carrying the old number over would invent
            # a module the document does not state.
            subject_code = boundary.subject_code
            subject_name = boundary.subject_name
            subject_boundary = BOUNDARY_DETECTED
            module_number = None
            module_label = None
            module_boundary = BOUNDARY_UNKNOWN
        elif boundary.kind == "non_module":
            # Non-module material (course outcomes, assessment details,
            # learning resources) keeps its subject but has no module of its
            # own, so the module above it is not carried down as a guess.
            module_number = None
            module_label = None
            module_boundary = BOUNDARY_UNKNOWN
        else:
            module_number = boundary.module_number
            module_label = boundary.module_label
            module_boundary = BOUNDARY_DETECTED
        cursor = line_index

    chunks: list[Chunk] = []
    summaries: list[SectionSummary] = []

    for index, section in enumerate(sections):
        start, end, sub_boundary, sub_name, sub_code, mod_boundary, module, label = section
        units = _units_for_lines(lines, start, end, settings.target_chars)
        groups = _pack_units(units, settings)

        section_page_start = min(line.page_number for line in lines[start:end])
        section_page_end = max(line.page_number for line in lines[start:end])
        summaries.append(
            SectionSummary(
                index=index,
                subject_name=sub_name,
                subject_code=sub_code,
                subject_boundary=sub_boundary,
                module_number=module,
                module_label=label,
                module_boundary=mod_boundary,
                page_start=section_page_start,
                page_end=section_page_end,
                first_line=lines[start].text[:80],
                chunk_count=len(groups),
            )
        )

        for group in groups:
            text = _render_group(group, units)
            pages = _group_pages(group, units)
            hard_split = any(units[unit_index].hard_split for unit_index in group.unit_indices)
            chunk_index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(
                        metadata.document_id,
                        metadata.version_id,
                        settings.fingerprint,
                        chunk_index,
                        text,
                    ),
                    text=text,
                    metadata=ChunkMetadata(
                        document_id=metadata.document_id,
                        version_id=metadata.version_id,
                        chunk_index=chunk_index,
                        filename=metadata.filename,
                        document_type=metadata.document_type,
                        scheme=metadata.scheme,
                        branch=metadata.branch,
                        semester=metadata.semester,
                        subject_name=sub_name,
                        subject_code=sub_code,
                        subject_boundary=sub_boundary,
                        module_number=module,
                        module_label=label,
                        module_boundary=mod_boundary,
                        page_start=min(pages),
                        page_end=max(pages),
                        page_numbers=pages,
                        char_count=len(text),
                        approx_token_count=approx_token_count(text, settings.chars_per_token),
                        hard_split=hard_split,
                    ),
                )
            )

    # A page is accounted for whether or not it yielded a chunk. Page coverage
    # therefore comes from the page list, not from the chunks: a text page no
    # chunk cites is reported rather than silently dropped.
    cited = {page for chunk in chunks for page in chunk.metadata.page_numbers}
    pages_without_content = tuple(page for page in text_pages if page not in cited)

    return ChunkingResult(
        document_id=metadata.document_id,
        version_id=metadata.version_id,
        settings=settings,
        chunks=tuple(chunks),
        sections=tuple(summaries),
        skipped_pages=skipped,
        pages_without_content=pages_without_content,
        ambiguous_heading_lines=ambiguous,
        furniture=furniture,
    )


def _group_pages(group: _Group, units: tuple[_Unit, ...]) -> tuple[int, ...]:
    """The distinct pages a chunk's text came from, in the order first seen.

    The overlap excerpt is included, because it is text the chunk really
    contains, and its pages are every page of the previous chunk the excerpt
    overlaps. Those pages sit immediately before the chunk's own pages, so the
    resulting order is still the document order.
    """
    seen: list[int] = []
    for page in group.seed_pages:
        if page not in seen:
            seen.append(page)
    for unit_index in group.unit_indices:
        for page in units[unit_index].pages:
            if page not in seen:
                seen.append(page)
    return tuple(seen)
