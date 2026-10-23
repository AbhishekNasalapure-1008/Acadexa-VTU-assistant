# VTU Assistant --- Project Context & Progress

> **Purpose:** The single source of truth for the VTU Assistant project.
> Read this file at the start of a new AI coding session before doing
> project work. Update it after each completed task. **Last updated:**
> 2026-10-21 **Status:** Planning, plus the frontend shell implemented.
> `REQUIREMENTS.md` exists as an unapproved draft (`draft-01`). The
> shell is static files running on fixture data, now with dark and light
> themes, the five interface states, table rendering, and the citation
> side panel. There is no backend, no ingestion, and no real document
> yet.

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
-   [x] Wrote an unapproved requirements draft (`REQUIREMENTS.md`,
    revision `draft-01`) covering problem and users, MVP scope and
    deferrals, functional and non-functional requirements,
    scheme/missing-context behaviour, ingestion and page-citation
    requirements, retrieval and refusal behaviour, source policy,
    acceptance criteria, and the interface. **Not approved**, and seven
    review revisions are proposed but not yet written into it.
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

### Not yet completed / not verified

-   [ ] Requirements document and acceptance criteria approved
    (`REQUIREMENTS.md` on disk is still `draft-01`).
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
-   [ ] Python virtual environment and dependencies set up.
-   [ ] Official VTU source PDFs collected and their permissions/source
    recorded.
-   [ ] PDF ingestion and page-aware chunking implemented and tested.
-   [ ] Metadata persistence implemented.
-   [ ] FAISS indexing and stable ID mapping implemented.
-   [ ] Retrieval baseline and evaluation dataset created.
-   [ ] Gemini generation and citation validation implemented.
-   [ ] Flask API implemented, and the frontend shell connected to it
    (the shell currently runs on fixture data only).
-   [ ] Security, accessibility, accuracy and deployment checks
    completed.

## 9. Current state / next task

**Current phase:** Phase 1 --- planning, with the frontend shell
implemented.
**Implementation status:** The frontend shell is implemented as static
files and runs against fixture data (`app/static/js/mock-data.js`). It
has dark and light themes, the five interface states, marked-up tables,
and the citation side panel with an honest preview-unavailable fallback.
It is not connected to a backend, has not been reviewed or approved, and
contains no university content. No ingestion, embedding, retrieval, or
generation code exists, and no real PDF has been handled yet.
**Verified this session:** the checks listed under Completed ---
`node --check` on the three JavaScript files, element-id consistency
between `app.js` and `index.html`, CSS variable resolution, absence of
literal colours in `app.css`, absence of external requests, secrets, and
browser storage, data-seam completeness, absence of `innerHTML`/`eval`,
serving of all six files over a local HTTP server, a clean page load in a
browser preview, and measured WCAG contrast ratios for every token pair
in both themes. Interactive behaviour (theme toggle, sidebar drawer,
composer keys, state transitions, citations, panel) was **not** executed
by a person, and screen-reader behaviour was **not** checked. Nothing has
been run against a real document.
**Next task:** Review the running shell against the manual checklist and
settle the open decisions below. Then build the PDF ingestion and
provenance pipeline, and do not connect anything to the network before
that pipeline has been tested on a few representative, lawfully sourced
documents.

**Open decisions**

-   **How a cited PDF page is shown.** The approved stack contains no
    PDF renderer. The side panel currently embeds the browser's own PDF
    viewer in an iframe, and JavaScript cannot detect a host that
    refuses framing (`X-Frame-Options`), so a blocked embed would appear
    as a blank panel. Unresolved; the fallback path is what works today.
-   **Whether the seven requirements revisions are applied.** Logical
    document identity versus file version/content hash, page
    classification (blank versus image-only versus extraction failure),
    relaxing AC-04 to recall within an agreed retrieval range, FR-CTX-03
    reconciled with Section 5.2, citation fallback behaviour, retrieved
    document text treated as untrusted evidence, and the public-release
    gate. Proposed, not written into `REQUIREMENTS.md`.
-   **Fixture content and naming.** Every fixture `source_url` is null
    and every fixture title says it is a placeholder, so inventing VTU
    content is avoided. Only the unavailable-preview path can be
    exercised until a real document exists.
-   **Whether `REQUIREMENTS.md` needs a new revision marker.** Two rows
    were edited while the header still says `draft-01`. Bumping the
    revision is an approval decision, so it was left alone; the
    alternative is that a changed draft keeps its old revision label.
-   **Whether the theme choice is remembered.** The toggle works, but the
    selection is forgotten on reload because persisting it would need
    browser storage, which the requirements do not currently authorise.
    Requires a decision, not a code change.
-   **Whether control borders are darkened.** `--border` and
    `--border-strong` measure 1.1:1–1.6:1 against their surfaces, below
    the 3:1 non-text threshold. Controls remain identifiable by their
    labels and fills, so this may be acceptable, but it is an explicit
    decision rather than an oversight.
