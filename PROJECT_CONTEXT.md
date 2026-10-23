# VTU Assistant --- Project Context & Progress

> **Purpose:** The single source of truth for the VTU Assistant project.
> Read this file at the start of a new AI coding session before doing
> project work. Update it after each completed task. **Last updated:**
> 2026-10-23 **Status:** Phase 2 --- the PDF extraction foundation is
> implemented and its tests pass. `REQUIREMENTS.md` is frozen as
> `draft-02`, and the user has explicitly approved that draft for
> implementation — recorded here only. The document's own approval
> record still reads `DRAFT — NOT APPROVED` and no signature has been
> written. The frontend shell is static files running on fixture data,
> with dark and light themes, the five interface states, table
> rendering, and the citation side panel. `app/ingestion/pdf_extract.py`
> extracts text page by page with original page provenance and a
> four-way page outcome; its 17 tests run and pass in a project-local
> `.venv` (PyMuPDF 2.0). Extraction is proven only against locally
> generated fixtures — **no real PDF has been ingested**. There is no
> backend, no chunking, no embeddings, and no real document yet.

## 1. Product vision

Build a real, student-facing VTU academic assistant that may be
published for VTU students after review/approval. It must help students
find and understand academic information from trustworthy indexed
documents. This is intended to be a reliable implementation, not merely
a demo.

**Product UX direction:** ChatGPT-inspired interaction patterns, with
original branding and a distinct identity. Do not imply affiliation with
OpenAI or VTU unless authorized.

**Core principles** - Accuracy and traceability before visual polish. -
Never invent syllabus or circular information. - Make the selected
scheme/academic context visible. - Cite source document and original PDF
page wherever possible. - If evidence is missing or retrieval confidence
is inadequate, say so. - Protect API keys and user data; assess document
permissions/licensing before public release. - Work incrementally: plan
→ implement one task → test → review → update this file.

## 2. Intended technology stack

-   Frontend: HTML, CSS, vanilla JavaScript
-   UI motion: GSAP only where it improves usability. No motion library
    has been added; GSAP was explicitly excluded from the frontend task.
-   Frontend dependencies: none. The shell uses no framework, no icon
    library, and no build step, and every icon is inline SVG.
-   Backend/API: Python + Flask
-   PDF extraction: PyMuPDF
-   Embeddings: Sentence Transformers
-   Vector search: FAISS
-   Answer generation: Google Gemini API
-   Metadata persistence: SQLite initially (JSON may be used for a
    minimal prototype, but SQLite is preferred for reliable updates)
-   Version control: Git + GitHub
-   Development environment: Trae AI coding assistant on Windows
-   REA: optional development-time investigation toolkit; do not force
    it into ordinary Python source-code analysis or the deployed
    product.

## 3. Initial scope

Start with CSE syllabus documents for the VTU 2022 scheme. Design the
data model to support more schemes and document types later.

Potential future document types: - Official syllabus PDFs - Official
circulars and notices - Exam rules and academic regulations

Do not ingest a large dataset before the ingestion and provenance
pipeline has been tested on a few representative documents.

## 4. Planned user experience

ChatGPT-inspired, not a clone: - Collapsible sidebar and new-chat
action - Conversation history (only after persistence is implemented) -
Centered chat area and message composer - Suggested academic prompts -
Visible scheme/branch/semester context - Readable answers with
headings/lists - Clickable source references showing document name and
page - Ability to open or preview the cited PDF page - Useful loading,
empty, error, and no-evidence states - Responsive layout for laptops and
phones - Keyboard accessibility, readable contrast, clear focus states -
Dark theme by default, with a visible light-theme toggle. Implemented
earlier than the "after the core flow works" plan, at explicit request;
the chosen theme is not remembered between sessions.

Possible later sections: Browse Syllabus, Saved Answers, and
admin/ingestion status. Do not build all of these before the core RAG
flow works.

## 5. RAG and provenance design requirements

### Ingestion

-   Extract text page by page using PyMuPDF.
-   Keep stable document identity and original one-based PDF page
    numbers.
-   Preserve metadata such as scheme, branch, semester, subject code,
    module, document type, effective date, source URL, filename, and
    ingestion/version information where available.
-   Chunk by document structure (module/unit/subject headings) where
    possible, then enforce a maximum chunk size. Hard-split oversized
    paragraphs safely.
-   Every chunk must retain its parent document ID and page provenance.
    If a chunk spans pages, store page_start/page_end or explicit page
    references.
-   Handle scanned PDFs/OCR as a separately identified capability; do
    not silently treat empty extraction as valid text.

### Suggested chunk metadata

-   chunk_id
-   document_id
-   filename
-   source_url (when available)
-   scheme
-   branch
-   semester
-   subject_code
-   module
-   document_type
-   effective_date (when applicable and verified)
-   page_number or page_start/page_end
-   chunk_text
-   faiss_id (or stable vector mapping)

### Vector index

-   Maintain an explicit, stable mapping: FAISS vector ID → metadata
    record → document and original page.
-   Never assume a FAISS position is itself a document ID or page
    number.
-   Normalize embeddings if using inner-product similarity as cosine
    similarity.
-   Persist index and metadata consistently; test rebuild and update
    behavior.

### Retrieval and answer generation

-   First resolve required context (especially scheme, branch,
    semester/subject) or ask a clarifying question.
-   Apply relevant metadata filters before ranking so passages from
    other schemes do not crowd out correct material.
-   Begin with a simple dense retrieval baseline, then evaluate whether
    hybrid lexical + dense retrieval and reranking improve results.
-   Bound the context by relevance and token budget; do not pass all
    chunks of a large document.
-   Give Gemini only retrieved evidence, with source labels containing
    filename and page.
-   Require citations to refer only to supplied evidence.
-   If no relevant indexed evidence is found, state that the answer is
    not available in the indexed material instead of guessing.
-   Test citations and factual grounding, not just whether answers sound
    plausible.

## 6. Reference project reviewed

Repository: `tharUmesh/Circular-Chatbot-Cascade-Retrieval` Pinned
revision: `bd73f2d1d6d3ff22d682d2d9a6640b2a7788ed5b` (10 Oct 2025)
Analysis basis: static source inspection; code was not executed.

Observed in the reviewed source (as reported in the analysis): -
Streamlit UI; PostgreSQL schema with a `VECTOR(384)` column; no pgvector
vector operators used in the retrieval path. - `.txt` documents are
loaded; no PDF parsing or page-number provenance. - `all-MiniLM-L6-v2`,
384-dimensional embeddings. - Chunking uses paragraph-greedy packing
around 1000 characters and a 50-character tail overlap; oversized
paragraphs may exceed the target. - Keyword shortlist uses PostgreSQL
full-text search with `ts_rank` and OR-joined terms, limited to 100
candidates. - Candidate vectors are fetched and cosine-scored in Python;
top 5 chunks are selected. - Parent documents are ranked by effective
date; top 2 documents are expanded to all chunks for generation. - Groq
Llama 3.1 8B Instant generates answers. - No page numbers, character
offsets, or page-level citation chain in the schema. - Duplicate
retrieval path in `pipeline.py`, confirmed by static source inspection
(the code was not executed): line 30 calls `rerank_and_gather(...)` and
assigns `doc_chunks`, which is never used again, while line 34 calls
`answer_query`, which performs its own retrieval. The first call is dead
work and an unnecessary database round trip. Confirmed by source
inspection, not runtime testing. - Potential weaknesses identified by
static reading include N+1 database queries, unbounded context
expansion, model duplication, and credentials used as defaults. These
were not runtime-tested.

Useful patterns to consider (not blindly copy): - Separate ingestion,
retrieval, reranking/context assembly, and answer generation. - Combine
lexical and semantic retrieval if evaluation demonstrates value. -
Expand context cautiously while keeping token budgets bounded. - Use
effective-date/scheme metadata appropriately. - Keep citations
structural through explicit provenance metadata.

## 7. Development workflow and AI coding rules

Use one step at a time. Do not ask an AI agent to build the whole app in
one prompt.

For each task: 1. Read this file first. 2. State the current task and
its acceptance criteria. 3. Inspect relevant existing files before
editing. 4. Make only the changes needed for that task. 5. Do not
install packages, download datasets, alter unrelated files, or make
external changes without explicit approval. 6. Run appropriate tests or
provide exact manual verification steps. 7. Report changed files,
commands run, test outcomes, known limitations, and the next task. 8.
Update the **Progress log** and **Current state / next task** sections
in this file. 9. Do not mark a task complete unless evidence shows it
passed its acceptance criteria. 10. Preserve user changes; do not
overwrite existing work without asking.

### Prompt to start a new AI session

"Read `PROJECT_CONTEXT.md` first and treat it as the project source of
truth. Briefly report the current state and next task. Inspect existing
files before changing anything. Work only on the next task, explain the
plan, and wait for my approval before making changes. After
implementation, run or describe relevant tests and update
`PROJECT_CONTEXT.md` with verified progress, changed files, test
results, limitations, and the next task. Do not invent completed work."

### Prompt to update this file after a task

"Update `PROJECT_CONTEXT.md` based only on work actually completed in
this session. Keep the file concise. Update the status, completed tasks,
changed files, tests and outcomes, decisions, known issues, and next
task. Do not mark unverified work complete. Preserve important long-term
requirements and remove obsolete details. Show me the proposed diff or
summary before saving."

**Important limitation:** The file will not update itself automatically
just because a task is completed. The AI agent must be explicitly
instructed to edit it, and the change must be saved. Review the update
before accepting it. Use Git commits as an additional history/backup.

## 8. Progress log

### Completed

-   [x] Agreed on product vision: public-facing VTU academic assistant,
    subject to approval/review.
-   [x] Chose a custom website: HTML/CSS/vanilla JS frontend + Flask
    backend.
-   [x] Chose initial RAG stack: PyMuPDF, Sentence Transformers, FAISS,
    Gemini.
-   [x] Chose ChatGPT-inspired interaction patterns with original
    branding.
-   [x] Reviewed the reference repository statically and identified page
    provenance as a major gap to avoid.
-   [x] Established incremental, test-driven workflow and this
    project-context file.
-   [x] Wrote the first requirements draft (`REQUIREMENTS.md`, revision
    `draft-01`) covering problem and users, MVP scope and deferrals,
    functional and non-functional requirements,
    scheme/missing-context behaviour, ingestion and page-citation
    requirements, retrieval and refusal behaviour, source policy,
    acceptance criteria, and the interface. Superseded by `draft-02`
    (see below).
-   [x] Confirmed the duplicate retrieval defect in the reference
    project's `pipeline.py` by static source inspection.
-   [x] Implemented the step-1 frontend shell as static files:
    `app/templates/index.html`, `app/static/css/tokens.css`,
    `app/static/css/app.css`, `app/static/js/mock-data.js`,
    `app/static/js/api.js`, `app/static/js/app.js`.
-   [x] Implemented the five required interface states (empty, loading,
    error, missing context, no evidence) plus the answered conversation
    view, switchable without reloading.
-   [x] Implemented prominent page-level citations and the in-app
    citation side panel, including an explicit "preview unavailable"
    fallback. No URL or page destination is ever fabricated when a
    source URL is missing.
-   [x] Kept a single data seam (`api.js`) so the same markup and styles
    can be connected to the Flask API later without being rebuilt.
-   [x] Verified the step-1 frontend: `node --check` passed on all three
    JavaScript files; every element id referenced by `app.js` exists in
    `index.html`; every class selector it uses is styled; no undefined
    CSS variables; no external requests and no added dependencies; all
    six files served successfully over a local HTTP server.
-   [x] Added a complete dark/light theme: a light token block in
    `tokens.css` overrides colours only, and a sun/moon toggle in the
    topbar switches `data-theme` with no reload. The toggle's accessible
    name states the action ("Switch to light mode" / "Switch to dark
    mode"). Dark remains the default. The choice is **not** persisted —
    no browser storage is used anywhere.
-   [x] Promoted the remaining literal colours in `app.css` into tokens,
    so no component style differs between themes and no colour is
    duplicated.
-   [x] Moved the selected academic context out of the DOM into a state
    object in `app.js`. The `<select>` elements are now an input to that
    state rather than the place it is stored, and nothing is selected on
    the user's behalf.
-   [x] Added table rendering for answers (caption, column headers,
    horizontally scrollable on narrow screens), because syllabus and
    regulation documents carry credit and module tables.
-   [x] Added page-fragment handling to the citation panel: a `#page=N`
    fragment is appended only to a real source URL that has none, and
    the panel states that some viewers ignore it instead of promising a
    jump. Nothing is appended when no page is recorded.
-   [x] Measured the token contrast ratios in both themes against WCAG
    2.1 AA with a throwaway script: every text pair and every focus ring
    passes. The border colours sit between 1.1:1 and 1.6:1 against the
    surfaces they outline, which is reported as a known trade-off rather
    than hidden.
-   [x] Re-verified the frontend after these changes: `node --check`
    passed on all three JavaScript files; all 41 element ids referenced
    by `app.js` exist in `index.html`; all 53 `var()` references resolve;
    every colour token has a light value; `app.css` contains no literal
    colours; no external URLs, no key-shaped strings, and no browser
    storage in any file; every `api.*` call is exported by `VTUApi`; no
    `innerHTML` or `eval`; and all six files served HTTP 200. The page
    also loads in a browser preview with no console errors.
-   [x] Updated two rows of `REQUIREMENTS.md` for the authorised theme
    scope change: FR-UI-05 now specifies a dark default with a visible,
    keyboard-accessible light toggle, and D3 now defers only
    *remembering* the chosen theme rather than the theme itself. The
    document's approval status (`DRAFT — awaiting review`) and its
    revision marker (`draft-01`) were deliberately left unchanged, so
    the edit does not imply an approved revision.
-   [x] Initialized Git and pushed the initial commit (`6e0d8a1`,
    8 files) to
    `https://github.com/AbhishekNasalapure-1008/Acadexa-VTU-assistant`.
    The branch is `main` and tracks `origin/main`. Git had not been
    initialized before this; no code changed in this step.
-   [x] Revised and froze `REQUIREMENTS.md` as `draft-02`, applying nine
    review corrections: logical document identity versus file version,
    PDF page classification, the AC-04 retrieval criterion, context
    resolution, citation fallback, retrieved-text security, the
    public-release gate, citation version integrity, and ingestion
    consistency and recovery. Committed as `a89465e`. The document's own
    approval record was deliberately left as `DRAFT — NOT APPROVED`; no
    signature was written.
-   [x] Recorded that the user **explicitly approved `REQUIREMENTS.md`
    `draft-02` for implementation**. This approval is recorded in this
    file only. It is deliberately *not* written into `REQUIREMENTS.md`,
    whose Section 12 approval record still reads `DRAFT — NOT APPROVED`;
    editing the document or simulating a signature was out of scope.
-   [x] Implemented the PDF extraction foundation as
    `app/ingestion/pdf_extract.py`, with `app/__init__.py` and
    `app/ingestion/__init__.py` added so both are importable packages.
    It opens one local PDF with PyMuPDF, extracts text page by page
    while preserving each page's original one-based PDF page number, and
    classifies every page as exactly one of `text`, `blank`,
    `image-only`, or `extraction failure` (FR-ING-01, FR-ING-05;
    ING-01/04/05/06). Missing paths, non-file paths, unreadable files,
    encrypted documents, and malformed or unparsable PDFs raise
    `PdfExtractionError` with a message naming the problem, instead of
    returning an empty successful result. It contains no chunking,
    embedding, FAISS, Gemini, Flask, or OCR code, and it invents no
    document metadata (no title, source URL, or effective date).
-   [x] Wrote focused tests in `tests/test_pdf_extract.py` plus a
    `tests/__init__.py` package marker. They use the standard-library
    `unittest` runner, so no new test dependency was added, and they
    build every fixture locally in a temporary directory with PyMuPDF.
    No document was downloaded and no VTU syllabus content was invented.
-   [x] Created a project-local virtual environment (`.venv`, Python
    3.12.7) and a `.gitignore` (expanded in the Git-hygiene pass
    below). PyMuPDF was installed **into `.venv` only**; the global
    interpreter was not modified and neither pytest nor any other
    package was installed.
    `pip` reported the packages as already present in `.venv`, so this
    step resolved to a no-op install of PyMuPDF 2.0.
-   [x] **Ran the extraction tests for real and they pass.**
    `.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v`
    reports `Ran 17 tests ... OK` — 17 executed, 17 passed, 0 failed, 0
    skipped. The suite covers multi-page text with one-based page
    numbers, a genuinely blank page, an image-only page, a page-level
    PyMuPDF error, and missing, directory, malformed, empty, and
    encrypted file inputs.
-   [x] Fixed one defect the real run exposed: the image-only fixture
    used `Pixmap.samples`, which is read-only in PyMuPDF 2.0 and raised
    `AttributeError`. It now uses `Pixmap.set_rect`. Added an encrypted-
    PDF test (verified `needs_pass` on the fixture before asserting) and
    a page-level extraction-failure test, so the failure path is
    exercised on a genuine PyMuPDF error rather than only through the
    classifier.
-   [x] Reviewed Git hygiene before the first backend commit.
    `.gitignore` now covers virtual environments (`.venv/`, `venv/`,
    `env/`), generated files (`__pycache__/`, `*.py[cod]`, `*.pyo`),
    environment and secret files (`.env`, `.env.*`, with `.env.example`
    re-included by negation), and tool caches (`.pytest_cache/`,
    `.mypy_cache/`, `.coverage`, `htmlcov/`). `git check-ignore` confirmed
    that no source file, test, `PROJECT_CONTEXT.md`, or `REQUIREMENTS.md`
    is ignored. No `.env` file exists anywhere in the tree and no secret
    is tracked or staged; no credential value was printed or written into
    the repository.

### Not yet completed / not verified

-   [ ] `REQUIREMENTS.md` approved **in the document itself**. It is
    frozen as `draft-02` and the user has approved that draft for
    implementation, but Section 12 still reads
    `DRAFT — NOT APPROVED` and is unsigned.
-   [ ] **PDF extraction validated against a real document.** The module
    now passes its 17 tests, but every fixture is generated locally by
    PyMuPDF. No lawfully sourced VTU PDF has been opened, so AC-01,
    AC-02 and AC-15 are **not** satisfied and PDF ingestion is **not**
    complete.
-   [ ] UI design brief/design tokens approved (they exist but have not
    been reviewed or approved).
-   [ ] Step-1 interface reviewed on real devices and browsers. Token
    contrast has now been measured (see Completed); the theme toggle,
    sidebar drawer, composer keys, state transitions, and citations have
    **not** yet been exercised by a person in a browser, and
    screen-reader announcements have not been checked at all.
-   [ ] Source-panel PDF preview on a real document. Every fixture
    `source_url` is null, so only the "preview unavailable" path has
    ever run; the iframe embed path has not been executed once.
-   [ ] Border contrast decision. `--border` and `--border-strong` are
    below the 3:1 non-text threshold; raising them would change the
    intended "subtle border" look and needs a decision.
-   [ ] Dependencies pinned in a dependency file. `.venv` exists but
    there is still no `requirements.txt` (or equivalent), so PyMuPDF
    `2.0` and its transitive packages (which include `numpy`,
    `onnxruntime`, `pymupdf4llm`, and `pymupdf-layout`) are recorded
    only in this file. None of those extras is imported by the
    extraction module, and no OCR code was added.
-   [ ] Official VTU source PDFs collected and their permissions/source
    recorded.
-   [ ] PDF ingestion and page-aware chunking implemented and tested.
    The extraction foundation exists and its 17 tests pass; chunking has
    not been started and no real PDF has been ingested. PDF ingestion is
    **not** complete and does not satisfy AC-01, AC-02 or AC-15.
-   [ ] Metadata persistence implemented.
-   [ ] FAISS indexing and stable ID mapping implemented.
-   [ ] Retrieval baseline and evaluation dataset created.
-   [ ] Gemini generation and citation validation implemented.
-   [ ] Flask API implemented, and the frontend shell connected to it
    (the shell currently runs on fixture data only).
-   [ ] Security, accessibility, accuracy and deployment checks
    completed.

## 9. Current state / next task

**Current phase:** Phase 2 --- the PDF extraction foundation is
implemented and verified against local fixtures. Requirements are frozen
as `draft-02` and approved by the user for implementation.
**Implementation status:** There are now two independent pieces of work.
(1) The frontend shell is static files running on fixture data
(`app/static/js/mock-data.js`), with dark and light themes, the five
interface states, marked-up tables, and the citation side panel with an
honest preview-unavailable fallback. It is not connected to a backend.
(2) The backend is one module, `app/ingestion/pdf_extract.py`, which
extracts text from a local PDF page by page, keeps each page's original
one-based number, and classifies each page as `text`, `blank`,
`image-only`, or `extraction failure`. It has no chunking, embedding,
FAISS, Gemini, Flask, or OCR code. There is no backend server, no
metadata persistence, and no real PDF has been handled yet.
**Verified this session:** `.\.venv\Scripts\python.exe -m unittest
discover -s tests -t . -v` ran **17 tests**: **17 passed, 0 failed, 0
skipped**. One real defect was found and fixed (the image-only fixture
used `Pixmap.samples`, read-only in PyMuPDF 2.0). A page-level PyMuPDF
error and an encrypted PDF are now covered by executed tests. The
frontend checks listed under Completed were verified in earlier sessions
and were not re-run here.
**Next task:** Validate extraction against a small set of lawfully
sourced VTU PDFs — checking original one-based page numbers against the
source and recording how real blank, image-only, and failing pages are
classified. Then implement page-aware chunking and metadata persistence,
and pin dependencies in a dependency file. Do not connect anything to
the network before the ingestion and provenance pipeline has been tested
on a few representative, lawfully sourced documents.

**Open decisions**

-   **What the extraction tests do not prove.** Every fixture is
    generated locally by PyMuPDF, so real-world PDFs (producer quirks,
    filled forms, unusual encodings, true scans) are untested. The
    blank-versus-image-only rule also still rests on PyMuPDF reporting
    image content; a page whose only content is vector drawing is
    reported `blank` and that remains a stated limitation.
-   **How a cited PDF page is shown.** The approved stack contains no
    PDF renderer. The side panel currently embeds the browser's own PDF
    viewer in an iframe, and JavaScript cannot detect a host that
    refuses framing (`X-Frame-Options`), so a blocked embed would appear
    as a blank panel. Unresolved; the fallback path is what works today.
-   **Whether `REQUIREMENTS.md` should record the approval.** The user
    has approved `draft-02` for implementation, but Section 12 still
    reads `DRAFT — NOT APPROVED` and is unsigned. Deliberately left
    untouched here, because editing that document was out of scope and a
    signature must not be simulated.
-   **Fixture content and naming.** Every frontend fixture `source_url`
    is null and every fixture title says it is a placeholder, so
    inventing VTU content is avoided. Only the unavailable-preview path
    can be exercised until a real document exists.
-   **Whether the theme choice is remembered.** The toggle works, but the
    selection is forgotten on reload because persisting it would need
    browser storage, which the requirements do not currently authorise.
    Requires a decision, not a code change.
-   **Whether control borders are darkened.** `--border` and
    `--border-strong` measure 1.1:1–1.6:1 against their surfaces, below
    the 3:1 non-text threshold. Controls remain identifiable by their
    labels and fills, so this may be acceptable, but it is an explicit
    decision rather than an oversight.
