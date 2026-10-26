# VTU Assistant --- Project Context & Progress

> **Purpose:** The single source of truth for the VTU Assistant project.
> Read this file at the start of a new AI coding session before doing
> project work. Update it after each completed task. **Last updated:**
> 2026-10-26 **Status:** Phase 2 --- the PDF extraction foundation is
> implemented and its tests pass, page-aware chunking is implemented with
> verified pilots on all five dataset PDFs (three syllabi and two
> regulation documents), and the interface has been
> redesigned
> into a fuller assistant shell. `REQUIREMENTS.md` is frozen as
> `draft-02`, and the user has explicitly approved that draft for
> implementation — recorded here only. The document's own approval
> record still reads `DRAFT — NOT APPROVED` and no signature has been
> written. The frontend shell is static files running on fixture data,
> with dark and light themes, the five interface states, table
> rendering, and the citation side panel; it now also has a branded
> sidebar (identity, New chat, Chat/Syllabus/Circulars navigation, a
> session-only Recent list, an academic-context section, and a profile
> disclosure), a welcome screen with example questions, a copy-answer
> action, and honest empty Syllabus and Circulars views.
> `app/ingestion/pdf_extract.py` extracts text page by page with
> original page provenance and a four-way page outcome, and
> `app/ingestion/chunking.py` turns one extraction result into
> page-traceable chunks with deterministic IDs, gives material the
> document does not assign to a module its own unknown-module section,
> and removes only repeated page furniture that carries no syllabus
> content; their 105 tests run and pass in a project-local `.venv`
> (PyMuPDF 2.0). Extraction has also
> been run over the five real VTU PDFs held *outside* the repository in
> the local dataset: all five extracted as text, with their original
> one-based numbering intact and no failed page. Chunking has been run
> on **all five** of them — the 2022-scheme 5th-semester syllabus
> (`data/processed/pilot_2022_cse_5th/`), the 2025-scheme
> 3rd-semester syllabus (`data/processed/pilot_2025_sem3/`), the
> 2022-scheme 3rd-semester syllabus (`data/processed/pilot_2022_cse_3rd/`),
> the 2022 regulations (`data/processed/pilot_2022_regulations/`) and the
> 2025 regulations (`data/processed/pilot_2025_regulations/`) — as
> separate pilots; the 2025 syllabus run needed the subject-header rule
> generalised to its second layout. The two original syllabus pilots were
> produced by the chunker **before** the Task 6 corrections and are left
> in place unchanged (94 and 127 chunks); the corrected chunker now yields
> 95 and 135 for the same two documents, so those two pilots are stale
> and are reported as such rather than overwritten. A single **canonical**
> chunk dataset now exists for all five documents
> (`data/processed/canonical/`, 655 chunks) and a FAISS index has been
> built over it (`data/processed/index/`, 655 vectors × 384 dimensions,
> `IndexFlatIP` over L2-normalised `sentence-transformers/all-MiniLM-L6-v2`
> embeddings), with a minimal retrieval interface for validation only.
> That is still **not ingestion complete**: no SQLite metadata store
> exists, chunks are persisted as JSONL rather than in a database, there
> is no backend, no Gemini integration, and no copy of any source
> document in this repository. The redesigned
> interface has been exercised through its real event handlers against a
> stubbed DOM, but it has **not** been rendered in a real browser.

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
-   [x] Redesigned the interface into a fuller assistant shell using
    only HTML, CSS, and vanilla JavaScript — no framework, no package
    installed, no build step, and no change to file structure. The
    sidebar now carries the Acadexa identity, a prominent New chat
    action, Chat/Syllabus/Circulars navigation with a real active state
    and `aria-current`, a Recent list, the academic-context controls,
    and a profile disclosure. `tokens.css` was **not** modified: every
    new rule reuses an existing design token.
-   [x] Replaced the four fixture example questions with the ones from
    the design brief ("Show me the CSE 3rd semester syllabus", "Find
    circulars about examination registration", "Explain a subject from
    my syllabus", "Find the source of a VTU academic notification").
    They are interface strings, not answers: each is asked through the
    same path as a typed question and returns the same placeholder
    answer text, so nothing here states a VTU fact. The Context column
    used by the citation chips and the fallback table now also shows
    the recorded document type, and stays blank when the record has
    none, rather than filling it with a guess.
-   [x] Added a session-only Recent list, built from questions actually
    asked in the session, newest first, capped at six, with the empty
    state saying plainly that nothing is kept between sessions.
    Selecting an entry is asked through the same code path as a typed
    question. "Clear conversation" clears the transcript, the
    pending question, the last question, and the citation source maps —
    but deliberately keeps this list, because it is the session's
    record of which questions were asked rather than part of the
    transcript.
-   [x] Added a copy-answer action on assistant messages. The copied
    text is built from the same structured answer blocks that produced
    the message (app.js never scrapes the DOM), and the control is
    revealed only where `navigator.clipboard.writeText` exists, so it
    is absent rather than broken in a non-secure context. A refused
    clipboard announces a message instead of entering the error state.
-   [x] Added a profile disclosure — a disclosure, not a modal dialog,
    so it never traps focus. Escape closes it, an outside click closes
    it, and everything it reports is a statement of fact about this
    build (fixtures, no indexed documents, placeholder answers, current
    theme).
-   [x] Added Syllabus and Circulars section views with real active
    states and explicit "nothing is indexed yet" notices, each with a
    button back to the chat section. The navigation is therefore not
    decorative, and no document list is invented to fill it.
-   [x] Verified the redesign with the tools that were actually
    available. `node --check` passed on all three JavaScript files;
    every element id the scripts reference exists in `index.html`;
    every class they query or style exists in `index.html`/`app.css`;
    `app.css` still contains no literal colour and still carries the
    `[hidden] { display: none !important; }` override. The three
    scripts were then loaded into a Node VM with a minimal stubbed DOM
    and driven through their real handlers: **41 checks passed**,
    covering start-up, the welcome screen, the four rendered example
    prompts, section navigation including the "Ask a question instead"
    return, the profile disclosure and its Escape handler, one full ask
    flow ending in the missing-context state, and New chat. That run is
    what proved `startNewChat()` is now defined — before it, the file
    called the function without defining it. **No browser was
    available, so nothing about rendering, layout, or CSS has been
    visually confirmed.**
-   [x] Re-ran the existing Python suite after the frontend work:
    `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .`
    reports `Ran 17 tests ... OK` — 17 executed, 17 passed, 0 failed, 0
    skipped.
-   [x] Inventoried and validated the five real VTU PDFs held outside
    the repository (dataset path `C:\Users\hp\Desktop\Dataset`) by
    running `app.ingestion.pdf_extract` over them with the project's
    `.venv` Python. The run only **read** the files: none was moved,
    renamed, edited, deleted, copied into the repository, or sent
    anywhere, and no OCR was performed. Verified results, one row per
    file, are recorded in `data/metadata/dataset_inventory.csv`:

    | File (relative to the dataset root) | Category | Pages | text / blank / image-only / failure | Text readable | 1-based numbering |
    | --- | --- | --- | --- | --- | --- |
    | `Regulations/B.E.B.Tech2025.pdf` | Regulations | 41 | 41 / 0 / 0 / 0 | yes | preserved |
    | `Regulations/Regulations-Clr-BE-BTECH-2022-611-02052023.pdf` | Regulations | 65 | 65 / 0 / 0 / 0 | yes | preserved |
    | `Syllabus/2022-scheme/3rd_sem_syllabi.pdf` | Syllabus, 2022 scheme | 88 | 88 / 0 / 0 / 0 | yes | preserved |
    | `Syllabus/2022-scheme/5th_sem_syllabi.pdf` | Syllabus, 2022 scheme | 33 | 33 / 0 / 0 / 0 | yes | preserved |
    | `Syllabus/2025-scheme/3rd_sem_syllabi.pdf` | Syllabus, 2025 scheme | 59 | 59 / 0 / 0 / 0 | yes | preserved |

    Across all 286 pages there was no `blank`, `image-only`, or
    `extraction failure` page, no U+FFFD replacement character, and the
    returned page numbers ran exactly 1..N in order for every file. The
    shortest page still carried 255 characters; the per-file median was
    between 2,359 and 2,875 characters. Every page read as real prose
    (covering "VTU Regulations Governing the UG Programmes B.E. and
    B.Tech. - 2025", a course-code page such as "Mathematics for
    Computer Science ... Course Code BCS301", and so on). The
    little-text and suspected-scan columns in the CSV are empty for all
    five files.
-   [x] Found **no extraction defect**, so `app/ingestion/pdf_extract.py`
    was not changed. The suite was re-run afterwards and still reports
    `Ran 17 tests ... OK`.
-   [x] Recorded what `B.E.B.Tech2025.pdf` actually says, rather than
    inferring its status from its filename. Its cover reads "VTU
    Regulations Governing the UG Programmes B.E. and B.Tech. - 2025".
    No notification number and no effective date appear anywhere in the
    extracted text; clause 1.3 states only that the regulations "come
    into force with effect from the date of their notification by the
    Visvesvaraya Technological University, Belagavi", and clause 1.4
    applies them to students admitted "from the academic year 2025-26
    onwards". The file's own embedded PDF metadata gives a creation date
    of 2026-05-22, and the cover carries the token "22052026".
    **Whether it is approved, notified, or in force is not verifiable
    from the file, and is asserted nowhere.** No source URL and no
    publication date were found in any of the five documents, so those
    fields are left empty rather than invented.

-   [x] Implemented page-aware chunking as `app/ingestion/chunking.py`,
    the second ingestion step after extraction. `chunk_document()` takes
    one `ExtractionResult` plus a `DocumentMetadata` and returns chunks
    whose text is held separately from their metadata. It splits on
    paragraph and sentence boundaries first (FR-ING-03/CHK-01) and only
    then enforces a size limit, hard-splitting an oversized block at a
    safe boundary and recording that it did so (CHK-02/CHK-03). Every
    chunk keeps `page_numbers`, `page_start`/`page_end`, a single
    `page_number` when it sits on one page (FR-ING-04/CHK-04), and the
    document's ID, type, scheme, semester, filename and version, so
    chunks from two documents can never be produced by one call
    (CHK-05). Subject name/code and module number are stored **only**
    when the document itself states them or the caller supplies them;
    otherwise the field is absent and the boundary is recorded as
    `unknown` rather than guessed (FR-META-02/META-02). Chunk IDs are a
    SHA-256 over document ID, version ID, a settings fingerprint,
    position and text, so re-running the same input with the same
    settings produces the same IDs (FR-ING-07/FR-ING-10). No
    embeddings, FAISS, Gemini, Flask, or OCR code was added, and no
    `faiss_id` field is written.
-   [x] Sized chunks in **characters, not real tokens**, because no
    tokenizer is installed and none was added. The module documents the
    approximation explicitly (`APPROX_CHARS_PER_TOKEN = 4`, so
    `approx_token_count` is `ceil(len(text) / 4)`) and enforces the
    exact, testable relation `len(chunk.text) <= target_tokens *
    chars_per_token`. The pilot defaults are 500 tokens of target and 75
    tokens of overlap, i.e. at most 2,000 characters per chunk with at
    most 300 characters of overlap. `REQUIREMENTS.md` Q4 still lists the
    approved sizes as pending, so these are instance parameters, not
    approved constants.
-   [x] Wrote `tests/test_chunking.py` — 60 tests, appended to the
    existing suite. Every fixture is a synthetic `ExtractionResult`
    built in memory from plain dataclasses; no PDF is opened and no VTU
    syllabus wording is invented. They cover settings validation, the
    size approximation, chunk size limits, overlap behaviour, chunk-ID
    determinism and sensitivity, page provenance for single-page,
    multi-page and skipped-page chunks, subject/module metadata
    propagation and its three boundary values, missing and ambiguous
    headings, empty pages and empty input, document isolation, and the
    JSON record shape. Size assertions set `chars_per_token=1` so the
    token numbers and the character limits are the same number and the
    expected sizes are exactly checkable.
-   [x] **Ran the complete suite.** `.\.venv\Scripts\python.exe -m
    unittest discover -s tests -t . -v` reports `Ran 77 tests ... OK` —
    **77 executed, 77 passed, 0 failed, 0 skipped** (60 in
    `test_chunking.py`, 17 in `test_pdf_extract.py`). Two defects were
    found and fixed while this was being done: unit-granular overlap was
    a silent no-op (a real paragraph is usually longer than the whole
    overlap budget, so no overlap was ever inserted — overlap is now
    character-level and trimmed to a line or word boundary), and the
    subject detector accepted the line above the `Semester` label
    unconditionally, which could record a page counter as a subject
    name.
-   [x] Ran the chunking pilot on exactly one document, the 2022-scheme
    5th-semester syllabus
    (`Syllabus/2022-scheme/5th_sem_syllabi.pdf`, 33 pages, all `text`),
    through `data/processed/pilot_2022_cse_5th/run_pilot.py`. The driver
    only reads the source PDF; it does not write to it, copy it, or send
    it anywhere. Verified result: **73 chunks in 50 detected sections**,
    all 33 pages cited, no skipped page, no ambiguous heading, 0 chunks
    over the 2,000-character limit, 0 hard splits, 28 multi-page chunks,
    character length min/median/mean/max 13 / 962 / 1,013.7 / 1,994
    (≈4 / 241 / 254 / 499 approximated tokens). 9 subject codes were
    detected (`BCS501`, `BCS502`, `BCS503`, `BCGL504`, `BCG515A`,
    `BCS515B`, `BCS515C`, `BCG515D`, `BCS508`) with 5 modules each
    except `BCGL504`, plus one lead-in chunk whose subject is correctly
    left `unknown`. 20 of the 23 eligible same-section chunk pairs repeat
    text (173–299 characters, median 260.5); the other 3 are the pairs
    where the following chunk's own first paragraph was large enough that
    a 300-character repeat would have broken the size guarantee.
-   [x] Wrote the pilot outputs to `data/processed/pilot_2022_cse_5th/`:
    `chunks.jsonl` (one JSON record per chunk, text and metadata
    together, no `faiss_id`) and `chunk_quality_report.md` (chunk counts,
    size statistics, overlap measurements, the detected
    subject/module table with page ranges, per-subject rollup,
    page-provenance checks, and the limitations). No vector embeddings
    were stored. Re-running the driver produced **byte-identical** files
    (SHA-256 `135aab23aa0edcf33b106e00dd0a15825c3edb631d0c3666f4897a36716bf3d6`
    for `chunks.jsonl`), which is the evidence that the chunk IDs are
    deterministic.
-   [x] Recorded what the *first* pilot run did **not** show — **this
    list is superseded by the corrections and regenerated pilot below,
    but is kept as the record of what the validation pass found.**
    Chunking was **not**
    yet reliable in the sense of being validated: it had run on one
    document only, its heading detector was written against that
    document's observed `Course Code` + `Semester` layout, repeated page
    furniture was not stripped (an annexure label appeared in 30 chunks
    and the template footer in 4, and furniture with no body text around
    it became a 13-character chunk), and content with no module heading
    of its own — course outcomes, textbook and reference lists,
    assessment notes — was attributed to the module that preceded it,
    which is why `Module-5` held 28 of that run's 73 chunks. The module
    label on those chunks was a lower bound, not a verified claim, and
    the same folding
    explained the 4 `BCGL504` chunks that carried no module label at all.
    The other four dataset PDFs were **not** processed.
-   [x] Corrected the three chunking-pilot defects the validation above
    exposed, without changing the extraction module or the source PDFs
    (a continuation of the same task, not a new feature):
    -   **Non-module material no longer folds into Module 5.**
        `_detect_boundaries` now emits a `non_module` boundary when a
        line is one of a small fixed set of headings the document does
        not assign to a module (`course outcomes`, `assessment details
        (both cie and see)`, `suggested learning resources`, `web links
        and video lectures (e-resources)`, in their observed spellings).
        `chunk_document` gives such a section its subject but leaves its
        module `None` with boundary `unknown`, instead of carrying the
        module above it down as a guess. In the regenerated pilot,
        `Module-5` now holds 8 chunks rather than 28, and 54 chunks are
        correctly reported as having no module.
    -   **Repeated page furniture is removed conservatively.**
        `_detect_page_furniture` drops a line only with *two* kinds of
        evidence together: it sits in a furniture position (a leading
        annexure/template label, the bare counter directly under such a
        label, or the final line of the page) **and** the identical line
        occupies that same position on at least `_FURNITURE_MIN_PAGES`
        (3) pages. A line seen once or twice is always kept, so a
        genuine subject title or a body sentence at a page edge
        survives. Every removal is recorded as a `FurnitureRemoval`
        (`kind`, `text`, `page_numbers`) on `ChunkingResult.furniture`
        and reported in the pilot report's new section 4b, so nothing is
        dropped silently; the source PDF is never written to. The pilot
        removed **13 patterns over 90 page occurrences** — the
        `12082024` footer (pages 4–29), `Annexure II`/`Annexure-II 1..4`/
        `Annexure-III`/`Annexure-IV` labels, the `MKV-TEMPLATE for IPCC
        (26.04.2022)` and `TEMPLATE for AEC …` labels, and the bare page
        counters `1`–`4`.
    -   **Overlap provenance now cites every page the repeated text came
        from.** The previous code attributed an overlap excerpt to only
        the final unit of the previous chunk, so a seed that ran back
        through several paragraphs could sit on a page missing from the
        chunk's `page_numbers`. `_seed_provenance` now walks the chunk's
        rendered layout and returns the pages of *every* segment the
        excerpt overlaps; `_group_pages` puts them in document order
        before the chunk's own pages. The maximum chunk-size guarantee
        is unchanged (the seed is still dropped when it would leave no
        room for the next unit).
-   [x] Added regression tests for all three corrections to
    `tests/test_chunking.py` — `OverlapProvenanceTests` (a seed spanning
    page 1 and pages 2–3 must cite page 1, and a non-repeated page must
    not leak), `NonModuleSectionTests` (each real non-module heading
    opens an unknown-module section while the Module-5 body stays in
    Module 5, and an unrecognised heading is left alone), and
    `PageFurnitureTests` (the exact removal audit map, removal from the
    chunk text with the body preserved, a 2-page pattern kept, and a
    repeated body word never removed). One real defect was found while
    doing this: `_FURNITURE_LABEL_RE` initially required the whole line
    to match, so the pilot's actual `Annexure-II 1` label was never
    recognised; the label branch now allows a trailing counter.
-   [x] **Re-ran the complete suite.** `.\.venv\Scripts\python.exe -m
    unittest discover -s tests -t . -v` reports `Ran 90 tests ... OK` —
    **90 executed, 90 passed, 0 failed, 0 skipped** (73 in
    `test_chunking.py`, 17 in `test_pdf_extract.py`).
-   [x] Regenerated the pilot with the same `run_pilot.py` (extended to
    print and tabulate the furniture audit). Verified result:
    **94 chunks in 84 detected sections**, `version_id`
    `6c06b07dc90dfe14`, all 33 pages cited, no skipped page, 0 chunks
    over the 2,000-character limit, 0 hard splits, 14 multi-page chunks,
    character length min/median/mean/max 151 / 575 / 741.9 / 1,994.
    9 subject codes detected as before, each now followed by its
    unknown-module trailing sections; the 5 modules hold 8 chunks each
    and the 54 remaining chunks carry no module. 8 of the 10 eligible
    same-section chunk pairs repeat text (the other 2 are the
    size-limited cases). 13 furniture lines were removed across 90 page
    occurrences.
-   [x] Verified content preservation and determinism on the regenerated
    pilot with a read-only throwaway probe (since deleted; nothing was
    added to the repository): every one of the **1,298 non-furniture
    source lines appears in the chunk text** when whitespace is
    normalised (**0 missing**), **0 furniture patterns leaked** back
    into any chunk, and two runs produced identical chunk IDs and
    identical text. The overlap fix was also re-proved by temporarily
    restoring the old logic, which made `OverlapProvenanceTests` fail
    with `AssertionError: 1 not found in (2, 3)`; the fix was then
    restored and the suite passed.
-   [x] Recorded what was **not** changed: `REQUIREMENTS.md` was not
    edited; `app/ingestion/pdf_extract.py` was not modified; no source
    PDF was written to; no package was installed; no external API was
    called; the other four dataset PDFs were not processed; and nothing
    was staged, committed, or pushed.
-   [x] **Validated the chunker against the second dataset document**
    (Task 5): the 2025-scheme 3rd-semester syllabus
    `C:\Users\hp\Desktop\Dataset\Syllabus\2025-scheme\3rd_sem_syllabi.pdf`
    (59 pages, all classified `text`). Added a **separate** pilot at
    `data/processed/pilot_2025_sem3/` (`run_pilot.py` plus its generated
    `chunks.jsonl` and `chunk_quality_report.md`), reusing the 2022
    runner's conventions. The 2022 pilot was left untouched.
-   [x] **Found and fixed one general-purpose defect in the
    subject-header rule.** The 2025 header sets `Course Code` *above* its
    code with a `Scheme` label between the code and `Semester`, a layout
    the original detector did not accept; it was generalised to anchor on
    the `Course Code` label (or an intervening `Semester` label) rather
    than assuming the 2022 line order, with no document-specific branch.
    Verified result: all **9** subject codes recovered
    (`1BMATCS301`, `1BCS302`, `1BCS303`, `1BCS304`, `1BCS305`,
    `1BCSL306`, `1BCSL307A`, `1BAIL307A`, `1BCP308`) with their names,
    plus one `unknown` lead-in section. **0** module-like lines were
    rejected as ambiguous.
-   [x] **Re-ran the 2022 pilot** after the header fix and confirmed it
    is unchanged: still **94 chunks in 84 detected sections**, same
    `version_id`, byte-for-byte identical output.
-   [x] Regenerated the 2025 pilot and verified it: **127 chunks in 53
    detected sections**, all 59 pages cited, no skipped page, 0 chunks
    over the 2,000-character limit, 0 hard splits, 70 multi-page chunks,
    character length min/median/mean/max 4 / 1,393 / 1,195.8 / 2,000,
    `version_id` `86437482987bbf10`. 18 sections carry an unknown module
    by the fixed heading set; the module-labelled chunks split
    `Module-1`–`Module-4` at 5 each and `Module-5` at 12 (the rest are
    unassigned preamble/trailing material). Repeated page furniture
    removed: **1** line (`17082026`) over 59 page occurrences — the same
    conservative positional-plus-repetition evidence as the 2022 run.
-   [x] Verified content preservation and provenance on the 2025 pilot
    with read-only throwaway probes (since deleted; nothing added to the
    repository): whitespace-normalised, **0 of 5,335** non-empty source
    lines are missing from the chunk text, **0** furniture occurrences
    leak into any chunk, and a per-character page map over the kept-line
    stream (**0 of 127** chunks cite a page their text does not occupy)
    confirms the one-based page references, including the overlap seed
    attributed to every page it overlaps. Two full runner executions
    produced **byte-identical** `chunks.jsonl` (SHA-256
    `35C3FCA8BF8682E2F1134EDFBFCF711DF296A0F403E4C62E1B2121FBFB473D45`),
    so chunk IDs and text are deterministic.
-   [x] **Re-ran the complete suite.** `.\.venv\Scripts\python.exe -m
    unittest discover -s tests -t . -v` reports `Ran 95 tests ... OK` —
    **95 executed, 95 passed, 0 failed, 0 skipped** (78 in
    `test_chunking.py`, 17 in `test_pdf_extract.py`).
-   [x] Recorded what was **not** changed for Task 5:
    `REQUIREMENTS.md` was not edited; `app/ingestion/pdf_extract.py` was
    not modified; the 2022 pilot was not overwritten; no source PDF was
    written to; no package was installed; no external API was called; no
    embeddings, FAISS, Gemini, Flask, OCR, or frontend code was added;
    no other dataset PDF was processed; and nothing was staged,
    committed, or pushed.

#### Task 6 — complete dataset chunking validation (five PDFs)

-   [x] **Phase A — three small, general-purpose chunker corrections**
    in `app/ingestion/chunking.py`, each supported by evidence from the
    two existing pilots and none document-specific:
    -   **Non-module headings are matched after a trailing qualifier is
        peeled off.** A new `_non_module_heading_key()` collapses
        whitespace, then repeatedly strips a trailing colon and a
        trailing parenthetical before matching `_NON_MODULE_HEADINGS`.
        The 2025 syllabus prints the same heading with extra wording
        (`Suggested Learning Resources: (Text Book/ Reference Book/
        Manuals):`) and the 2022 layout prints `Assessment Details for
        CIE (both CIE and SEE)`, so those texts were previously left
        folded into the module above them. `Assessment Structure`,
        `PRACTICAL COMPONENT OF IPCC` and `TUTORIAL COMPONENT OF PCC`
        (with or without a trailing qualifier) are in the fixed set.
    -   **A chunk is never content-free.** In `_units_for_lines.flush()`
        a piece that contains no letter at all is no longer emitted as a
        chunk of its own (a page counter or stamp that survived the
        furniture pass is not citable evidence). This makes the
        previously reported four-character content-free chunk impossible
        by construction rather than by a special case.
    -   **Page coverage is reported independently of chunks.**
        `ChunkingResult` gained a `pages_without_content` field, filled
        in `chunk_document` from the page list (`text_pages` minus the
        pages any chunk cites), so a page that yielded no citable text is
        still accounted for instead of being inferred from the chunks.
-   [x] Added **10 regression tests** for the confirmed defects and the
    new coverage guarantee: two `NonModuleSectionTests` (a heading hidden
    by a trailing qualifier is still recognised; the trailing-component
    headings are recognised), three `PageFurnitureTests` (a glued
    template label is removed when repeated; a dotted or prefixed date
    stamp is removed when repeated; a short number at the foot of a page
    is never a footer), and a new `PageCoverageTests` class of five
    (a numbers-only page is accounted for but uncited; no chunk is
    content-free; every text page is cited or reported; a numbers-only
    document reports every page uncited; a page whose lines were all
    furniture is reported).
-   [x] **Phase B — three further pilots, reused engine, no new chunker.**
    Added one shared driver `data/processed/pilot_common.py` (extraction,
    chunking, JSONL writing and the whole markdown report live there
    once) plus three thin `run_pilot.py` files that only declare a
    `PilotConfig`. Each new run reads its source PDF read-only, writes
    only its own output directory, and calls the existing
    `chunk_document` — no document-specific chunker was written and no
    existing pilot was overwritten.
-   [x] **Phase B/D — generated and verified (current chunker, two runs
    each, deterministic):**

    | Pilot directory | Source | Pages (text) | Chunks | Sections | chars min/med/max | over limit | hard splits | furniture lines | subjects | chunks w/o module |
    | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
    | `pilot_2022_cse_3rd/` | 2022-3rd syllabus | 88 (88) | **245** | 191 | 78 / 554 / 2000 | 0 | 0 | 15 | 24 | 163 |
    | `pilot_2022_regulations/` | 2022 regulations | 65 (65) | **107** | 1 | 309 / 1645 / 2000 | 0 | 0 | 0 | 0 | 107 |
    | `pilot_2025_regulations/` | 2025 regulations | 41 (41) | **73** | 1 | 249 / 1665 / 1994 | 0 | 0 | 1 | 0 | 73 |
    | `pilot_2022_cse_5th/` (stale) | 2022-5th syllabus | 33 (33) | 94 / **95** | 84 / 85 | — | 0 | 0 | 13 | 9 | 55 |
    | `pilot_2025_sem3/` (stale) | 2025-3rd syllabus | 59 (59) | 127 / **135** | 53 / 74 | — | 0 | 0 | 8 | 9 | 110 |

    Every chunk in every run cites a one-based page inside its document;
    `pages_without_content` and `skipped_pages` are both empty for all
    five; no chunk is content-free; all chunk IDs are distinct. The two
    `pilot_*_sem*` rows show `on-disk / current-chunker` because those two
    pilots predate the Phase A corrections and were deliberately **not**
    overwritten (see the header note); the two regulation runs and the
    2022-3rd run match the current chunker exactly.
-   [x] **Phase C — structure and metadata.** The three syllabi recover
    their subject codes (24 / 9 / 9) and modules and leave course
    outcomes, assessment, resources and practical/lab material in
    unknown-module sections. Both regulations recover **0** subject codes
    and **0** modules, with all 73 / 107 chunks reporting the field
    absent — that is the intended behaviour, because a regulation is not
    a module-based syllabus and no syllabus heading was forced onto it;
    the regulation reports present the document as a single
    `unknown`-subject rollup keyed by page ranges and first lines, with
    headings, clauses, dates and tables left as extracted. The regulatory
    status of both regulation files remains **unverified** (no
    notification number and no effective date appear in either file).
-   [x] **Phase D — independent, read-only verification.** Four
    throwaway probes (in `%TEMP%`, since deleted; nothing added to the
    repository) re-checked the run's own output:
    -   **Page coverage:** for all five documents the accounted pages
        (cited ∪ `pages_without_content` ∪ `skipped_pages`) equal the
        document's pages exactly, with no missing or extra page; all
        pages classify `text`.
    -   **Determinism:** two runs per document produced identical chunk
        text and identical chunk-ID sets.
    -   **Provenance:** no over-limit chunk, no hard split, no
        content-free chunk, no empty page list, no chunk citing a page
        outside 1..N, all chunk IDs distinct. A per-line probe found
        **no source line containing a letter that is absent** from the
        normalised chunk corpus for any of the five documents; the only
        absent lines are letter-free page counters and bold mathematical
        digits (`- 15 -`, `- 37 -`, `- 43 -`, `- 62 -` in the 2022
        regulations; `(𝟏𝟎𝟏+ 𝟏𝟕𝟖)` and `𝟏𝟒+ 𝟐𝟓` in the 2025
        regulations). A word-multiset probe (robust to newline→space
        joining) independently found **0 lettered-word deficits** in all
        five. These two probes are the preservation evidence; the
        comparison normalises whitespace and subtracts the verified
        removed furniture, so it proves **no lettered content is lost**,
        not character-perfect preservation.
    -   **Furniture audit:** 2022-5th 13 lines / 90 occurrences;
        2025-3rd 8 lines / 79 occurrences (the glued template header
        `VTU/PCC-PEC-OEC (3 Credits) template30032026 1` is now removed —
        14 occurrences — where the old pilot had left it in);
        2022-3rd 15 lines / 165 occurrences (both footers `15.09.2023`
        ×50 and `@# 16032024` ×38); 2022 regulations 0; 2025 regulations
        1 line (`22052026` ×41). Every removal needs positional evidence
        **and** repetition on ≥3 pages, and every removal is recorded.
    -   **Resolved observation:** the 2022-3rd document contains both
        `15.09.2023` (the running footer, ×50, removed) and `14.09.2023`
        (46 occurrences, always **mid-page** and therefore retained as
        body content) — a check of the raw lines proved the second date
        is not page furniture and is not dropped.
-   [x] **Phase E — ran the tests for real.**
    `.\.venv\Scripts\python.exe -m unittest tests.test_chunking -v`
    reports `Ran 88 tests ... OK`, and
    `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .`
    reports **`Ran 105 tests ... OK` — 105 executed, 105 passed, 0
    failed, 0 skipped** (88 in `test_chunking.py`, 17 in
    `test_pdf_extract.py`).
-   [x] Recorded what was **not** changed for Task 6: `REQUIREMENTS.md`
    was not edited; `app/ingestion/pdf_extract.py` was not modified; no
    original PDF was written to, moved, renamed, copied, or deleted; no
    package was installed and no dependency downloaded; no external API
    was called; no embeddings, Sentence Transformer execution, FAISS
    indexing, Gemini, Flask, OCR or frontend code was written; no PDF
    beyond the five listed was processed; the two original pilots were
    not overwritten; and nothing was staged, committed, or pushed.


#### Task 7 — embedding and FAISS indexing pipeline

-   [x] **Phase A — a fresh canonical chunk dataset** at
    `data/processed/canonical/` (`chunks.jsonl` + `manifest.json`),
    built by a new `app/ingestion/canonical.py` that drives the *existing*
    extraction and chunker through one shared path — no second chunker and
    no per-document branch. **655 chunks across all five documents**:
    2022-scheme 3rd sem **245**, 2022-scheme 5th sem **95**, 2025-scheme
    3rd sem **135**, 2022 regulations **107**, 2025 regulations **73**.
    Every record carries `document_id`, `version_id` (source SHA-256 prefix),
    `filename` and the one-based `page_numbers`, so each chunk traces back to
    its document revision and original PDF pages. Records are
    `Chunk.to_record()` verbatim; the existing record schema was **not**
    changed. The dataset is a new directory, separate from the five
    historical `pilot_*` directories, which were read but not written to.
    Regenerating it reproduced the same `chunks_sha256`
    (`ce8fbf1dbc887245…`), which is the determinism check.
-   [x] **Phase B — the embedding model, offline.** The project `.venv` has
    PyMuPDF but **not** `faiss` or `sentence-transformers`; the machine's
    global Python 3.12 has both, has `torch` CPU-only
    (`cuda.is_available()` is `False`), and already holds
    `sentence-transformers/all-MiniLM-L6-v2` in the local Hugging Face cache.
    With the user's explicit approval the pipeline was run on the **global
    Python 3.12** with `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`: **no
    package was installed, no model was downloaded and no network request was
    made.** Recorded configuration: `sentence-transformers/all-MiniLM-L6-v2`,
    **384** dimensions, L2-normalised, batch size 32, the same configuration
    for every document and every query (`app/indexing/embedding.py`).
-   [x] **Phase C — the FAISS index** at `data/processed/index/`
    (`index.faiss`, `entries.jsonl`, `manifest.json`), built by a new
    `app/indexing/vector_index.py`: `IndexFlatIP` (exact search; no ANN)
    over the unit-length vectors, so the metric is inner product = **cosine
    similarity**, stated explicitly in the manifest. **655 vectors × 384
    dimensions.** `faiss_id` is the row position in the index and the line
    position in `entries.jsonl`, and is never a document ID or page number;
    each entry is joined to its chunk by `chunk_id`. Entries store the
    citation fields (document ID, version ID, filename, type, scheme,
    semester, subject, module, page numbers) and deliberately **not**
    `chunk_text`, which stays in the canonical dataset. The build is
    restartable (a `BUILDING` marker makes an interrupted build detectable),
    reuses a compatible index instead of rebuilding, and rebuilds cleanly on
    request. `load_index` refuses a missing, incomplete, mis-hashed,
    mis-shaped, wrong-metric or wrong-dimension artifact with a specific
    error. No credentials are stored, and no SQLite schema was touched.
-   [x] **Phase D — a minimal retrieval interface** in
    `app/retrieval/search.py`: `Retriever.search(query, top_k, filters)`
    returns the top-k chunks with their metadata, the metric and a score, plus
    a `citation()` payload. `MetadataFilter` supports `document_type`,
    `scheme`, `semester`, `branch` and `document_ids`; filters are applied
    **before** ranking by masking candidate rows, and a `None` metadata value
    never matches a set filter, so a regulation cannot answer a scheme-filtered
    query. No confidence threshold is applied — a score is reported, not
    interpreted. There is no Gemini, no answer synthesis, no refusal logic,
    no Flask route and no frontend change.
-   [x] **Phase E — tests, and the results actually observed.** 188 tests
    exist; both interpreters were run for real:
    `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` →
    **`Ran 188 tests ... OK (skipped 47)`** (the 47 skips are the tests needing
    `faiss`/`sentence-transformers`), and the global Python 3.12 →
    **`Ran 188 tests ... OK (skipped 21)`** (the 21 skips are the tests needing
    PyMuPDF). New: `tests/test_canonical.py` and `tests/test_indexing.py`,
    the latter using a deterministic, collision-free bag-of-words stand-in
    embedder and a six-chunk synthetic corpus, so routine runs load no model
    and read no PDF. Making `pdf_extract.py` import PyMuPDF **on demand**
    (inside `extract_pdf`, where it was previously imported at module level)
    is what lets the indexing and retrieval stages import in an interpreter
    without the PDF toolkit; it changed no output — the canonical dataset's
    hash was identical before and after.
-   [x] **Independent read-only probe of the real artifacts** (not using
    `app.retrieval`, so a bug there cannot hide a defect): 40 checks, all
    passed. It confirmed 655 entries matching 655 canonical records in order,
    `index.ntotal == 655` and `index.d == 384`, `IndexFlatIP` with
    `faiss.METRIC_INNER_PRODUCT`, per-document counts matching the canonical
    dataset, **180 regulation chunks with `scheme`/`semester`/`branch` all
    `null`** (no metadata invented), byte-identical `entries.jsonl` and a
    byte-identical `index.faiss` on a fresh rebuild, unit-norm vectors, and a
    query run straight through FAISS returning the *Normalization* page of the
    2022-scheme 3rd-semester syllabus first (score 0.7132, 21 ms).
-   [x] Recorded resource use: the cold index build over 655 chunks took
    **≈92 s** (including model load) and a warm rebuild ≈27 s; peak resident
    memory was not instrumented, and embeddings were generated in batches of
    32 through one preallocated array rather than per-document copies.
-   [x] Recorded what was **not** done for Task 7: `REQUIREMENTS.md` was not
    edited; no original PDF was written to, moved, renamed, copied or deleted;
    no historical pilot output was overwritten; no package was installed, no
    model was downloaded and no network request was made; no external API was
    called; no PDF beyond the five listed was processed; no Gemini, Flask,
    OCR, answer-synthesis or frontend code was written; and nothing was
    staged, committed, or pushed.


#### Task 8 — retrieval evaluation (offline, read-only)

-   [x] **A deterministic, grounded evaluation dataset** at
    `data/processed/evaluation/questions.jsonl` — **58 questions**
    (52 answerable, 6 unanswerable) covering every one of the nine
    required categories: `syllabus_fact` 8, `module` 10, `scheme` 5,
    `semester` 5, `document_type` 5, `regulation` 7, `exact_term` 6,
    `semantic` 6, `insufficient_evidence` 6. Every relevance label is
    produced by a **selector that reads the real canonical records**
    (`header`, `module`, `containing`, `by_ids` in
    `app/evaluation/build_dataset.py`), so a label names a chunk that
    exists and a selector that matches nothing fails the build instead
    of quietly producing an unanswerable question. The file is
    deterministic — rebuilding gives the same
    `9555281418f20222…` — and the labels live **only** in this file: a
    test asserts `relevant_chunk_ids` never appears in `chunks.jsonl` or
    `entries.jsonl`, so a judgement cannot leak into what a real query is
    served from.
-   [x] **The metric arithmetic** in `app/evaluation/metrics.py`, stated
    as explicit formulas with no similarity threshold: recall@k =
    \|rel ∩ top_k\| / \|rel\|, precision@k = \|rel ∩ top_k\| / k, hit@k,
    and MRR@k = 1 / rank of the first relevant chunk. An empty relevance
    set is **rejected** rather than scored 0 or 1, `k` must be a positive
    integer, and `mean([])` is `None` rather than a misleading `0.0`.
-   [x] **The runner and report** in `app/evaluation/evaluate.py`, writing
    `data/processed/evaluation/retrieval_eval_report.md` (11 sections,
    reproducible, carrying the questions/canonical/entries SHA-256
    prefixes). Measured over the **existing** index at k = 1, 3, 5, 10 —
    neither the index nor the canonical dataset was changed:

    | Metric | @1 | @3 | @5 | @10 |
    | --- | --- | --- | --- | --- |
    | recall | 0.429 | 0.631 | 0.667 | 0.721 |
    | precision | 0.462 | 0.224 | 0.146 | 0.081 |
    | hit | 0.462 | 0.673 | 0.712 | 0.750 |
    | mrr | 0.462 | 0.551 | 0.561 | 0.566 |

    24 of the 52 answerable questions put a relevant chunk at rank 1; 13
    had their label absent from the top 10; 15 had it present but not at
    rank 1.
-   [x] **Filter and provenance correctness, read off the same run:** 39
    questions applied a metadata filter (`document_type`, `scheme`,
    `semester` and/or `document_ids`) and **0 returned chunks violated
    their filter**; every returned chunk carried a complete citation chain
    — a `chunk_id` namespaced under its own `document_id`, non-empty
    `version_id`/`filename`/`document_type`, at least one one-based page,
    `page_start`/`page_end` equal to the min/max cited page, and
    membership of the canonical dataset — with **0 problems**.
-   [x] **Unanswerable queries measured, not refused.** The six
    unanswerable questions scored 0.3731–0.5132 at rank 1, which
    **overlaps** the correct answerable rank-1 scores (0.4353–0.7645), so
    **no single score threshold separates them on this dataset**. No
    refusal logic and no threshold were implemented; Q7 stays open with
    evidence instead of a guess.
-   [x] **The reported failures were audited against the corpus** before
    being written up. For each of the 13 questions whose label was absent
    from the top 10, the labelled chunk and the returned chunks were read:
    all 13 are genuine dense-retrieval misses — near-identical header
    boilerplate outranking the correct course header (`q-syl-01/05/06/07`,
    `q-dty-03`), a wrong module of the same subject (`q-mod-05`,
    `q-mod-10`), a different subject's module (`q-mod-06`, `q-mod-07`), a
    contents listing instead of the clause (`q-reg-06`), and semantic
    paraphrase failures (`q-sem-01`, `q-sem-05`). The one near-miss
    examined in detail, `q-sem-03`, returned the **eight**-academic-year
    rule for first-semester entry while the question asks about the
    **six**-year lateral-entry rule, so its label was left unchanged. No
    label was edited to improve a score.
-   [x] **Tests.** New `tests/test_evaluation.py` — 64 tests: metric
    arithmetic checked against hand-computed values; dataset validation
    (duplicate ids/queries, unknown category or filter field, a labelled
    chunk absent from the corpus, an unanswerable question carrying
    labels); the builder's selectors; the runner's filter and provenance
    checks driven by a small stand-in retriever; a FAISS-backed
    integration test; and, over the real artifacts, that the builder
    reproduces `questions.jsonl` byte for byte. Both interpreters were run
    for real: `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .`
    → **`Ran 252 tests ... OK (skipped 50)`**, and the global Python 3.12 →
    **`Ran 252 tests ... OK (skipped 21)`**.
-   [x] Recorded what was **not** done for Task 8: `REQUIREMENTS.md` was
    not edited; the FAISS index and the canonical dataset were not
    changed; no package was installed, no model downloaded, no network
    request made and no external API called; no PDF beyond the five was
    processed; no Gemini, Flask, OCR, reranking, query-rewriting, refusal
    or frontend code was written; and nothing was staged, committed, or
    pushed.


### Not yet completed / not verified

-   [ ] `REQUIREMENTS.md` approved **in the document itself**. It is
    frozen as `draft-02` and the user has approved that draft for
    implementation, but Section 12 still reads
    `DRAFT — NOT APPROVED` and is unsigned.
-   [ ] **PDF ingestion complete.** Extraction has been run over the
    five real VTU PDFs in the local dataset and behaved correctly on
    every one of them, chunking has been run over all five, and a
    canonical chunk dataset plus a FAISS index now exist (see Completed).
    Ingestion is still not finished: the chunk metadata is persisted as
    JSONL rather than in the SQLite metadata store the design calls for,
    there is no ingestion-to-index transaction that keeps the two
    atomically consistent, and there is no copy of any source document
    inside the repository, so AC-01, AC-02 and AC-15 are **not**
    satisfied. All five files are digitally generated
    text PDFs, so the `blank` and `image-only` paths were **not**
    exercised by any real document — they remain proven only by locally
    generated fixtures, and no OCR has been written or run.
-   [ ] **The indexing dependencies are not in the project `.venv`.** The
    `.venv` holds PyMuPDF but not `faiss-cpu` or `sentence-transformers`,
    so the embedding and index build currently run on the machine's global
    Python 3.12, which has them. Installing them into `.venv` needs network
    access and has **not** been done or approved. Until that is resolved,
    the pipeline is reproducible but asked to run in two interpreters.
-   [ ] UI design brief/design tokens approved (they exist but have not
    been reviewed or approved).
-   [ ] Interface reviewed on real devices and browsers. Token contrast
    has been measured, and the redesigned behaviour has been exercised
    against a stubbed DOM (see Completed), but **no browser was
    available** for the redesign: rendering, layout, the responsive
    breakpoints at 1280/1024/768px, the drawer and panel overlays, the
    composer keys, the copy-answer clipboard write, and screen-reader
    announcements have not been exercised by a person in a real
    browser.
-   [ ] Visual comparison against the design reference. The Figma
    prototype could not be inspected — the embed is JavaScript-rendered
    and could not be fetched — so the redesign follows the reference's
    known patterns (sidebar with identity and history, welcome screen
    with example prompts, message composer) and makes **no** claim of
    pixel-accurate reproduction.
-   [ ] Example questions connected to real material. The four welcome
    prompts now name a branch and a semester, but nothing is indexed,
    so each one ends in the missing-context state or in placeholder
    answer text. They are not suggested from indexed material (UI-04).
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
-   [ ] Official VTU source PDFs' provenance recorded. Five VTU PDFs
    (two regulation documents and three syllabus sets) are held locally
    in the dataset, but where each came from, its licence, and its
    publication date are still unrecorded. Nothing in the extracted text
    supplies a source URL or a publication date, so those fields are
    left empty in `data/metadata/dataset_inventory.csv` rather than
    guessed.
-   [ ] Chunking validated for **embedding readiness**. Task 6 has now
    run the chunker over **all five** dataset PDFs (three syllabi and two
    regulations) and each has its own pilot directory with a verified
    report (see Completed) — page coverage is complete, output is
    deterministic, no chunk exceeds the size limit, and no lettered
    source content is missing. What is **still** missing before embedding:
    the two original syllabus pilots (`pilot_2022_cse_5th/`,
    `pilot_2025_sem3/`) were produced by the chunker *before* the Task 6
    corrections and are stale (94 vs 95 and 127 vs 135 chunks); they were
    left in place rather than overwritten, so embeddings must be built
    from a **fresh** run of the corrected chunker, not from those two
    directories. The regulatory status of both regulation documents is
    unverified (no notification number, no effective date in either
    file), so they must not be presented as approved or in force. The
    non-module heading set and the repeated-furniture shapes are still a
    **fixed** list read from these documents, so a differently worded
    heading or a different header/footer on another document is not
    recognised and is left in place rather than removed. Chunks are
    persisted as a canonical JSONL dataset (655 chunks) with a FAISS index
    built over it, but the SQLite metadata store the design calls for does
    not exist, no Gemini or Flask code exists, and no document has
    been copied into the project.
-   [ ] Chunk size and overlap values chosen. `REQUIREMENTS.md` Q4 still
    lists the approved maximum chunk size and token budget as pending.
    The pilot used 500 tokens of target with 75 tokens of overlap
    through a 4-characters-per-token approximation; those are parameters
    of the pilot run, not approved constants, and the approximation is
    not a tokenizer measurement.
-   [ ] Metadata persistence implemented **in the designed form**:
    chunks are persisted as `data/processed/canonical/chunks.jsonl` and the
    index metadata as `data/processed/index/entries.jsonl`, not in a SQLite
    store, and nothing keeps the two atomically consistent.
-   [x] **FAISS indexing and stable ID mapping implemented** — an exact
    `IndexFlatIP` index over 655 unit-length vectors, with `faiss_id`
    joining each vector to its `chunk_id`, document ID, version ID,
    filename and original PDF pages (`data/processed/index/`).
-   [x] **Retrieval evaluation dataset and baseline created** (Task 8) —
    a 58-question judged dataset at
    `data/processed/evaluation/questions.jsonl` and a reproducible report
    at `data/processed/evaluation/retrieval_eval_report.md`, measured over
    the existing index: recall@10 **0.721**, MRR@10 **0.566**,
    precision@1 **0.462**, with **0 filter violations** and **0 provenance
    problems**. The measurement layer is read-only; neither the index nor
    the canonical dataset was changed. The retrieval **range** and any
    score **threshold** nonetheless remain open (Q7): the unanswerable and
    the correct answerable rank-1 scores overlap, so no threshold is
    justified by this evidence.
-   [ ] Gemini generation and citation validation implemented.
-   [ ] Flask API implemented, and the frontend shell connected to it
    (the shell currently runs on fixture data only).
-   [ ] Security, accessibility, accuracy and deployment checks
    completed.

## 9. Current state / next task

**Current phase:** Phase 2 --- the PDF extraction foundation is
implemented, verified against local fixtures and run over the five real
VTU PDFs held in the local dataset, page-aware chunking is
implemented and validated with verified pilots on **all five** of them
(three syllabi and two regulation documents), and a canonical chunk
dataset with a FAISS index now exists over those five documents.
Requirements are
frozen as `draft-02` and approved by the user for implementation.
**Implementation status:** There are now five independent pieces of
work.
(1) The frontend shell is static files running on fixture data
(`app/static/js/mock-data.js`), with dark and light themes, the five
interface states, marked-up tables, the citation side panel with an
honest preview-unavailable fallback, and the redesigned sidebar
(identity, New chat, section navigation, session Recent list, academic
context, profile disclosure), welcome screen with example questions,
copy-answer action, and empty Syllabus and Circulars views. It is not
connected to a backend and contains no real VTU content. (2)
`app/ingestion/pdf_extract.py` extracts text from a local PDF page by
page, keeps each page's original one-based number, and classifies each
page as `text`, `blank`, `image-only`, or `extraction failure`. (3)
`app/ingestion/chunking.py` turns one extraction result into
page-traceable chunks with deterministic IDs: it splits on detected
subject/module headings and paragraph and sentence boundaries before
applying a size limit, hard-splits a block that is still too large and
records that it did, keeps `page_numbers`/`page_start`/`page_end` on
every chunk, stores a subject or module only when the document
states it or the caller supplies it, opens an unknown-module section for
material the document does not assign to a module, never emits a
letter-free chunk, reports page coverage independently through
`pages_without_content`, and removes repeated page furniture only where
positional and repetition evidence agree, recording every removal. (4)
`app/ingestion/canonical.py` runs the five documents through (2) and (3)
into one canonical dataset at `data/processed/canonical/` — 655 chunks —
and (5) `app/indexing/` embeds those chunks with
`sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, L2-normalised)
into an exact `IndexFlatIP` FAISS index at `data/processed/index/`, with
`app/retrieval/search.py` offering a validation-only top-k search with
metadata filtering. None
of the pieces contains
Gemini, Flask, or OCR code, and (4)/(5) contain no answer generation.
There is no backend
server, no SQLite metadata persistence, and no real PDF copied into the
project repository. The registry of the five verified documents is
`data/metadata/dataset_inventory.csv`.
**Verified in the Task 6 session:** the chunker was corrected
in three small general-purpose ways and then **run over all five dataset
PDFs**. Each document now has its own pilot directory under
`data/processed/` with a `chunks.jsonl` and a `chunk_quality_report.md`:
the three new ones are `pilot_2022_cse_3rd/` (**245 chunks / 191
sections**), `pilot_2022_regulations/` (**107 chunks / 1 section**) and
`pilot_2025_regulations/` (**73 chunks / 1 section**), generated through
one shared `pilot_common.py` driver so no runner code was duplicated.
The two regulation documents recover **0** subject codes and **0**
modules and are reported as a single honest `unknown`-subject rollup —
no syllabus metadata was forced onto them. For every document: page
coverage is complete (cited ∪ without-content ∪ skipped == all pages),
all pages classify `text`, no chunk exceeds the 2,000-character limit,
there are no hard splits and no content-free chunks, all chunk IDs are
distinct, and two runs per document are identical. Independent read-only
probes found **no lettered source line and no lettered word missing** in
any of the five documents (whitespace-normalised, furniture subtracted),
and the 2022-3rd document's `14.09.2023` was proved to be mid-page body
text rather than furniture and is retained. Furniture removals were: 13
lines / 90 occurrences (2022-5th), 8 lines / 79 occurrences (2025-3rd,
including the glued template header), 15 lines / 165 occurrences
(2022-3rd), 0 (2022 regulations) and 1 line / 41 occurrences (2025
regulations). The complete suite reports `Ran 105 tests ... OK` (105
passed, 0 failed, 0 skipped: 88 chunking, 17 extraction). The earlier
extraction validation stands: all 286 pages across the five dataset files
classified `text`, no `blank`/`image-only`/`extraction failure` page, no
U+FFFD, one-based numbering intact, per-file figures in
`data/metadata/dataset_inventory.csv`. Nothing was staged, committed, or
pushed. The redesigned frontend was earlier checked with `node --check`,
an id/class cross-check, and 41 stub-DOM behaviour checks; **no browser
was available, so nothing about rendering or layout has been visually
confirmed, and no Figma prototype could be inspected.**
**Verified in the latest session (Task 7):** the five documents were run
through the existing extraction and corrected chunker into **one
canonical dataset** at `data/processed/canonical/` — **655 chunks**, no
stale pilot output — whose `chunks_sha256` (`ce8fbf1dbc887245…`) was
reproduced exactly on a second run. Those chunks were embedded with
`sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, L2-normalised)
and indexed into an exact `IndexFlatIP` FAISS index of **655 vectors ×
384 dimensions** under `data/processed/index/`, where the metric is inner
product = cosine similarity and `faiss_id` is a row position that joins a
vector to its `chunk_id`, document ID, version ID, filename and one-based
PDF pages. The run was entirely offline (`HF_HUB_OFFLINE=1`,
`TRANSFORMERS_OFFLINE=1`): no package was installed, no model downloaded
and no network request made. A 40-check independent read-only probe of
the artifacts passed, including 180 regulation chunks with
`scheme`/`semester`/`branch` all `null`, and a byte-identical
`index.faiss` and `entries.jsonl` on a fresh rebuild. Both interpreters
were run for real: `.venv` → `Ran 188 tests ... OK (skipped 47)`, global
Python 3.12 → `Ran 188 tests ... OK (skipped 21)`. The cold build took
≈92 s (reuse: no rebuild; warm rebuild ≈27 s). Nothing was staged,
committed, or pushed, and Gemini, Flask, OCR and frontend work was not
started.
**Verified in the latest session (Task 8):** retrieval quality has now been
measured. A deterministic **58-question** judged dataset (52 answerable +
6 unanswerable, spanning all nine categories) was built **offline** from
the existing canonical chunks at
`data/processed/evaluation/questions.jsonl`; every label is bound to a
real canonical `chunk_id` and to one-based PDF pages, and no label was
edited to change a score. It was run against the **existing** index —
neither the index nor the canonical dataset was modified — and the
reproducible report is `data/processed/evaluation/retrieval_eval_report.md`:
recall@10 **0.721**, MRR@10 **0.566**, precision@1 **0.462**, with
**0 filter violations** across 39 filtered questions and **0 provenance
problems** across every returned chunk. The evaluation test module (64
tests) passes and both interpreters were run for real: `.venv` →
`Ran 252 tests ... OK (skipped 50)`, global Python 3.12 →
`Ran 252 tests ... OK (skipped 21)`. Nothing was staged, committed, or
pushed, and Gemini, Flask, OCR and frontend work was not started.
**Next task:** `REQUIREMENTS.md` Q7 still leaves the retrieval **range**
and any score **threshold** open, and this evaluation **justifies no
threshold**: the unanswerable and the correct answerable rank-1 scores
overlap, so no cut-off can separate them from this evidence. Then
record the provenance and licence
of the five dataset documents, since no source URL or publication date is
present in any of them. Confirm the regulatory status of both regulation
files from an authoritative source before they are presented as current.
Pin dependencies in a dependency file, and decide whether
`faiss-cpu`/`sentence-transformers` may be installed into the project
`.venv` (they are not there today, so indexing currently runs on the
global interpreter). The source PDFs stay outside the
repository until there is an explicit decision about how documents are
held. A real-browser review of the redesigned interface (desktop and
mobile widths, both themes, keyboard only) also remains outstanding. Do
not connect anything to the network before the ingestion and provenance
pipeline has been tested on a few representative documents.

**Open decisions**

-   **What the extraction tests do not prove.** Every *test fixture* is
    generated locally by PyMuPDF. Real documents have now been run
    through the module — five VTU PDFs, all digital text, all fully
    readable — but that set contains no scan, no filled form, and no
    blank page, so true scans, forms, and unusual encodings remain
    untested. The blank-versus-image-only rule also still rests on
    PyMuPDF reporting image content; a page whose only content is vector
    drawing is reported `blank` and that remains a stated limitation.
-   **The regulatory status of `B.E.B.Tech2025.pdf`.** Its cover says
    the regulations govern the UG B.E./B.Tech. programmes from 2025, but
    the document states no notification number and no effective date
    (only that it starts on "the date of their notification"), and its
    embedded PDF metadata dates the file 2026-05-22. It must not be
    treated as an approved, notified, or in-force regulation on the
    strength of its filename. This needs confirmation from an
    authoritative source before it is ingested, and it is one of the
    documents most likely to be cited, so the answer matters.
-   **All five real PDFs are digital text PDFs.** No `blank`,
    `image-only`, or `extraction failure` page occurred in the dataset,
    so those three paths of the four-way classification are still proven
    only by synthetic fixtures. A genuinely scanned circular will be the
    first real test of the `image-only` path, and is the point at which
    OCR becomes relevant (D6, OCR deferred).
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
    can be exercised until a real document exists. The four welcome
    example questions are the one place text that looks like a real
    request appears; they are asked through the normal path and return
    placeholder answer text, so they state no VTU fact.
-   **Whether "Clear conversation" should also empty the Recent list.**
    It currently clears the transcript, the pending question, the last
    question, and the citation source maps, but keeps the session's
    question list — on the grounds that the list is history rather than
    part of the conversation. Either behaviour is defensible; this was
    a deliberate choice, not an oversight.
-   **Syllabus and Circulars are honest empty sections.** They exist so
    the navigation is real rather than decorative, but nothing is
    indexed, so each shows a notice instead of a list. Whether these
    sections should exist before ingestion is implemented at all is a
    product decision.
-   **Whether the theme choice is remembered.** The toggle works, but the
    selection is forgotten on reload because persisting it would need
    browser storage, which the requirements do not currently authorise.
    Requires a decision, not a code change.
-   **Whether control borders are darkened.** `--border` and
    `--border-strong` measure 1.1:1–1.6:1 against their surfaces, below
    the 3:1 non-text threshold. Controls remain identifiable by their
    labels and fills, so this may be acceptable, but it is an explicit
    decision rather than an oversight.
