# VTU Assistant — Requirements Specification

> **Status: DRAFT — NOT APPROVED.**
> This document is a proposal for review. No requirement in it is agreed
> until the approval record in Section 12 is signed off.
>
> **Source of truth:** `PROJECT_CONTEXT.md`. This draft derives from it and
> does not override it. Where this document is silent, `PROJECT_CONTEXT.md`
> governs. Where the two conflict, `PROJECT_CONTEXT.md` wins and this file
> must be corrected.
>
> **Scope of this draft:** planning only. No application code, dataset
> collection, or package installation is authorised by this document.
>
> **Date:** 2026-10-22
> **Revision:** draft-02
> **Revision note:** draft-02 incorporates nine review corrections —
> logical document identity versus file version, PDF page classification,
> the AC-04 retrieval criterion, context resolution, citation fallback,
> retrieved-text security, the public-release gate, citation version
> integrity, and ingestion consistency and recovery. Incorporating a
> correction is not approving it.
> **Traceability:** section-level cross-references to `PROJECT_CONTEXT.md`
> are given as §PC-n.

---

## 1. Problem statement and target users

### 1.1 Problem statement

VTU students need to locate specific academic facts — what a module covers,
what a subject's credits are, which regulation a subject belongs to, what an
exam rule states — inside long, formally structured PDF documents such as
syllabus books, circulars, and academic regulations. Reading these documents
manually is slow, and search inside a PDF returns raw text hits without
explaining them in the context of the student's scheme, branch, and semester.

General-purpose chatbots are a poor substitute, because they answer from
memory and can state syllabus or regulatory details that are outdated,
belong to a different scheme, or are simply wrong. A student has no reliable
way to tell a correct answer from a confident guess.

This project builds an assistant that answers only from indexed, approved
documents, and shows the document and original PDF page behind every claim.
The value of the product is not conversation for its own sake; it is
**traceable academic accuracy**.

### 1.2 Target users

| User | Primary need | Failure that hurts them most |
|---|---|---|
| **VTU undergraduate student (primary)** | Find syllabus, credit, and regulation facts for their own scheme, branch, and semester | Receiving an answer from the wrong scheme, or an invented one |
| **Student revising or checking eligibility** | Confirm a specific clause (exam rule, eligibility, credit requirement) | A plausible answer with no source to verify against |
| **Project maintainer / reviewer (secondary)** | Add documents, confirm the index is current, audit answer quality | Not being able to tell which document version is indexed |

**Primary user for the MVP is the VTU CSE student on the 2022 scheme** (§PC-3).
Later schemes and branches are a data-model concern for the MVP, not a launch
requirement.

### 1.3 Non-goals

- The assistant is **not** an official VTU service and must not imply that it
  is (§PC-1).
- It is **not** a replacement for the official VTU website or the authoritative
  PDF. It is a way to find and understand those documents faster.
- It does **not** answer questions outside the indexed material.

---

## 2. MVP scope and deferred features

### 2.1 In scope for the MVP

| # | Capability | Notes |
|---|---|---|
| M1 | Page-aware PDF ingestion for a small set of approved VTU PDFs | 2–3 representative documents first (§PC-9) |
| M2 | Metadata persistence in SQLite | `PROJECT_CONTEXT.md` §PC-2 prefers SQLite over JSON |
| M3 | FAISS vector index with an explicit, stable ID → metadata → page mapping | §PC-5 |
| M4 | Dense retrieval baseline with metadata filtering | §PC-5 |
| M5 | Grounded answer generation via Gemini, from retrieved evidence only | §PC-5 |
| M6 | Page-level citations in every answer that makes a factual claim | §PC-1, §PC-5 |
| M7 | Explicit refusal when evidence is absent or confidence is inadequate | §PC-1, §PC-5 |
| M8 | Scheme / branch / semester context selection, visible in the interface | §PC-4, §PC-5 |
| M9 | Single-turn chat flow: ask, answer, cite, start a new question | §PC-4 |
| M10 | Flask API plus HTML/CSS/vanilla-JS frontend | §PC-2 |

### 2.2 Explicitly deferred (not in the MVP)

| # | Deferred item | Why deferred | Trigger to revisit |
|---|---|---|---|
| D1 | Conversation history persistence | §PC-4: "only after persistence is implemented" | After M2 and M9 are verified working |
| D2 | Browse Syllabus, Saved Answers, admin/ingestion-status screens | §PC-4: do not build before the core RAG flow works | After MVP acceptance criteria pass |
| D3 | Remembering the chosen theme between sessions | The theme toggle itself was moved into scope and implemented in the frontend shell; storing the choice would need browser storage, which §PC-4 does not authorise | If the user approves browser storage |
| D4 | Multi-scheme and multi-branch coverage | §PC-3: design for it, do not ingest for it yet | After ingestion and retrieval are validated on one scheme |
| D5 | Hybrid lexical + dense retrieval and reranking | §PC-5: evaluate whether it improves results | After a measured dense baseline exists (M4) |
| D6 | Scanned-PDF / OCR support | §PC-5: handle as a separately identified capability | When a scan-only document is actually needed |
| D7 | Large-scale dataset ingestion | §PC-3: expand only after small-set tests pass | After M1–M8 accepted |
| D8 | Circulars, notices, exam rules as document types | §PC-3: potential future types | After syllabus type is stable |
| D9 | GSAP motion polish | §PC-2: only where it improves usability | After M10 usability review |
| D10 | Public deployment and release | §PC-1: subject to review/approval | After the release gate in §8.3 passes and explicit release approval is recorded |

### 2.3 Constraints on this phase

- No large dataset is collected before the ingestion and provenance pipeline is
  tested on a few representative documents (§PC-3, §PC-9).
- Technology choices are fixed by §PC-2. This document does not add, replace, or
  upgrade any of them.

---

## 3. Functional requirements

Requirement identifiers are stable and are referenced by the acceptance criteria
in Section 9. Priority uses MoSCoW: **M**ust, **S**hould, **C**ould.

### 3.1 Conversation and session

| ID | Pri | Requirement |
|---|---|---|
| FR-CONV-01 | M | The user can submit a question and receive one answer in a single exchange. |
| FR-CONV-02 | M | The user can start a new conversation that clears prior context, without reloading the application. |
| FR-CONV-03 | S | The system offers suggested academic prompts that are relevant to the selected scheme/branch/semester. |
| FR-CONV-04 | S | The interface exposes the four states named in §PC-4 — loading, empty, error, and no-evidence — plus the context-missing state required by FR-CTX-03 and designed in UI-05. All five are distinct and switchable without a page reload. |
| FR-CONV-05 | C | Conversation history survives a page reload once D1 is implemented. |

### 3.2 Academic context

| ID | Pri | Requirement |
|---|---|---|
| FR-CTX-01 | M | The user can select scheme, branch, and semester. The current selection is always visible while chatting (§PC-4). |
| FR-CTX-02 | M | The selected context is applied as a retrieval filter, not as an after-the-fact re-sort. |
| FR-CTX-03 | M | If context needed for the question is missing, partial, or conflicting, and resolving it could change the answer, the system asks a clarifying question instead of guessing. If it could not change the answer, the system proceeds and states the assumption it made and that no context filter was applied (§PC-5, §5.2). |
| FR-CTX-04 | S | Context changes are reflected in the next answer without restarting the application. |

### 3.3 Ingestion and metadata

| ID | Pri | Requirement |
|---|---|---|
| FR-ING-01 | M | Text is extracted page by page with PyMuPDF; each page retains its original one-based number (§PC-5). |
| FR-ING-02 | M | Document identity is two-tiered. `document_id` identifies the logical work — for example, the 2022-scheme syllabus for one subject — and does not change when the file is revised. `version_id` identifies one specific file revision of that work. Revising a document never creates a second logical document. |
| FR-ING-03 | M | Documents are chunked by structure (module/unit/subject headings) where that structure exists, then subject to a maximum chunk size; oversized blocks are hard-split safely (§PC-5). |
| FR-ING-04 | M | Every chunk stores its parent document ID and page provenance, using `page_start`/`page_end` when it spans pages (§PC-5). |
| FR-ING-05 | M | Every extracted page is classified and recorded as **text**, **blank**, **image-only**, or **extraction failure**. Only text-classified pages supply content to the index. A blank page, an image-only page, and an extraction failure are separate outcomes and are never collapsed into one another or stored as valid empty text (§PC-5, §6.1 ING-06). |
| FR-ING-06 | M | The full metadata set in §3.4 is persisted for each document and chunk where the value is available. |
| FR-ING-07 | S | Re-running ingestion on content that is already stored leaves the stored state unchanged: no duplicate document records, chunks, or vectors (FR-ING-10). |
| FR-ING-08 | S | The ingestion run reports, per document, how many pages and chunks were stored and which metadata fields were unavailable. |
| FR-ING-09 | M | Every ingested version records a content hash of the file it was built from, so identical content is recognisable without re-extracting or re-embedding it. |
| FR-ING-10 | M | Re-ingesting byte-identical content for the same logical document is a no-op: no new `version_id`, no new chunks, no new vectors. The run reports that nothing changed. |
| FR-ING-11 | M | Content that differs from the stored version creates a new `version_id` and records which version it supersedes. The previous version is retained rather than overwritten, because existing citations must continue to resolve to it (FR-CITE-06). |
| FR-ING-12 | S | Each ingestion run reports, per document, whether the outcome was new, unchanged, superseding, or failed. |

### 3.4 Chunk metadata

| ID | Pri | Requirement |
|---|---|---|
| FR-META-01 | M | Each chunk record carries: `chunk_id`, `document_id`, `version_id`, `filename`, `source_url` (when available), `scheme`, `branch`, `semester`, `subject_code`, `module`, `document_type`, `effective_date` (when verified), `page_number` or `page_start`/`page_end`, `chunk_text`, and `faiss_id`. |
| FR-META-02 | M | Fields that are genuinely unknown are stored as absent, never as a fabricated default. An unverified `effective_date` stays empty rather than being estimated. |
| FR-META-03 | M | `faiss_id` is the single link between the vector index and the metadata record, as required by §PC-5. |
| FR-META-04 | S | The metadata schema is designed so that additional schemes, branches, and document types can be added without restructuring existing records (§PC-3). |
| FR-META-05 | M | Version-level facts — content hash, ingestion timestamp, source, and supersession status — are recorded once per version and referenced through `version_id`, rather than duplicated across that version's chunk records. |
| FR-META-06 | M | Supersession is recorded as an explicit link between versions. Recording a newer version never rewrites, redirects, or deletes the metadata of the version it supersedes (FR-CITE-06, CIT-11). |

### 3.5 Vector index

| ID | Pri | Requirement |
|---|---|---|
| FR-IDX-01 | M | The mapping FAISS vector ID → metadata record → document and original page is explicit and stable. A FAISS position is never treated as a document ID or a page number (§PC-5). |
| FR-IDX-02 | M | Embeddings are L2-normalised when inner-product similarity is used to represent cosine similarity (§PC-5). |
| FR-IDX-03 | M | The index and its metadata are persisted and re-loaded consistently, so a restart does not change answer citations. |
| FR-IDX-04 | S | Index rebuild and incremental update behaviour is tested, not assumed (§PC-5). |
| FR-IDX-05 | M | An index is only made queryable once the metadata update it depends on has completed. A partially built or mismatched index is never served as current (§6.5). |

### 3.6 Retrieval and generation

| ID | Pri | Requirement |
|---|---|---|
| FR-RET-01 | M | Retrieval applies metadata filters for the selected context before ranking (§PC-5). |
| FR-RET-02 | M | The MVP ships a dense retrieval baseline; hybrid/reranked retrieval is only added if measured evidence shows improvement (D5). |
| FR-RET-03 | M | Assembly of context for generation is bounded by relevance and token budget. Passing all chunks of a large document is not permitted (§PC-5). |
| FR-RET-04 | M | Default retrieval excludes superseded document versions. Retrieving a superseded version is possible only through an explicit, documented historical lookup, which is not part of the MVP (§6.4 CIT-11, Q8). |
| FR-GEN-01 | M | Gemini receives only retrieved evidence, and every evidence block is labelled with filename and page (§PC-5). |
| FR-GEN-02 | M | The prompt requires that citations refer only to supplied evidence (§PC-5). |
| FR-GEN-03 | M | Output is rendered as readable prose with headings and lists where appropriate (§PC-4). |
| FR-GEN-04 | M | When no relevant evidence is found, the system states the answer is not available in the indexed material and does not guess (§PC-1, §PC-5). |
| FR-GEN-05 | M | Retrieved document text is supplied to the model as untrusted evidence, clearly separated from instructions. Text inside a retrieved document that reads as an instruction is data to be reported, never a directive to be followed (§4.2 NFR-SEC-06, NFR-SEC-07). |

### 3.7 Citations

| ID | Pri | Requirement |
|---|---|---|
| FR-CITE-01 | M | Every factual claim in an answer is attributable to at least one cited source, and citation labels are structurally correct — derived from stored metadata, not from text the model produced. |
| FR-CITE-02 | M | Each citation shows document name and page number (§PC-4). |
| FR-CITE-03 | M | A citation can be opened or previewed at the cited PDF page where the recorded source permits it. Where it does not — no source URL, an unreachable or framing-blocked source, or a viewer that ignores page fragments — the citation still shows the exact document identity and original page alongside an honest "preview unavailable" state (FR-CITE-07, §6.4). |
| FR-CITE-04 | M | Citations that do not correspond to supplied evidence are rejected, and the answer is regenerated or downgraded to a refusal. |
| FR-CITE-05 | S | Citations are displayed prominently rather than as low-contrast footnotes (Section 10). |
| FR-CITE-06 | M | A citation binds to `document_id`, `version_id`, and the original page it was drawn from. Superseding a document never redirects an existing citation to the replacement version, and never changes the page it points at (FR-ING-11, FR-META-06, CIT-11). |
| FR-CITE-07 | M | When a preview is impossible or fails, the interface states that it is unavailable while still showing the recorded document identity and original page number. It never substitutes another document, another version, another URL, or an inferred page destination (CIT-07, CIT-08, CIT-09). |

### 3.8 Interface

| ID | Pri | Requirement |
|---|---|---|
| FR-UI-01 | M | Layout follows the ChatGPT-inspired direction in §PC-4: collapsible sidebar, new-chat action, centred chat area and composer. |
| FR-UI-02 | M | Branding is original. No OpenAI or VTU affiliation is implied (§PC-1). |
| FR-UI-03 | M | The interface is responsive on laptops and phones (§PC-4). |
| FR-UI-04 | M | Keyboard navigation, readable contrast, and clear focus states are present (§PC-4). |
| FR-UI-05 | S | Dark theme is the default in a fresh session, and a light theme is available through a visible, keyboard-accessible toggle that switches the whole interface without a page reload. The chosen theme is not persisted between sessions (D3). |

### 3.9 Operations

| ID | Pri | Requirement |
|---|---|---|
| FR-OPS-01 | M | Server-side configuration (including the Gemini API key) is read from environment configuration and never shipped to the browser (§PC-1). |
| FR-OPS-02 | S | The maintainer can see which source documents are indexed and when they were last updated. |
| FR-OPS-03 | C | Ingestion status is exposed in an admin view (D2). |

---

## 4. Non-functional requirements

### 4.1 Accuracy

| ID | Requirement |
|---|---|
| NFR-ACC-01 | A factual answer must be supported by retrieved evidence. Unsupported confident answers are treated as defects, not acceptable variance. |
| NFR-ACC-02 | Answers must not mix content from a scheme, branch, or semester other than the selected context. |
| NFR-ACC-03 | Grounding and citation correctness are tested directly (Section 9), not inferred from answers sounding plausible (§PC-5). |
| NFR-ACC-04 | Where sources conflict or evidence is incomplete, the system surfaces the uncertainty rather than silently choosing one. |

### 4.2 Security

| ID | Requirement |
|---|---|
| NFR-SEC-01 | API keys and database credentials are stored server-side only, excluded from version control, and never embedded in delivered frontend assets (§PC-1). |
| NFR-SEC-02 | No default or example credentials are shipped. This requirement exists specifically because the reviewed reference project used a default database password (§PC-6). |
| NFR-SEC-03 | Model output and user input are escaped before rendering. Model output is never injected into the page as raw HTML. |
| NFR-SEC-04 | All database access uses parameterised queries. |
| NFR-SEC-05 | User input length and request rate are bounded to limit accidental or deliberate abuse. |
| NFR-SEC-06 | Retrieved document text is treated as untrusted evidence. It is never merged into the instruction channel, and it cannot grant permissions, change the task, or override the system instructions, security rules, or refusal behaviour (FR-GEN-05). |
| NFR-SEC-07 | Text inside a retrieved document that is phrased as an instruction, a role change, or a request to reveal configuration is treated as document content to be reported. It never causes the system to act on behalf of the document. |

### 4.3 Privacy

| ID | Requirement |
|---|---|
| NFR-PRV-01 | The MVP does not require user accounts and does not ask for personal information. |
| NFR-PRV-02 | Questions sent to the Gemini API are transmitted only to the extent required to produce an answer, and this is disclosed to users. |
| NFR-PRV-03 | If conversation logging is added later, it is disclosed before it is enabled, and the retention period is stated. |
| NFR-PRV-04 | Indexed documents are public academic materials; no student or personal data is ingested. |

### 4.4 Accessibility

| ID | Requirement |
|---|---|
| NFR-A11Y-01 | The core flow is fully keyboard operable, including context selection, question submission, and opening a citation. |
| NFR-A11Y-02 | Text and interactive elements meet WCAG 2.1 AA contrast, and focus indicators are clearly visible. |
| NFR-A11Y-03 | Structure uses semantic HTML with correct heading order and accessible names for controls. |
| NFR-A11Y-04 | Loading, error, and no-evidence states are announced to assistive technology rather than conveyed by colour alone. |

### 4.5 Responsive design

| ID | Requirement |
|---|---|
| NFR-RSP-01 | The layout is usable from small phone widths through laptop widths without horizontal scrolling of the conversation. |
| NFR-RSP-02 | Citation content remains readable and openable on small screens. |
| NFR-RSP-03 | The interface is verified in at least two browser engines on desktop and one mobile viewport. |

### 4.6 Performance

Thresholds below are **proposed defaults for approval**, not measured facts. They
must be replaced with agreed targets or adjusted after baseline measurement.

| ID | Requirement | Proposed default (needs approval) |
|---|---|---|
| NFR-PERF-01 | Answer latency for a single question, excluding PDF download | p95 within an agreed bound; target to be confirmed |
| NFR-PERF-02 | Retrieval is bounded by token budget, not document size | Context capped by configured token limit (§PC-5) |
| NFR-PERF-03 | Index load on application start does not block the first question beyond an agreed bound | to be confirmed |
| NFR-PERF-04 | Ingestion of the initial 2–3 documents completes within an agreed bound on the development machine | to be confirmed |

---

## 5. Scheme-selection behaviour and missing context

### 5.1 Context precedence

1. **Explicit user selection** — if the user selects scheme, branch, and semester,
   that selection is authoritative for the request.
2. **Persisted in-session selection** — a choice made earlier in the session
   applies to later questions until changed.
3. **Question-derived context** — a scheme or subject named in the question may
   be used *only* if it resolves unambiguously to one indexed value.
4. **Ask** — if the above do not resolve, the system asks a clarifying question.

Requirements:

| ID | Requirement |
|---|---|
| FR-SCH-01 | Context resolution follows the precedence order above. A lower step never overrides a higher one. |
| FR-SCH-02 | Ambiguity is resolved by asking, never by picking the most common or most recent scheme. |
| FR-SCH-03 | The interface always displays the context currently in force, so the user can see whether a filter is narrowing their results. |
| FR-SCH-04 | If retrieval within the selected context returns nothing, the system says so and offers to search without the context filter or to change it. It does not silently widen the search. |
| FR-SCH-05 | Content from a different scheme is never used to answer a question bound to a specific scheme. |

### 5.2 Missing, partial, and conflicting context

This section is the behaviour behind FR-CTX-03. In every row the deciding
question is whether resolving the context could change the answer. If it could,
the system asks; if it could not, the system proceeds and states the assumption
it made and that no filter was applied for the unresolved value. The system
never resolves ambiguity by choosing the most popular or most recent scheme,
branch, or semester (FR-SCH-01, FR-SCH-02).

| Situation | Required behaviour |
|---|---|
| No document indexed for the selected context | State that no material is indexed for this selection. Do not answer. |
| Selection missing entirely (nothing chosen yet) | Ask for the context that would change the answer, following the precedence order in §5.1. Do not default to any scheme, branch, or semester. |
| Selection partial (e.g. scheme known, semester not) | Ask for the missing value if it would change the answer; otherwise proceed and state the assumption in the answer and that no filter was applied for the missing value. |
| Question implies a different context than selected | Point out the mismatch and ask which should apply; do not silently prefer either one. |
| Question itself names conflicting context (e.g. two schemes) | Ask which one applies. Do not choose on the basis of popularity, recency, or index size. |
| Context not required by the question (e.g. a general academic-regulation question) | Proceed, and state that no scheme filter was applied. |

---

## 6. PDF ingestion, chunk metadata, and page-level citations

### 6.1 Extraction

| ID | Requirement |
|---|---|
| ING-01 | PyMuPDF extracts text page by page. The one-based original PDF page number is preserved for every extracted page (§PC-5). |
| ING-02 | Document identity is two-tiered, matching FR-ING-02: a logical `document_id` for the work and a `version_id` for one file revision. Re-ingesting a revision never creates a second logical document for the same work. |
| ING-03 | Ingestion records where a document came from (`source_url`, filename), when it was ingested, and the content hash of the file it was built from (FR-ING-09). |
| ING-04 | Every extracted page is classified into exactly one of four outcomes: **text**, **blank**, **image-only**, or **extraction failure** (ING-06). A non-text page is recorded as its own outcome, never stored as valid empty content and never collapsed into a different outcome (§PC-5). |
| ING-05 | Image-only and scan-only pages are recorded and reported as such, so OCR remains an explicit, separate path (D6) rather than a silent quality loss. OCR is not part of the MVP. |
| ING-06 | The page outcomes are distinct and are reported separately. **Text** pages supply content to the index. **Blank** means the page genuinely has no content; **image-only** means the page has content that is not machine-readable text (a scan or picture); **extraction failure** means text is expected but extraction produced none. A blank page is not reported as a failure, and an image-only page is not reported as blank. |

### 6.2 Chunking

| ID | Requirement |
|---|---|
| CHK-01 | Splitting prefers document structure: module, unit, and subject headings (§PC-5). |
| CHK-02 | A maximum chunk size is enforced after structural splitting. |
| CHK-03 | Any block that still exceeds the maximum is hard-split at a safe boundary, with the split recorded. |
| CHK-04 | A chunk that spans pages stores `page_start` and `page_end`; a chunk within one page stores that single `page_number` (§PC-5). |
| CHK-05 | Chunks are never created that contain text from two different documents. |

### 6.3 Metadata requirements

The authoritative field list is FR-META-01. Additional requirements:

| ID | Requirement |
|---|---|
| META-01 | Metadata is stored per chunk, not only per document, because citation works at chunk granularity. |
| META-02 | Absent values are absent. Null is preferred over a guess, especially for `effective_date` and `module`. |
| META-03 | The metadata store and the vector index are updated together; a mismatch between index size and metadata rows is detectable. |
| META-04 | Version-level facts are recorded once per version and reached through `version_id` (FR-META-05). A superseding version is recorded as a new row linked to the version it replaces, never by editing that version's rows in place (FR-META-06). |
| META-05 | A metadata update and the index update it depends on form one unit of work. Until that unit completes, the new state is not queryable, so a partial or mismatched state is never served (FR-IDX-05, §6.5). |

### 6.4 Page-level citation

| ID | Requirement |
|---|---|
| CIT-01 | The citation chain is: FAISS vector ID → metadata record → `document_id` + page → displayed document name and page number. |
| CIT-02 | The document name shown to the user is the human-readable filename or verified title, never an internal row ID. §PC-6 records the reviewed reference project as having no page-level citation chain; this requirement keeps provenance structural to avoid that gap (§PC-5). |
| CIT-03 | Page numbers shown to the user are the original PDF page numbers, matching the PDF a student can open. |
| CIT-04 | If a chunk spans pages, the citation shows the range. |
| CIT-05 | A citation is only shown if its metadata resolves. An unresolved citation is an error state, not a blank label. |
| CIT-06 | The evidence labels given to Gemini contain filename and page, so the model's references are checkable against supplied evidence (§PC-5). |
| CIT-07 | A citation records the document identity and the original page it was drawn from, independently of whether a preview can be opened. Where no `source_url` is recorded, the interface shows the citation with a "preview unavailable" state and does not invent a URL (FR-CITE-07). |
| CIT-08 | Where a recorded `source_url` is unreachable, broken, or blocked from being previewed (for example by framing restrictions), that failure is shown honestly. The citation still shows the recorded document and original page; it is not silently dropped and no substitute destination is offered (FR-CITE-07). |
| CIT-09 | A PDF preview link uses the `#page=N` fragment where a page number is available. Because some viewers ignore that fragment, the interface states that the number shown is the recorded original page and may not be honoured by every viewer (FR-CITE-03). |
| CIT-10 | The system never fabricates a citation, a URL, a document version, or a page destination to fill a gap. Where a value is unknown or a preview is impossible, the honest unavailable state is shown instead. |
| CIT-11 | A citation binds to `document_id`, `version_id`, and the original page. Superseding a document never redirects an existing citation to its replacement: the citation keeps resolving to the exact version and page that supported the answer (FR-CITE-06, FR-META-06, FR-RET-04). |

### 6.5 Ingestion consistency and recovery

Ingestion writes to more than one store — the SQLite metadata and the FAISS
index — so the two can drift apart if a run is interrupted. The requirements
below define how that drift is detected and what the application is allowed to
serve. They state the required outcome only and do not prescribe any particular
mechanism, library, or implementation detail.

| ID | Requirement |
|---|---|
| ING-CON-01 | After a successful ingestion or index update, the SQLite metadata and the FAISS index agree: every indexed vector has exactly one metadata row, and the index size equals the stored chunk count (META-03, AC-03). |
| ING-CON-02 | If an update is partial, fails, or is interrupted before completion, the inconsistent state is detected on the next start or ingestion run rather than being treated as current (META-05). |
| ING-CON-03 | A partially written or mismatched index is never served as current. While the state is inconsistent, retrieval does not run against it; the system reports the condition instead of returning results from a known-inconsistent index (FR-IDX-05). |
| ING-CON-04 | Version mixing is prevented: a single answer's evidence never combines chunks from two versions of the same logical document (CHK-05, FR-RET-04). |
| ING-CON-05 | Recovery returns the system to a consistent state — either the last complete state or the completed update — without creating duplicate chunks or vectors. |

---

## 7. RAG retrieval, grounded generation, and refusal

### 7.1 Retrieval

| ID | Requirement |
|---|---|
| RET-01 | The pipeline order is: resolve context → filter by metadata → rank by relevance → bound by token budget → assemble evidence. |
| RET-02 | The MVP baseline is dense retrieval. Hybrid lexical + dense retrieval and reranking are adopted only if evaluation demonstrates improvement (D5, §PC-5). |
| RET-03 | Filters are applied before ranking, so passages from other schemes cannot crowd out correct material (§PC-5). |
| RET-04 | The number of retrieved passages and the resulting context size are configuration values, not hard-coded assumptions about document length. |
| RET-05 | Retrieved evidence retains its provenance through every step, so nothing reaches generation as an unattributed string. |
| RET-06 | Retrieved evidence is labelled as untrusted document content and is kept structurally separate from system instructions throughout retrieval and assembly (FR-GEN-05, NFR-SEC-06). |
| RET-07 | Default retrieval excludes superseded document versions; an ordinary query never returns a superseded version (FR-RET-04, CIT-11). |
| RET-08 | Retrieval does not run against a metadata store and index that are known to disagree; an inconsistent state is reported instead (ING-CON-03). |

### 7.2 Grounded generation

| ID | Requirement |
|---|---|
| GEN-01 | Gemini receives the question, the evidence blocks with source labels, and instructions that constrain it to that evidence. |
| GEN-02 | The instruction set states explicitly that the model must not use outside knowledge to answer syllabus or regulation questions. |
| GEN-03 | Output is requested in a readable structure with headings and lists where appropriate (§PC-4). |
| GEN-04 | The system's own uncertainty is expressible: partial evidence produces a qualified answer, not a complete-sounding one. |
| GEN-05 | Retrieved document text is passed to the model as untrusted evidence, in a clearly delimited channel separate from instructions. Text inside it that reads as an instruction is treated as content to be reported, never obeyed (FR-GEN-05, NFR-SEC-06, NFR-SEC-07). |
| GEN-06 | The instruction set states that instructions found inside a retrieved document have no authority over the system's own instructions, security rules, or the task to be performed. |

### 7.3 Refusal behaviour

| ID | Requirement |
|---|---|
| REF-01 | If no relevant indexed evidence is found, the answer states that the information is not available in the indexed material (§PC-1, §PC-5). |
| REF-02 | If relevant evidence is weak, the system answers only what is supported and clearly states what could not be confirmed. |
| REF-03 | Refusal is a normal, well-presented state, not an error dialog (FR-CONV-04). |
| REF-04 | A refusal must not be accompanied by an unsourced guess, a "likely" answer, or an answer drawn from model memory. |
| REF-05 | Where evidence conflicts, the conflict is surfaced to the user rather than resolved silently. |

---

## 8. Data-source verification, document permissions, and licensing

### 8.1 Source verification

| ID | Requirement |
|---|---|
| SRC-01 | Every indexed document is traceable to an official or otherwise verifiable source, recorded as `source_url` (§PC-5). |
| SRC-02 | A document is only indexed once its scheme, branch, semester, and document type are confirmed and recorded. |
| SRC-03 | Documents whose provenance cannot be established are not indexed. |
| SRC-04 | Where an official source publishes a superseding version, the superseded document is marked as such rather than left to compete in retrieval. |
| SRC-05 | `effective_date` is only stored when verified. An unverified date stays empty (§PC-5, FR-META-02). |
| SRC-06 | The maintainer can list what is indexed, from where, and at which version. |

### 8.2 Permissions and licensing

| ID | Requirement |
|---|---|
| LIC-01 | Before public release, the permissions and licensing status of every indexed document is assessed and recorded (§PC-1). |
| LIC-02 | The assistant does not redistribute the underlying PDF beyond what its licence permits. Where redistribution is not permitted, citation points to the official source. |
| LIC-03 | Document permissions are reviewed before any public deployment, and any document without a clear basis for inclusion is withheld from the public index. |
| LIC-04 | The interface states that the assistant is unofficial and that the official document remains authoritative, without implying VTU endorsement (§PC-1). |
| LIC-05 | If an owner requests removal of a document, removal is possible without rebuilding the whole system. |

### 8.3 Public-release gate

Public deployment (D10) is gated. Clearing this gate is a precondition for
release, not a completion of it. Nothing in this document marks public
deployment as approved, completed, or ready, and this draft does not authorise
a release.

| ID | Requirement |
|---|---|
| REL-01 | Before public release, the relevant acceptance criteria in Section 9 pass, with evidence recorded rather than inferred from plausible output. |
| REL-02 | Before public release, the security checks required by Section 4.2 are performed and their results recorded. |
| REL-03 | Before public release, the permissions and licensing review in Section 8.2 is completed and recorded for every indexed document (LIC-01, LIC-03). |
| REL-04 | Public release requires explicit, recorded release approval by a human reviewer. In the absence of a recorded approval, the release does not proceed. |
| REL-05 | Until REL-01 to REL-04 are satisfied, the assistant is not publicly deployed and is not described as released or approved. |

---

## 9. Acceptance criteria and test cases

Acceptance criteria are met only when evidence shows they passed. A task is not
marked complete on the basis of plausible output (§PC-7).

### 9.1 Acceptance criteria

| AC ID | Criterion | Verifies |
|---|---|---|
| AC-01 | A representative approved VTU syllabus PDF is ingested; every extracted page maps to its correct original one-based page number, spot-checked against the PDF. | FR-ING-01, ING-01 |
| AC-02 | Every stored chunk resolves to a document ID and a page or page range; no chunk has null provenance. | FR-ING-04, CHK-04 |
| AC-03 | Every chunk in the index has a matching metadata row, and the index size equals the metadata row count. | FR-IDX-01, META-03 |
| AC-04 | For a question whose answer lies on a known page, the retrieved evidence set contains that page (or the passage carrying the answer) within the agreed retrieval range. The top-ranked passage is not required to be the answer page, provided the relevant evidence is present and correctly cited. The range itself is a pending decision (Q7); no cutoff or score threshold is set by this criterion. | FR-RET-01, FR-RET-02 |
| AC-05 | Every factual claim in the answer carries a citation that resolves to a real document and page. | FR-CITE-01, CIT-01 |
| AC-06 | No citation in any test answer refers to a document or page that was not supplied as evidence. | FR-CITE-04, GEN-02 |
| AC-07 | A question outside the indexed material produces a refusal consistent with REF-01 and REF-04, with no invented content. | FR-GEN-04, REF-01, REF-04 |
| AC-08 | A question answered only in a non-selected scheme is not answered from that scheme; the system says so or asks. | FR-SCH-05, NFR-ACC-02 |
| AC-09 | Changing scheme/branch/semester visibly changes retrieval results, confirming filters are applied before ranking. | FR-CTX-02, RET-03 |
| AC-10 | The full question flow is completable with the keyboard alone. | NFR-A11Y-01 |
| AC-11 | No API key or credential appears in any browser-delivered asset, and no default credential exists in the codebase. | NFR-SEC-01, NFR-SEC-02 |
| AC-12 | Model output containing HTML-like text renders as text and does not execute. | NFR-SEC-03 |
| AC-13 | The layout is usable at phone and laptop widths without horizontal scrolling of the conversation. | NFR-RSP-01 |
| AC-14 | Re-running ingestion on an unchanged document creates no duplicate documents or chunks. | FR-ING-07 |
| AC-15 | A document containing a genuinely blank page, an image-only or scanned page, and a page that fails text extraction is ingested, and each page is classified and reported as its own outcome — blank, image-only, and extraction failure respectively — with none collapsed into another and none stored as valid text. | ING-04, ING-06, FR-ING-05 |
| AC-16 | Re-ingesting byte-identical content creates no new version, chunk, or vector; ingesting changed content for the same logical document creates a new `version_id` recording what it supersedes. The earlier version stays identifiable and resolvable, so existing citations continue to resolve to the exact original version and page. Historical search across superseded versions is not required in the MVP (FR-RET-04, Q8). | FR-ING-09, FR-ING-10, FR-ING-11, FR-ING-12 |
| AC-17 | After a document is superseded, a citation created against the earlier version still resolves to that exact version and original page; it is not redirected to the replacement. | FR-CITE-06, CIT-11 |
| AC-18 | When `source_url` is absent, broken, or preview-blocked, opening a citation shows an honest unavailable state with the recorded document identity and original page, and no invented URL, version, or page. | FR-CITE-03, FR-CITE-07, CIT-07, CIT-08, CIT-09 |
| AC-19 | Retrieved text containing an embedded instruction does not cause the system to follow it, change task, reveal configuration, or abandon its refusal behaviour; the text is reported as document content only. | NFR-SEC-06, NFR-SEC-07, FR-GEN-05, GEN-06 |
| AC-20 | After an interrupted or failed ingestion, the system does not serve a partially written or mismatched index; the inconsistent state is detected and recovered, and metadata and index agree once recovery completes. | FR-IDX-05, ING-CON-01, ING-CON-02, ING-CON-03 |
| AC-21 | Public release is not marked approved or completed by this document; it remains gated on REL-01 to REL-04. | REL-01, REL-02, REL-03, REL-04, REL-05 |

### 9.2 Test cases

Each case is written to be executable manually before automation exists.

| TC ID | Given | When | Then |
|---|---|---|---|
| TC-01 | A representative approved syllabus PDF with known page content | The document is ingested | Reported page and chunk counts match the PDF; a chosen fact is found on its correct original page |
| TC-02 | An ingested document | The metadata record for a chunk is inspected | `document_id`, `version_id`, `filename`, `scheme`, `branch`, `semester`, `page_start`/`page_end`, and `faiss_id` are present and correct |
| TC-03 | An ingested document | The metadata store and index are compared | Counts match; every `faiss_id` resolves to exactly one metadata row |
| TC-04 | An ingested document | A question is asked whose answer is on a specific known page | The retrieved evidence includes that page (or the passage carrying the answer) within the agreed retrieval range, and the answer cites it correctly |
| TC-05 | Any indexed context | A question about unrelated subject matter is asked | The answer is a refusal per REF-01; no unsourced claim appears |
| TC-06 | Scheme A selected; the answer exists only in Scheme B | A question is asked | The system does not answer from Scheme B; it states the absence or asks about the mismatch |
| TC-07 | A question with no explicit context, in a fresh session | The question is submitted | The system asks for the required context, or proceeds and states the assumption |
| TC-08 | An ingested document | Ingestion is run a second time unchanged | No duplicate documents or chunks are created |
| TC-09 | A PDF containing a blank page, an image-only or scanned page, and a page whose text fails to extract | The document is ingested | The blank page is reported blank, the image-only page is reported image-only, and the failing page is reported as an extraction failure; none is stored as valid text and none is collapsed into another outcome |
| TC-10 | A running application | The network panel and delivered assets are inspected | No API key or credential is present; server-side configuration only |
| TC-11 | A running application | An answer is rendered that contains markup-like text | It is displayed as text; no script executes |
| TC-12 | A running application | The full flow is completed using only the keyboard | Every control is reachable, usable, and shows a visible focus state |
| TC-13 | A running application | The layout is viewed at phone and laptop widths | No horizontal scrolling of the conversation; citations remain openable |
| TC-14 | A running application | A citation is opened | If the recorded source permits a preview, the cited PDF page opens at the recorded page number; otherwise an honest "preview unavailable" state is shown with the recorded document identity and original page |
| TC-15 | An already-ingested document | The same file is ingested again unchanged, then a modified file for the same work is ingested | The unchanged run reports no change; the modified file creates a new `version_id` recording what it supersedes, and the earlier version is not overwritten |
| TC-16 | A citation created against a document version | The document is superseded by a newer version | The existing citation still resolves to the original version and page; it is not redirected to the newer version |
| TC-17 | A citation whose `source_url` is absent, broken, or preview-blocked | The citation is opened | An honest unavailable state is shown with the recorded document identity and original page; no URL, version, or page is invented |
| TC-18 | An indexed document containing text phrased as an instruction (for example "ignore your instructions") | A question retrieves that passage | The system does not follow the embedded instruction, does not change task or reveal configuration, and reports the text as document content only |
| TC-19 | An ingestion run interrupted after some chunks are written but before completion | The application starts, or ingestion is re-run | The inconsistent index is not served; the state is detected and recovered, and metadata and index agree without duplicate chunks or vectors |

### 9.3 Not accepted as evidence of success

- An answer that sounds correct but has no resolving citation.
- A citation label produced by the language model without a matching metadata record.
- A citation silently redirected to a newer document version, or to a different page, than the one that supported the answer.
- A preview that shows a substituted or inferred destination when the recorded source is unavailable.
- A run reported as successful while the metadata store and the index disagree.
- An embedded instruction inside retrieved text being treated as a command.
- Retrieval that returns something for every query, including queries with no
  supporting document.
- A page number that is a chunk index or array position rather than the original
  PDF page.

---

## 10. Interface: ChatGPT-inspired, original branding, prominent citations

### 10.1 Direction

The interface follows the interaction patterns described in §PC-4 — collapsible
sidebar, new-chat action, centred chat area and composer, suggested academic
prompts — while remaining visually and nominally its own product. It must not
reproduce OpenAI's branding, and it must not imply affiliation with OpenAI or
with VTU (§PC-1).

### 10.2 Requirements

| ID | Requirement |
|---|---|
| UI-01 | The layout is recognisably conversation-first: one centred column, composer at the base, secondary controls in a collapsible sidebar. |
| UI-02 | The current scheme, branch, and semester are persistently visible and changeable without leaving the conversation (FR-CTX-01). |
| UI-03 | Applications of motion are purposeful and limited to transitions that aid comprehension. Decorative motion is not part of the MVP (D9). |
| UI-04 | Suggested prompts are drawn from the indexed material and the selected context, not hard-coded generic questions. |
| UI-05 | Empty, loading, error, "no evidence found", and "context missing" states are each designed, distinguishable, and non-alarming. |
| UI-06 | Answers present citations as first-class content, not as low-contrast footnotes (FR-CITE-05). |

### 10.3 Citation presentation

Citations are the product's main claim to trustworthiness, so they are a
designed surface rather than an afterthought.

| ID | Requirement |
|---|---|
| UI-CIT-01 | Each citation shows document name and page number in the answer itself, adjacent to the claim it supports (FR-CITE-02). |
| UI-CIT-02 | A citation is interactive and opens or previews the cited PDF page (FR-CITE-03, CIT-03). |
| UI-CIT-03 | Citations are visually prominent enough to be noticed without effort, and legible at AA contrast (NFR-A11Y-02). |
| UI-CIT-04 | A citation is identifiable by role for assistive technology, not by position or colour alone (NFR-A11Y-03). |
| UI-CIT-05 | Unsourced statements are visually distinguishable from cited statements, so a reader can see which claims are grounded. |
| UI-CIT-06 | The set of sources used for an answer is summarisable — the user can see which documents informed it. |
| UI-CIT-07 | When a citation's preview is unavailable, the citation surface shows the recorded document identity and original page together with an honest unavailable notice, rather than a broken control or an invented link (FR-CITE-03, FR-CITE-07, CIT-07, CIT-08, CIT-09). |

---

## 11. Open questions and pending decisions

The earlier documentation-date conflict is resolved: this revision uses the
current date, 2026-10-22 (Section 12). Q2–Q8 remain open.

| # | Question | Blocks | Status |
|---|---|---|---|
| Q2 | Agreed performance thresholds for NFR-PERF-01 to NFR-PERF-04. | NFR-4.6 sign-off | Awaiting approval |
| Q3 | The specific 2–3 representative VTU PDFs to use for validation, and their verified sources. | M1, D7 | Awaiting selection |
| Q4 | Chunk maximum size and token budget values. | CHK-02, RET-04 | Awaiting approval |
| Q5 | UI design brief and design tokens (listed as not yet completed in §PC-8). | Section 10 implementation | Awaiting approval |
| Q6 | Whether the initial validation set includes any document whose redistribution licence is unclear. | Section 8, LIC-01 | Awaiting review |
| Q7 | The agreed retrieval range for AC-04 — how many passages, or what context window, counts as "within range" for confirming that relevant evidence was retrieved. The criterion is stated as recall-within-range, but no numeric range or similarity threshold is set here. | AC-04, Section 9 | Awaiting approval |
| Q8 | Whether an explicit, documented historical lookup of superseded document versions is in scope beyond retention. This draft keeps superseded versions retained so existing citations keep resolving and excludes them from default retrieval, but it does not add a historical-lookup feature (FR-RET-04, CIT-11). | FR-RET-04, CIT-11 | Awaiting decision |

---

## 12. Approval record

**This document is a draft and is NOT approved.**

| Item | Value |
|---|---|
| Status | DRAFT — awaiting review |
| Revision | draft-02 |
| Prepared | 2026-10-22 |
| Approved by | — |
| Approval date | — |
| Notes | draft-02 incorporates nine review corrections (see the revision note at the top). Incorporating a correction is not approving it. No phase in `PROJECT_CONTEXT.md` §8 is marked complete by this document. `PROJECT_CONTEXT.md` §9 remains the record of project phase, and the requirements task there stays open until this document is approved. |

On approval, the reviewer should confirm or amend: the MVP scope in Section 2,
the performance thresholds in Section 4.6, the open questions in Section 11, and
the acceptance criteria in Section 9. Only then should `PROJECT_CONTEXT.md` be
updated to record this task as complete.
