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
> **Date:** 2026-10-21
> **Revision:** draft-01
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
| D7 | Large-scale dataset ingestion | §PC-9: expand only after small-set tests pass | After M1–M8 accepted |
| D8 | Circulars, notices, exam rules as document types | §PC-3: potential future types | After syllabus type is stable |
| D9 | GSAP motion polish | §PC-2: only where it improves usability | After M10 usability review |
| D10 | Public deployment and release | §PC-1: subject to review/approval | After Section 8 checks pass |

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
| FR-CONV-04 | S | The interface exposes the four states in §PC-4: loading, empty, error, and no-evidence. |
| FR-CONV-05 | C | Conversation history survives a page reload once D1 is implemented. |

### 3.2 Academic context

| ID | Pri | Requirement |
|---|---|---|
| FR-CTX-01 | M | The user can select scheme, branch, and semester. The current selection is always visible while chatting (§PC-4). |
| FR-CTX-02 | M | The selected context is applied as a retrieval filter, not as an after-the-fact re-sort. |
| FR-CTX-03 | M | If required context is missing before retrieval, the system asks a clarifying question instead of guessing (§PC-5). |
| FR-CTX-04 | S | Context changes are reflected in the next answer without restarting the application. |

### 3.3 Ingestion and metadata

| ID | Pri | Requirement |
|---|---|---|
| FR-ING-01 | M | Text is extracted page by page with PyMuPDF; each page retains its original one-based number (§PC-5). |
| FR-ING-02 | M | Each ingested document has a stable identity that survives re-ingestion of the same file. |
| FR-ING-03 | M | Documents are chunked by structure (module/unit/subject headings) where that structure exists, then subject to a maximum chunk size; oversized blocks are hard-split safely (§PC-5). |
| FR-ING-04 | M | Every chunk stores its parent document ID and page provenance, using `page_start`/`page_end` when it spans pages (§PC-5). |
| FR-ING-05 | M | A page that yields empty or unusable text is flagged, not accepted as valid content (§PC-5). |
| FR-ING-06 | M | The full metadata set in §3.4 is persisted for each document and chunk where the value is available. |
| FR-ING-07 | S | Re-running ingestion on an unchanged document is idempotent and does not duplicate records. |
| FR-ING-08 | S | The ingestion run reports, per document, how many pages and chunks were stored and which metadata fields were unavailable. |

### 3.4 Chunk metadata

| ID | Pri | Requirement |
|---|---|---|
| FR-META-01 | M | Each chunk record carries: `chunk_id`, `document_id`, `filename`, `source_url` (when available), `scheme`, `branch`, `semester`, `subject_code`, `module`, `document_type`, `effective_date` (when verified), `page_number` or `page_start`/`page_end`, `chunk_text`, and `faiss_id`. |
| FR-META-02 | M | Fields that are genuinely unknown are stored as absent, never as a fabricated default. An unverified `effective_date` stays empty rather than being estimated. |
| FR-META-03 | M | `faiss_id` is the single link between the vector index and the metadata record, as required by §PC-5. |
| FR-META-04 | S | The metadata schema is designed so that additional schemes, branches, and document types can be added without restructuring existing records (§PC-3). |

### 3.5 Vector index

| ID | Pri | Requirement |
|---|---|---|
| FR-IDX-01 | M | The mapping FAISS vector ID → metadata record → document and original page is explicit and stable. A FAISS position is never treated as a document ID or a page number (§PC-5). |
| FR-IDX-02 | M | Embeddings are L2-normalised when inner-product similarity is used to represent cosine similarity (§PC-5). |
| FR-IDX-03 | M | The index and its metadata are persisted and re-loaded consistently, so a restart does not change answer citations. |
| FR-IDX-04 | S | Index rebuild and incremental update behaviour is tested, not assumed (§PC-5). |

### 3.6 Retrieval and generation

| ID | Pri | Requirement |
|---|---|---|
| FR-RET-01 | M | Retrieval applies metadata filters for the selected context before ranking (§PC-5). |
| FR-RET-02 | M | The MVP ships a dense retrieval baseline; hybrid/reranked retrieval is only added if measured evidence shows improvement (D5). |
| FR-RET-03 | M | Assembly of context for generation is bounded by relevance and token budget. Passing all chunks of a large document is not permitted (§PC-5). |
| FR-GEN-01 | M | Gemini receives only retrieved evidence, and every evidence block is labelled with filename and page (§PC-5). |
| FR-GEN-02 | M | The prompt requires that citations refer only to supplied evidence (§PC-5). |
| FR-GEN-03 | M | Output is rendered as readable prose with headings and lists where appropriate (§PC-4). |
| FR-GEN-04 | M | When no relevant evidence is found, the system states the answer is not available in the indexed material and does not guess (§PC-1, §PC-5). |

### 3.7 Citations

| ID | Pri | Requirement |
|---|---|---|
| FR-CITE-01 | M | Every factual claim in an answer is attributable to at least one cited source, and citation labels are structurally correct — derived from stored metadata, not from text the model produced. |
| FR-CITE-02 | M | Each citation shows document name and page number (§PC-4). |
| FR-CITE-03 | M | A citation can be opened or previewed at the cited PDF page (§PC-4). |
| FR-CITE-04 | M | Citations that do not correspond to supplied evidence are rejected, and the answer is regenerated or downgraded to a refusal. |
| FR-CITE-05 | S | Citations are displayed prominently rather than as low-contrast footnotes (Section 10). |

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

### 5.2 Missing context

| Situation | Required behaviour |
|---|---|
| No document indexed for the selected context | State that no material is indexed for this selection. Do not answer. |
| Selection partial (e.g. scheme known, semester not) | Ask for the missing value if it would change the answer; otherwise proceed and state the assumption in the answer. |
| Question implies a different context than selected | Point out the mismatch and ask which should apply. |
| Context not required by the question (e.g. a general academic-regulation question) | Proceed, and state that no scheme filter was applied. |

---

## 6. PDF ingestion, chunk metadata, and page-level citations

### 6.1 Extraction

| ID | Requirement |
|---|---|
| ING-01 | PyMuPDF extracts text page by page. The one-based original PDF page number is preserved for every extracted page (§PC-5). |
| ING-02 | Document identity is stable and file-based, so re-ingesting a version does not create a competing identity. |
| ING-03 | Ingestion records where a document came from (`source_url`, filename) and when it was ingested. |
| ING-04 | A page yielding empty or non-textual extraction is recorded as a failure of extraction for that page, never stored as valid empty content (§PC-5). |
| ING-05 | Whether a document is scan-only is detected and reported, so OCR becomes an explicit separate path (D6) rather than a silent quality loss. |

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

### 6.4 Page-level citation

| ID | Requirement |
|---|---|
| CIT-01 | The citation chain is: FAISS vector ID → metadata record → `document_id` + page → displayed document name and page number. |
| CIT-02 | The document name shown to the user is the human-readable filename or verified title, never an internal row ID (§PC-6 notes the reference project labelled context with a numeric primary key). |
| CIT-03 | Page numbers shown to the user are the original PDF page numbers, matching the PDF a student can open. |
| CIT-04 | If a chunk spans pages, the citation shows the range. |
| CIT-05 | A citation is only shown if its metadata resolves. An unresolved citation is an error state, not a blank label. |
| CIT-06 | The evidence labels given to Gemini contain filename and page, so the model's references are checkable against supplied evidence (§PC-5). |

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

### 7.2 Grounded generation

| ID | Requirement |
|---|---|
| GEN-01 | Gemini receives the question, the evidence blocks with source labels, and instructions that constrain it to that evidence. |
| GEN-02 | The instruction set states explicitly that the model must not use outside knowledge to answer syllabus or regulation questions. |
| GEN-03 | Output is requested in a readable structure with headings and lists where appropriate (§PC-4). |
| GEN-04 | The system's own uncertainty is expressible: partial evidence produces a qualified answer, not a complete-sounding one. |

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
| AC-04 | For a question whose answer lies on a known page, the top retrieved passage is from that page. | FR-RET-01, FR-RET-02 |
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
| AC-15 | A document with a page that extracts as empty is flagged as an extraction failure rather than stored as valid content. | ING-04, FR-ING-05 |

### 9.2 Test cases

Each case is written to be executable manually before automation exists.

| TC ID | Given | When | Then |
|---|---|---|---|
| TC-01 | A representative approved syllabus PDF with known page content | The document is ingested | Reported page and chunk counts match the PDF; a chosen fact is found on its correct original page |
| TC-02 | An ingested document | The metadata record for a chunk is inspected | `document_id`, `filename`, `scheme`, `branch`, `semester`, `page_start`/`page_end`, and `faiss_id` are present and correct |
| TC-03 | An ingested document | The metadata store and index are compared | Counts match; every `faiss_id` resolves to exactly one metadata row |
| TC-04 | An ingested document | A question is asked whose answer is on a specific known page | The retrieved evidence includes that page, and the answer cites it |
| TC-05 | Any indexed context | A question about unrelated subject matter is asked | The answer is a refusal per REF-01; no unsourced claim appears |
| TC-06 | Scheme A selected; the answer exists only in Scheme B | A question is asked | The system does not answer from Scheme B; it states the absence or asks about the mismatch |
| TC-07 | A question with no explicit context, in a fresh session | The question is submitted | The system asks for the required context, or proceeds and states the assumption |
| TC-08 | An ingested document | Ingestion is run a second time unchanged | No duplicate documents or chunks are created |
| TC-09 | A PDF containing a blank or image-only page | The document is ingested | That page is reported as an extraction failure; nothing empty is stored as text |
| TC-10 | A running application | The network panel and delivered assets are inspected | No API key or credential is present; server-side configuration only |
| TC-11 | A running application | An answer is rendered that contains markup-like text | It is displayed as text; no script executes |
| TC-12 | A running application | The full flow is completed using only the keyboard | Every control is reachable, usable, and shows a visible focus state |
| TC-13 | A running application | The layout is viewed at phone and laptop widths | No horizontal scrolling of the conversation; citations remain openable |
| TC-14 | A running application | A citation is opened | The cited PDF page preview or reference matches the cited page number |

### 9.3 Not accepted as evidence of success

- An answer that sounds correct but has no resolving citation.
- A citation label produced by the language model without a matching metadata record.
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

---

## 11. Open questions and pending decisions

| # | Question | Blocks | Status |
|---|---|---|---|
| Q1 | Authoritative date for project documentation: the system clock reads 2026-10-21 and `PROJECT_CONTEXT.md` records 2026-10-21, while the session environment reported 2026-10-20. This draft uses 2026-10-21. | Documentation consistency | Awaiting confirmation |
| Q2 | Agreed performance thresholds for NFR-PERF-01 to NFR-PERF-04. | NFR-4.6 sign-off | Awaiting approval |
| Q3 | The specific 2–3 representative VTU PDFs to use for validation, and their verified sources. | M1, D7 | Awaiting selection |
| Q4 | Chunk maximum size and token budget values. | CHK-02, RET-04 | Awaiting approval |
| Q5 | UI design brief and design tokens (listed as not yet completed in §PC-8). | Section 10 implementation | Awaiting approval |
| Q6 | Whether the initial validation set includes any document whose redistribution licence is unclear. | Section 8, LIC-01 | Awaiting review |

---

## 12. Approval record

**This document is a draft and is NOT approved.**

| Item | Value |
|---|---|
| Status | DRAFT — awaiting review |
| Revision | draft-01 |
| Prepared | 2026-10-21 |
| Approved by | — |
| Approval date | — |
| Notes | No phase in `PROJECT_CONTEXT.md` §8 is marked complete by this document. `PROJECT_CONTEXT.md` §9 remains the record of project phase, and the requirements task there stays open until this document is approved. |

On approval, the reviewer should confirm or amend: the MVP scope in Section 2,
the performance thresholds in Section 4.6, the open questions in Section 11, and
the acceptance criteria in Section 9. Only then should `PROJECT_CONTEXT.md` be
updated to record this task as complete.
