/* ==========================================================================
   VTU Assistant — data seam
   --------------------------------------------------------------------------
   This is the only file in the interface that knows where data comes from.
   app.js calls these functions and never reads storage itself.

   Today every function is answered from mock-data.js. When the Flask
   backend exists, only the bodies below change: each one becomes a fetch()
   against a route that returns the same record shape. No markup, CSS, or
   app.js code has to be rewritten, which is the whole point of having a
   seam.

   Public interface
     getContextOptions()                 -> Promise<{scheme[],branch[],semester[]}>
     getSuggestedPrompts()               -> Promise<[{label,meta,question}]>
     findMissingContext(context)         -> string[]   (synchronous rule)
     askQuestion({question, context})    -> Promise<result>
     getCitationTarget(citation)         -> Promise<{status,url?,reason?}>

   askQuestion resolves to exactly one of:
     { status:'answered',     answer:{blocks[], sources[]} }
     { status:'no-evidence',  message }        <- refusal is an outcome, not an error
     { status:'needs-context', missing[], labels[] }
   and rejects with an Error carrying .userMessage when the request itself
   fails. Refusal (REF-03) and failure are deliberately different paths, so
   the interface can never present "I don't know" as a crash.
   ========================================================================== */

(function () {
  'use strict';

  var FIXTURES = window.VTU_FIXTURES;

  /* Fixture-only pacing, so the loading state is actually observable during
     review. Real latency comes from the API and this constant is deleted. */
  var LATENCY_MS = 700;
  var SHORT_LATENCY_MS = 160;

  /* Context fields without which the answer could differ. Kept here rather
     than in app.js because it is a data rule, and the backend will apply the
     same rule when it exists. */
  var REQUIRED_CONTEXT = ['scheme', 'branch', 'semester'];
  var CONTEXT_LABELS = { scheme: 'Scheme', branch: 'Branch', semester: 'Semester' };

  function wait(ms) {
    return new Promise(function (resolve) { window.setTimeout(resolve, ms); });
  }

  /* Return copies, so a consumer can never mutate the fixture store. */
  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function makeError(code, userMessage) {
    var error = new Error(userMessage);
    error.code = code;
    error.userMessage = userMessage;
    return error;
  }

  function normaliseContext(context) {
    var input = context || {};
    var clean = {};
    REQUIRED_CONTEXT.forEach(function (key) {
      clean[key] = String(input[key] === undefined || input[key] === null ? '' : input[key]).trim();
    });
    return clean;
  }

  function findMissingContext(context) {
    var clean = normaliseContext(context);
    return REQUIRED_CONTEXT.filter(function (key) { return clean[key] === ''; });
  }

  function labelMissing(keys) {
    return keys.map(function (key) { return CONTEXT_LABELS[key] || key; });
  }

  function getContextOptions() {
    return wait(SHORT_LATENCY_MS).then(function () {
      return clone(FIXTURES.contexts);
    });
  }

  function getSuggestedPrompts() {
    return wait(SHORT_LATENCY_MS).then(function () {
      return clone(FIXTURES.suggestedPrompts);
    });
  }

  function askQuestion(payload) {
    var request = payload || {};
    var question = String(request.question === undefined || request.question === null ? '' : request.question).trim();
    var context = normaliseContext(request.context);
    var triggers = FIXTURES.reviewTriggers || {};

    if (question === '') {
      return Promise.reject(makeError('empty-question', 'No question was provided.'));
    }

    /* Missing mandatory context is answered without pretending to search:
       the assistant refuses to guess which scheme the question means. */
    var missing = findMissingContext(context);
    if (missing.length > 0) {
      return Promise.resolve({
        status: 'needs-context',
        missing: missing,
        labels: labelMissing(missing)
      });
    }

    var lowered = question.toLowerCase();

    if (triggers.errorKeyword && lowered.indexOf(triggers.errorKeyword) !== -1) {
      return wait(LATENCY_MS).then(function () {
        throw makeError(
          'request-failed',
          'The request could not be completed. Something went wrong while preparing the answer. ' +
          'Your question has not been answered, and no answer has been guessed in its place.'
        );
      });
    }

    if (triggers.noEvidenceKeyword && lowered.indexOf(triggers.noEvidenceKeyword) !== -1) {
      return wait(LATENCY_MS).then(function () {
        return { status: 'no-evidence', message: FIXTURES.noEvidenceAnswer.message };
      });
    }

    return wait(LATENCY_MS).then(function () {
      var answer = clone(FIXTURES.sampleAnswer);
      /* Resolve source ids into full citation records, in the order the answer
         lists them. The block-level refs stay as ids pointing into this list,
         which is how the numbered markers and the source list stay in step. */
      answer.sources = (answer.sources || [])
        .map(function (id) { return FIXTURES.citations[id] ? clone(FIXTURES.citations[id]) : null; })
        .filter(function (citation) { return citation !== null; });
      return { status: 'answered', answer: answer };
    });
  }

  /* Resolves to the target the viewer should show. A citation whose source
     URL is absent or empty resolves to 'unavailable' rather than to a guessed
     destination — there is no branch here that invents a URL or a page. */
  function getCitationTarget(citation) {
    if (!citation) {
      return Promise.reject(makeError('unknown-citation', 'That source is not part of the current answer.'));
    }
    var raw = citation.source_url;
    var url = typeof raw === 'string' && raw.trim() !== '' ? raw.trim() : null;

    return wait(SHORT_LATENCY_MS).then(function () {
      if (url) {
        return { status: 'available', url: url, citation: clone(citation) };
      }
      return { status: 'unavailable', reason: 'no-source-url', citation: clone(citation) };
    });
  }

  window.VTUApi = {
    /* Marks this module as fixture-backed, so no consumer mistakes the
       interface review for a working retrieval system. */
    isFixture: true,
    contextLabels: CONTEXT_LABELS,
    requiredContext: REQUIRED_CONTEXT.slice(),
    findMissingContext: findMissingContext,
    getContextOptions: getContextOptions,
    getSuggestedPrompts: getSuggestedPrompts,
    askQuestion: askQuestion,
    getCitationTarget: getCitationTarget
  };
})();
