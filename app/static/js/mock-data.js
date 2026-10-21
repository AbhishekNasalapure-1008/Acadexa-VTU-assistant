/* ==========================================================================
   VTU Assistant — interface fixtures
   --------------------------------------------------------------------------
   TEMPORARY FILE. Everything in this file is placeholder data used to review
   the interface. It is not a dataset and contains no university content.

   Two rules this file follows deliberately:

   1. It contains no real document names, no real subject codes, and no URLs.
      Inventing plausible VTU syllabus content would violate the project's
      "never invent syllabus or circular information" principle, so the fixture
      titles say plainly that they are placeholders and every source_url is
      null. Because of this, the embedded-preview branch of the citation panel
      cannot be exercised yet; only the unavailable path can. That is stated in
      the implementation report rather than hidden.

   2. Record shapes mirror the field list the real metadata store will use
      (document_id, version_id, scheme, branch, semester, subject_code, module,
      page_number or page_start/page_end, source_url). Keeping the shapes
      identical is what allows the interface to be connected to Flask later
      without rewriting it.
   ========================================================================== */

(function () {
  'use strict';

  window.VTU_FIXTURES = {
    /* Marks every record below as fixture data, so no consumer can mistake it
       for verified information. */
    isFixture: true,

    /* Academic context options. In the real application these are derived from
       the documents that are actually indexed, which is why they live in data
       rather than in the markup. The empty value is what makes the
       "missing context" state reachable. */
    contexts: {
      scheme: [
        { value: '', label: 'Not set' },
        { value: '2022', label: '2022 scheme' }
      ],
      branch: [
        { value: '', label: 'Not set' },
        { value: 'CSE', label: 'Computer Science and Engineering' }
      ],
      semester: [
        { value: '', label: 'Not set' },
        { value: '5', label: 'Semester 5' },
        { value: '6', label: 'Semester 6' }
      ]
    },

    /* Suggested prompts for the empty state. Later these are drawn from the
       indexed material for the selected context (UI-04) rather than being
       fixed strings. */
    suggestedPrompts: [
      {
        label: 'What does Module 3 of this subject cover?',
        meta: 'Syllabus content',
        question: 'What does Module 3 of this subject cover?'
      },
      {
        label: 'How many credits does this subject carry?',
        meta: 'Credits and structure',
        question: 'How many credits does this subject carry?'
      },
      {
        label: 'Which practical work is listed for the subject?',
        meta: 'Labs and practicals',
        question: 'Which practical work is listed for the subject?'
      },
      {
        label: 'What is the pass requirement in this regulation?',
        meta: 'Examination rules',
        question: 'What is the pass requirement in this regulation?'
      }
    ],

    /* Citation records. Field names match the planned metadata record. */
    citations: {
      'cite-a': {
        citation_id: 'cite-a',
        document_id: 'doc-fixture-a',
        version_id: 'v1',
        version_label: 'v1',
        title: 'Placeholder Subject Syllabus — fixture A (not a real document)',
        scheme: '2022',
        branch: 'CSE',
        semester: '5',
        subject_code: 'FIX-501',
        module: 'Module 3',
        document_type: 'syllabus',
        page_number: 12,
        page_start: null,
        page_end: null,
        source_url: null
      },
      'cite-b': {
        citation_id: 'cite-b',
        document_id: 'doc-fixture-b',
        version_id: 'v2',
        version_label: 'v2',
        title: 'Placeholder Academic Regulation — fixture B (not a real document)',
        scheme: '2022',
        branch: 'CSE',
        semester: '5',
        subject_code: null,
        module: null,
        document_type: 'regulation',
        page_number: null,
        page_start: 27,
        page_end: 28,
        source_url: null
      },
      'cite-c': {
        citation_id: 'cite-c',
        document_id: 'doc-fixture-c',
        version_id: 'v1',
        version_label: 'v1',
        title: 'Placeholder Circular — fixture C (not a real document)',
        scheme: '2022',
        branch: 'CSE',
        semester: null,
        subject_code: null,
        module: null,
        document_type: 'circular',
        page_number: 3,
        page_start: null,
        page_end: null,
        source_url: null
      }
    },

    /* A sample grounded answer, expressed as structured blocks rather than an
       HTML string. app.js builds elements from these blocks with textContent,
       so nothing here can ever be interpreted as markup (NFR-SEC-03).

       The prose describes the interface itself rather than pretending to be
       real syllabus content. */
    sampleAnswer: {
      blocks: [
        {
          kind: 'paragraph',
          text: 'This is placeholder answer text, shown to review how a grounded answer is presented. It makes no claim about any real syllabus or regulation. Every sentence that would carry a fact in the real application is followed by a reference marker that opens the cited page.',
          refs: []
        },
        {
          kind: 'heading',
          text: 'How this answer demonstrates citation behaviour'
        },
        {
          kind: 'list',
          ordered: false,
          items: [
            {
              text: 'Reference markers sit next to the claim they support, not in a footnote at the end.',
              refs: ['cite-a']
            },
            {
              text: 'Sources used are listed together, so the set of documents behind the answer is visible at a glance.',
              refs: ['cite-a', 'cite-b']
            },
            {
              text: 'Selecting any marker or source opens the cited document in the side panel, and the panel names the original page.',
              refs: ['cite-b']
            }
          ]
        },
        {
          kind: 'heading',
          text: 'How a table is presented'
        },
        {
          /* Tables are part of the answer format because syllabus and
             regulation documents carry credit and module tables. The values
             are placeholders: no real subject is described. */
          kind: 'table',
          caption: 'Placeholder structure table — fixture values only, not a real subject',
          headers: ['Component', 'Placeholder value', 'Page'],
          rows: [
            ['Theory lectures', 'Placeholder figure', '12'],
            ['Practical or laboratory work', 'Placeholder figure', '13'],
            ['Credits', 'Placeholder figure', '12']
          ],
          refs: ['cite-a']
        },
        {
          kind: 'heading',
          text: 'Where a claim depends on more than one document'
        },
        {
          kind: 'paragraph',
          text: 'A single sentence can be supported by more than one source. In that case each source is marked separately, so a reader can check the claim against every document it rests on rather than assuming one source stands for all of it.',
          refs: ['cite-b', 'cite-c']
        }
      ],
      sources: ['cite-a', 'cite-b', 'cite-c']
    },

    /* The refusal outcome, kept as data so the state is rendered by the same
       code path as any other answer. */
    noEvidenceAnswer: {
      message: 'Nothing in the documents indexed for the selected context answers this question. Rather than guess, the assistant has not answered it.'
    },

    /* Documented review switches for api.js. Keyword-based so that the error
       and no-evidence paths can be reached through the real flow during
       review. These are fixture scaffolding and are deleted when the real
       API is connected. */
    reviewTriggers: {
      errorKeyword: 'trigger-error',
      noEvidenceKeyword: 'trigger-no-evidence'
    }
  };
})();
