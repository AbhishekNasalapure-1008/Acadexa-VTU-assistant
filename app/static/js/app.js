/* ==========================================================================
   VTU Assistant — interface behaviour
   --------------------------------------------------------------------------
   Responsibilities: the view state machine, rendering, event wiring, the
   citation side panel, and keyboard handling.

   Two rules this file keeps:

   1. Model output is never assembled into an HTML string. Answers arrive as
      structured blocks and are rendered with textContent and createElement,
      so text from a document can never execute as markup (NFR-SEC-03).

   2. app.js never scrapes the DOM for data. It reads nothing back out of the
      rendered conversation; retrieved data arrives through window.VTUApi and
      lives in the state object below.
   ========================================================================== */

(function () {
  'use strict';

  var api = window.VTUApi;

  /* Interface states (REQ: empty, loading, error, missing context, no
     evidence, plus the answered conversation itself). */
  var STATE_ELEMENTS = {
    'empty': 'state-empty',
    'loading': 'state-loading',
    'error': 'state-error',
    'missing-context': 'state-missing-context',
    'no-evidence': 'state-no-evidence'
  };

  var CONTEXT_SELECTS = {
    scheme: 'ctx-scheme',
    branch: 'ctx-branch',
    semester: 'ctx-semester'
  };

  var el = {};
  var ui = {
    state: 'empty',
    /* Which sidebar section is selected: 'chat', 'syllabus', or 'circulars'.
       There is no routing, so the current section is interface state and not
       part of the URL. */
    view: 'chat',
    busy: false,
    /* The question that is waiting for academic context, so it can be asked
       again automatically once a value is chosen. */
    pendingQuestion: null,
    /* The last question asked, so "Try again" repeats it without the user
       retyping and without duplicating their message in the transcript. */
    lastQuestion: null,
    /* citation_id -> 1-based source number for the answer on screen */
    sourceIndex: {},
    /* citation_id -> citation record for the answer on screen */
    sourceById: {},
    /* The control that opened the panel, so focus can return to it. */
    panelTrigger: null,
    /* Questions asked in this session, newest first. This is real session
       state: nothing is remembered between sessions and nothing is invented
       to fill the list. */
    recent: []
  };

  /* How many questions the Recent list keeps. Older ones drop off, so the
     sidebar cannot grow without limit during a long session. */
  var RECENT_LIMIT = 6;

  /* ------------------------------------------------------------------------
     Small helpers
     ------------------------------------------------------------------------ */

  function byId(id) {
    return document.getElementById(id);
  }

  function capitalise(text) {
    if (!text) { return ''; }
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  /* The one place a page reference is turned into words. A citation that does
     not carry a page says so; nothing is inferred or filled in. */
  function pageLabel(citation) {
    if (!citation) { return 'Page not specified'; }
    if (citation.page_number) { return 'Page ' + citation.page_number; }
    if (citation.page_start && citation.page_end && citation.page_end !== citation.page_start) {
      return 'Pages ' + citation.page_start + '\u2013' + citation.page_end;
    }
    if (citation.page_start) { return 'Page ' + citation.page_start; }
    return 'Page not specified';
  }

  function contextLine(citation) {
    var parts = [];
    if (citation.scheme) { parts.push(citation.scheme + ' scheme'); }
    if (citation.branch) { parts.push(citation.branch); }
    if (citation.semester) { parts.push('Semester ' + citation.semester); }
    return parts.length > 0 ? parts.join(' \u00b7 ') : 'Not recorded for this source';
  }

  function announce(message) {
    el.live.textContent = '';
    /* Cleared first so a repeated announcement is still spoken. */
    window.setTimeout(function () { el.live.textContent = message; }, 40);
  }

  /* The selected academic context lives here, not in the DOM. The <select>
     elements are one way to edit it, not the place it is stored, so the
     context the answers depend on is independent of the presentation layer
     that happens to display it. */
  var contextState = {
    scheme: '',
    branch: '',
    semester: ''
  };

  /* The option lists as they were last loaded, so a label can be resolved
     without reading it back out of a rendered control. */
  var contextOptions = {
    scheme: [],
    branch: [],
    semester: []
  };

  function readContext() {
    return {
      scheme: contextState.scheme,
      branch: contextState.branch,
      semester: contextState.semester
    };
  }

  function setContextValue(key, value) {
    if (!Object.prototype.hasOwnProperty.call(contextState, key)) { return; }
    contextState[key] = String(value === undefined || value === null ? '' : value);
  }

  function contextOptionLabel(key, value) {
    var options = contextOptions[key] || [];
    for (var i = 0; i < options.length; i += 1) {
      if (String(options[i].value) === String(value)) { return options[i].label; }
    }
    /* No match means the control has not been populated yet; showing the raw
       value is honest, whereas inventing a label would not be. */
    return String(value);
  }

  function isNarrowLayout() {
    return window.matchMedia('(max-width: 1023px)').matches;
  }

  function isPanelOverlayLayout() {
    return window.matchMedia('(max-width: 1279px)').matches;
  }

  /* The selected context as a short line, used as the second line of a Recent
     entry so the context a question was asked under stays visible. It states
     plainly when nothing is selected rather than implying a default. */
  function contextMeta() {
    var context = readContext();
    var parts = [];
    if (context.scheme) { parts.push(context.scheme + ' scheme'); }
    if (context.branch) { parts.push(context.branch); }
    if (context.semester) { parts.push('Semester ' + context.semester); }
    return parts.length > 0 ? parts.join(' \u00b7 ') : 'No context selected';
  }

  /* ------------------------------------------------------------------------
     State machine
     ------------------------------------------------------------------------
     Two independent things decide what is on screen:

       ui.state — which interface state the conversation column is in
                  (empty, loading, error, missing context, no evidence, or
                  the answered conversation)
       ui.view  — which section is selected in the sidebar (Chat, Syllabus,
                  Circulars)

     Both are drawn by renderVisibility() alone, so there is one place that
     decides what is visible and the two can never disagree with each other.
     ------------------------------------------------------------------------ */

  function setState(name) {
    ui.state = name;
    renderVisibility();
  }

  function setView(name) {
    ui.view = (name === 'syllabus' || name === 'circulars') ? name : 'chat';
    syncNav();
    renderVisibility();
  }

  function renderVisibility() {
    var chat = ui.view === 'chat';

    Object.keys(STATE_ELEMENTS).forEach(function (key) {
      var node = byId(STATE_ELEMENTS[key]);
      if (!node) { return; }
      node.hidden = !chat || key !== ui.state;
    });

    el.viewSyllabus.hidden = ui.view !== 'syllabus';
    el.viewCirculars.hidden = ui.view !== 'circulars';

    syncMessageList();
  }

  function syncMessageList() {
    /* The transcript is not a state: it stays visible underneath whatever is
       happening below it, so asking a second question never blanks the first
       answer. Only its emptiness hides it, and it belongs to the chat view. */
    el.messageList.hidden = ui.view !== 'chat' || el.messageList.childElementCount === 0;
  }

  /* The three sections, paired with the buttons that select them. Built on
     demand rather than cached at load, because the elements are looked up
     after cache() has run. */
  function navItems() {
    return [
      { view: 'chat', node: el.navChat },
      { view: 'syllabus', node: el.navSyllabus },
      { view: 'circulars', node: el.navCirculars }
    ];
  }

  function syncNav() {
    navItems().forEach(function (item) {
      var active = ui.view === item.view;
      item.node.classList.toggle('is-active', active);
      /* aria-current is removed as well as added, so exactly one section is
         ever current and a stale value is never left behind. */
      if (active) {
        item.node.setAttribute('aria-current', 'page');
      } else {
        item.node.removeAttribute('aria-current');
      }
    });
  }

  function syncComposer() {
    var hasText = el.composerInput.value.trim() !== '';
    el.composerSend.disabled = ui.busy || !hasText;
    el.composer.setAttribute('aria-busy', ui.busy ? 'true' : 'false');
  }

  /* ------------------------------------------------------------------------
     Sidebar and scrim
     ------------------------------------------------------------------------ */

  function syncSidebarAria() {
    var expanded = isNarrowLayout()
      ? el.app.classList.contains('is-sidebar-open')
      : !el.app.classList.contains('is-sidebar-closed');
    el.sidebarToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  function syncScrim() {
    /* The scrim is only used where a surface genuinely overlays content:
       the off-canvas drawer on narrow screens, and the panel overlay below
       1280px. When both are docked, nothing is covered and no scrim is shown. */
    var drawer = el.app.classList.contains('is-sidebar-open');
    var panel = el.app.classList.contains('is-panel-open') && isPanelOverlayLayout();
    el.scrim.hidden = !(drawer || panel);
  }

  function toggleSidebar() {
    if (isNarrowLayout()) {
      el.app.classList.toggle('is-sidebar-open');
    } else {
      el.app.classList.toggle('is-sidebar-closed');
    }
    syncSidebarAria();
    syncScrim();
  }

  function openSidebar() {
    if (isNarrowLayout()) {
      el.app.classList.add('is-sidebar-open');
    } else {
      el.app.classList.remove('is-sidebar-closed');
    }
    syncSidebarAria();
    syncScrim();
  }

  function closeSidebar() {
    if (isNarrowLayout()) {
      el.app.classList.remove('is-sidebar-open');
    } else {
      el.app.classList.add('is-sidebar-closed');
    }
    syncSidebarAria();
    syncScrim();
  }

  /* ------------------------------------------------------------------------
     Theme
     ------------------------------------------------------------------------
     Only the data-theme attribute on <html> changes. Every colour is a token
     in tokens.css, so switching themes restyles the whole interface — sidebar,
     header, messages, controls, citations, and the source panel — without a
     reload and without a second stylesheet.

     Dark is the default and is already set in the markup, so a fresh session
     never paints light first and then flips. The choice is deliberately not
     persisted: storing it would mean browser storage, which is a decision the
     requirements do not authorise yet (documented in the implementation
     report and REQUIREMENTS.md D3).
     ------------------------------------------------------------------------ */

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function syncThemeToggle(theme) {
    var toLight = theme === 'dark';
    /* The accessible name describes the action, not the current state, so it
       is never ambiguous to a screen-reader user. */
    el.themeToggle.setAttribute('aria-label', toLight ? 'Switch to light mode' : 'Switch to dark mode');
    /* The visible icon matches the name: sun means "go to light". */
    el.themeIconSun.hidden = !toLight;
    el.themeIconMoon.hidden = toLight;
    /* The profile popover reports the theme as a fact about this build, so it
       is kept in step with the attribute rather than left stating "Dark". */
    el.popoverTheme.textContent = toLight ? 'Dark' : 'Light';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
    syncThemeToggle(currentTheme());
  }

  function toggleTheme() {
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    announce(next === 'light' ? 'Light theme enabled.' : 'Dark theme enabled.');
  }

  /* ------------------------------------------------------------------------
     Context
     ------------------------------------------------------------------------ */

  function renderContextOptions(grouped) {
    Object.keys(CONTEXT_SELECTS).forEach(function (key) {
      var select = byId(CONTEXT_SELECTS[key]);
      var options = (grouped && grouped[key]) || [];
      contextOptions[key] = options.slice();
      select.textContent = '';
      options.forEach(function (option) {
        var node = document.createElement('option');
        node.value = option.value;
        node.textContent = option.label;
        select.appendChild(node);
      });
      /* Nothing is selected on the user's behalf. The control is pointed at
         whatever the state already holds — which is empty in a fresh session,
         even though one scheme may be far more common than the others. */
      select.value = contextState[key];
    });
    renderContextSummary();
  }

  function renderContextSummary() {
    var context = readContext();
    var parts = [];
    Object.keys(CONTEXT_SELECTS).forEach(function (key) {
      if (context[key] !== '') {
        parts.push(contextOptionLabel(key, context[key]));
      }
    });

    var missing = api.findMissingContext(context);
    var text;
    if (parts.length === 0) {
      text = 'No context selected';
    } else if (missing.length > 0) {
      text = parts.join(' \u00b7 ') + ' \u00b7 incomplete';
    } else {
      text = parts.join(' \u00b7 ');
    }

    el.contextSummaryText.textContent = text;
    el.contextSummary.classList.toggle('is-incomplete', missing.length > 0);
    el.contextSummary.setAttribute(
      'aria-label',
      'Academic context: ' + text + '. Activate to change it.'
    );
  }

  function onContextChange(event) {
    /* The control is an input to the state, never the state itself. */
    var select = event && event.target;
    if (select && select.name) { setContextValue(select.name, select.value); }

    renderContextSummary();
    /* A question held back for missing context is asked again as soon as the
       context is complete, which is what the missing-context state promises. */
    if (ui.pendingQuestion && api.findMissingContext(readContext()).length === 0) {
      var question = ui.pendingQuestion;
      ui.pendingQuestion = null;
      runQuestion(question, false);
    }
  }

  /* ------------------------------------------------------------------------
     Rendering an answer
     ------------------------------------------------------------------------ */

  function refsInto(container, refs) {
    (refs || []).forEach(function (citationId) {
      var citation = ui.sourceById[citationId];
      var number = ui.sourceIndex[citationId];
      if (!citation || !number) {
        /* A marker without a matching source record is not rendered, because
           a reference that cannot be opened would be a fabricated citation. */
        window.console.warn('VTU Assistant: reference to an unknown source was skipped.', citationId);
        return;
      }
      var marker = el.tplRef.content.firstElementChild.cloneNode(true);
      marker.textContent = '[' + number + ']';
      marker.setAttribute('data-citation-id', citationId);
      marker.setAttribute('aria-label', 'Open source ' + number + ': ' + citation.title + ', ' + pageLabel(citation));
      container.appendChild(document.createTextNode(' '));
      container.appendChild(marker);
    });
  }

  /* Real syllabus and regulation documents carry credit and module tables, so
     a table block is rendered as a real table — with a caption and column
     headers — inside a wrapper that scrolls on a narrow screen instead of
     widening the page. Cells are filled with textContent like every other
     piece of retrieved text. */
  function renderTable(block) {
    var wrapper = document.createElement('div');
    wrapper.className = 'table-block';

    var scroller = document.createElement('div');
    scroller.className = 'table-wrap';

    var table = document.createElement('table');

    if (block.caption) {
      var caption = document.createElement('caption');
      caption.textContent = block.caption;
      table.appendChild(caption);
    }

    if (block.headers && block.headers.length > 0) {
      var head = document.createElement('thead');
      var headRow = document.createElement('tr');
      block.headers.forEach(function (label) {
        var th = document.createElement('th');
        th.setAttribute('scope', 'col');
        th.textContent = label;
        headRow.appendChild(th);
      });
      head.appendChild(headRow);
      table.appendChild(head);
    }

    var body = document.createElement('tbody');
    (block.rows || []).forEach(function (cells) {
      var row = document.createElement('tr');
      (cells || []).forEach(function (cell) {
        var td = document.createElement('td');
        td.textContent = cell === null || cell === undefined ? '' : String(cell);
        row.appendChild(td);
      });
      body.appendChild(row);
    });
    table.appendChild(body);

    scroller.appendChild(table);
    wrapper.appendChild(scroller);

    /* A table can be the evidence for a claim, so references attached to it
       are kept rather than dropped. */
    if (block.refs && block.refs.length > 0) {
      var refs = document.createElement('p');
      refs.className = 'table-block__refs';
      refsInto(refs, block.refs);
      wrapper.appendChild(refs);
    }

    return wrapper;
  }

  function renderBlock(block) {
    if (!block) { return null; }

    if (block.kind === 'heading') {
      var heading = document.createElement('h3');
      heading.textContent = block.text || '';
      return heading;
    }

    if (block.kind === 'table') {
      return renderTable(block);
    }

    if (block.kind === 'list') {
      var list = document.createElement(block.ordered ? 'ol' : 'ul');
      (block.items || []).forEach(function (item) {
        var li = document.createElement('li');
        li.textContent = item.text || '';
        refsInto(li, item.refs);
        list.appendChild(li);
      });
      return list;
    }

    var paragraph = document.createElement('p');
    paragraph.textContent = block.text || '';
    refsInto(paragraph, block.refs);
    return paragraph;
  }

  function renderSources(sources) {
    var wrap = document.createElement('div');
    wrap.className = 'sources';

    var title = document.createElement('p');
    title.className = 'sources__title';
    title.textContent = 'Sources used';
    wrap.appendChild(title);

    var list = document.createElement('ul');
    list.className = 'sources__list';

    sources.forEach(function (citation) {
      var item = el.tplChip.content.firstElementChild.cloneNode(true);
      var button = item.querySelector('.citation-chip');
      var page = pageLabel(citation);
      /* The type is shown only when the source records one. An unrecorded type
         is left blank rather than filled with a guess. */
      var type = citation.document_type ? capitalise(citation.document_type) : '';

      item.querySelector('.citation-chip__doc').textContent = citation.title;
      item.querySelector('.citation-chip__type').textContent = type;
      item.querySelector('.citation-chip__page').textContent = page;
      button.setAttribute('data-citation-id', citation.citation_id);
      button.setAttribute(
        'aria-label',
        'Open source: ' + citation.title + (type ? ', ' + type : '') + ', ' + page
      );
      list.appendChild(item);
    });

    wrap.appendChild(list);
    return wrap;
  }

  function appendMessage(role, modifier, buildBody) {
    var node = el.tplMessage.content.firstElementChild.cloneNode(true);
    node.classList.add(modifier);
    node.querySelector('.message__role').textContent = role;
    buildBody(node.querySelector('.message__body'));
    el.messageList.appendChild(node);
    syncMessageList();
    return node;
  }

  function renderUserMessage(text) {
    appendMessage('You', 'message--user', function (body) {
      body.textContent = text;
    });
  }

  function renderAnswer(answer) {
    ui.sourceIndex = {};
    ui.sourceById = {};

    var sources = answer.sources || [];
    sources.forEach(function (citation, position) {
      ui.sourceById[citation.citation_id] = citation;
      ui.sourceIndex[citation.citation_id] = position + 1;
    });

    var node = appendMessage('Assistant', 'message--assistant', function (body) {
      var answerBody = document.createElement('div');
      answerBody.className = 'answer';
      (answer.blocks || []).forEach(function (block) {
        var rendered = renderBlock(block);
        if (rendered) { answerBody.appendChild(rendered); }
      });
      if (sources.length > 0) {
        answerBody.appendChild(renderSources(sources));
      }
      body.appendChild(answerBody);
    });

    attachCopy(node, answer);
  }

  /* Copying is offered only where the Clipboard API exists, which means a
     secure context (https or localhost). Elsewhere the control stays hidden
     rather than being shown and then failing. */
  function canCopy() {
    return !!(window.navigator && navigator.clipboard &&
      typeof navigator.clipboard.writeText === 'function');
  }

  /* The copied text is built from the same structured blocks that produced the
     answer, not read back out of the rendered page: app.js never scrapes the
     DOM for data. */
  function blocksToText(blocks) {
    var lines = [];
    (blocks || []).forEach(function (block) {
      if (!block) { return; }

      if (block.kind === 'heading') {
        lines.push(String(block.text || ''));
        return;
      }

      if (block.kind === 'table') {
        if (block.caption) { lines.push(String(block.caption)); }
        if (block.headers) { lines.push(block.headers.join('\t')); }
        (block.rows || []).forEach(function (row) { lines.push((row || []).join('\t')); });
        return;
      }

      if (block.kind === 'list') {
        (block.items || []).forEach(function (item, index) {
          lines.push((block.ordered ? (index + 1) + '. ' : '- ') + String(item.text || ''));
        });
        return;
      }

      lines.push(String(block.text || ''));
    });
    return lines.join('\n');
  }

  function copyTextForAnswer(answer) {
    var parts = [blocksToText(answer.blocks)];
    var sources = answer.sources || [];

    if (sources.length > 0) {
      parts.push('');
      parts.push('Sources used');
      sources.forEach(function (citation, index) {
        parts.push(
          '[' + (index + 1) + '] ' + citation.title +
          (citation.document_type ? '. ' + capitalise(citation.document_type) : '') +
          '. ' + pageLabel(citation) + '.'
        );
      });
    }

    return parts.join('\n');
  }

  function attachCopy(node, answer) {
    var tools = node.querySelector('.message__tools');
    var button = node.querySelector('.message__copy');
    if (!tools || !button || !canCopy()) { return; }

    var text = copyTextForAnswer(answer);
    if (text.trim() === '') { return; }

    tools.hidden = false;
    button.addEventListener('click', function () {
      var label = button.querySelector('.message__copy-label');
      navigator.clipboard.writeText(text).then(function () {
        button.classList.add('is-copied');
        if (label) { label.textContent = 'Copied'; }
        announce('Answer copied to the clipboard.');
        window.setTimeout(function () {
          button.classList.remove('is-copied');
          if (label) { label.textContent = 'Copy answer'; }
        }, 2000);
      }).catch(function () {
        /* A refused clipboard is not an error state for the conversation: the
           answer is still on screen and can be selected by hand. */
        announce('The answer could not be copied. Select the text instead.');
      });
    });
  }

  function scrollToLatest() {
    el.conversation.scrollTop = el.conversation.scrollHeight;
  }

  /* ------------------------------------------------------------------------
     Asking a question
     ------------------------------------------------------------------------ */

  function clearComposer() {
    el.composerInput.value = '';
    autoSizeComposer();
    syncComposer();
  }

  /* New chat / Clear conversation.
     The transcript, the question held back for missing context, the last
     question, and the source maps are all cleared. Dropping the source maps
     matters: otherwise "Try again" could re-ask the previous conversation's
     question, and a stale citation marker could still resolve to a record
     that is no longer on screen.

     The Recent list is deliberately kept. It is the session's record of which
     questions have been asked, not part of the transcript, and emptying it
     would mean retyping a question the sidebar is still offering to repeat.
     Nothing in it is invented: it only ever lists questions the user typed. */
  function startNewChat() {
    /* A new chat is a chat action, so the workspace returns to Chat first. */
    setView('chat');

    el.messageList.textContent = '';
    ui.pendingQuestion = null;
    ui.lastQuestion = null;
    ui.sourceIndex = {};
    ui.sourceById = {};

    el.contextMissingFields.textContent = '';
    el.contextMissingFields.hidden = true;

    /* Closes the source panel and returns focus to the composer, so the panel
       can never outlive the answer its citation belonged to. */
    ui.panelTrigger = null;
    closeCitation();

    clearComposer();
    renderRecent();
    setState('empty');

    el.composerInput.focus();
    announce('New chat started.');
  }

  /* Returns true when the question was accepted. Callers use that to decide
     whether to clear the composer, so a question typed while a request is in
     flight is never silently discarded. */
  function runQuestion(question, appendUserMessage) {
    var text = String(question || '').trim();
    if (text === '' || ui.busy) { return false; }

    /* Asking is a chat action, so a question typed while browsing Syllabus or
       Circulars brings the conversation back rather than answering into a
       hidden column. */
    setView('chat');

    if (appendUserMessage !== false) { renderUserMessage(text); }

    ui.lastQuestion = text;
    recordRecent(text);

    ui.busy = true;
    syncComposer();
    setState('loading');
    announce('Searching the indexed documents for the selected academic context.');
    scrollToLatest();

    api.askQuestion({ question: text, context: readContext() })
      .then(handleResult)
      .catch(handleFailure)
      .then(function () {
        ui.busy = false;
        syncComposer();
      });

    return true;
  }

  function handleResult(result) {
    if (result.status === 'needs-context') {
      /* The question is kept, not discarded, so completing the context
         answers it rather than asking the user to type it again. */
      ui.pendingQuestion = ui.lastQuestion;
      el.contextMissingFields.textContent = 'Missing: ' + result.labels.join(', ') + '.';
      el.contextMissingFields.hidden = false;
      setState('missing-context');
      announce('Academic context is required. Missing: ' + result.labels.join(', ') + '.');
      return;
    }

    ui.pendingQuestion = null;

    if (result.status === 'no-evidence') {
      el.noEvidenceBody.textContent = result.message;
      setState('no-evidence');
      announce('Nothing in the indexed documents answers this question, so it was not answered.');
      return;
    }

    renderAnswer(result.answer);
    setState('answered');
    announce(
      'Answer ready, with ' + (result.answer.sources || []).length + ' cited source' +
      ((result.answer.sources || []).length === 1 ? '' : 's') + '.'
    );
    scrollToLatest();
  }

  function handleFailure(error) {
    el.errorBody.textContent = (error && error.userMessage)
      ? error.userMessage
      : 'The request could not be completed. Your question has not been answered, and no answer has been guessed in its place.';
    setState('error');
    announce('The request could not be completed. The question was not answered.');
    scrollToLatest();
  }

  /* ------------------------------------------------------------------------
     Citation side panel
     ------------------------------------------------------------------------ */

  function clearViewer() {
    var frame = el.panelViewer.querySelector('.citation-panel__frame');
    if (frame) { el.panelViewer.removeChild(frame); }
  }

  function renderPanelMeta(citation) {
    el.panelMeta.textContent = '';

    var page = document.createElement('span');
    page.className = 'citation-panel__page';
    page.textContent = pageLabel(citation);
    el.panelMeta.appendChild(page);

    if (citation.document_type) {
      var type = document.createElement('span');
      type.textContent = capitalise(citation.document_type);
      el.panelMeta.appendChild(type);
    }

    if (citation.version_label) {
      var version = document.createElement('span');
      version.textContent = 'Version ' + citation.version_label;
      el.panelMeta.appendChild(version);
    }
  }

  function showUnavailable(citation, reason) {
    el.unavailableTitle.textContent = reason === 'no-source-url'
      ? 'No in-app preview for this source'
      : 'The source could not be previewed here';

    el.fbDocument.textContent = citation.title;
    el.fbVersion.textContent = citation.version_label ? 'Version ' + citation.version_label : 'Not specified';
    el.fbType.textContent = citation.document_type ? capitalise(citation.document_type) : 'Not specified';
    el.fbContext.textContent = contextLine(citation);
    el.fbPage.textContent = pageLabel(citation);

    el.unavailable.hidden = false;
  }

  /* The page fragment used by PDF viewers. It is appended only to a real
     source URL that does not already carry a fragment, and only when a page
     is actually recorded for the citation, so no destination is ever invented.
     Whether an embedded viewer honours the fragment depends on the server, so
     the panel says so rather than promising a jump. */
  function withPageFragment(url, citation) {
    if (url.indexOf('#') !== -1) { return { url: url, page: null }; }
    var page = citation.page_number || citation.page_start;
    if (!page) { return { url: url, page: null }; }
    return { url: url + '#page=' + page, page: page };
  }

  function clearPageNote() {
    el.pageNote.textContent = '';
    el.pageNote.hidden = true;
  }

  function openCitation(citationId, trigger) {
    var citation = ui.sourceById[citationId];
    if (!citation) { return; }

    ui.panelTrigger = trigger || null;
    clearViewer();
    clearPageNote();
    el.unavailable.hidden = true;
    el.panelTitle.textContent = citation.title;
    renderPanelMeta(citation);

    /* The panel opens before the preview is known, so the outcome of a slow
       or unavailable source never delays the citation itself being readable. */
    el.panel.hidden = false;
    el.app.classList.add('is-panel-open');
    syncScrim();
    el.panelClose.focus();

    api.getCitationTarget(citation).then(function (target) {
      if (target.status === 'available' && target.url) {
        var resolved = withPageFragment(target.url, citation);

        clearViewer();
        el.unavailable.hidden = true;
        var frame = document.createElement('iframe');
        frame.className = 'citation-panel__frame';
        frame.src = resolved.url;
        frame.loading = 'lazy';
        frame.setAttribute('referrerpolicy', 'no-referrer');
        frame.setAttribute('title', citation.title + ', ' + pageLabel(citation));
        el.panelViewer.appendChild(frame);

        el.openSource.href = resolved.url;

        /* A fragment is a request to the viewer, not a guarantee. Saying so is
           better than implying the cited page is definitely what appeared. */
        if (resolved.page) {
          el.pageNote.textContent = 'Opened with a #page=' + resolved.page +
            ' fragment. Some viewers ignore it, so check the page number shown above.';
          el.pageNote.hidden = false;
        }

        el.panelFooter.hidden = false;
      } else {
        /* No URL, or no usable preview. The citation stays complete — document
           name, version, and original page — and the app says the preview is
           unavailable instead of linking somewhere invented. */
        clearViewer();
        showUnavailable(citation, target.reason);
        el.openSource.removeAttribute('href');
        clearPageNote();
        el.panelFooter.hidden = true;
      }
      announce(citation.title + ', ' + pageLabel(citation) + '. Source panel opened.');
    }).catch(function () {
      clearViewer();
      showUnavailable(citation, 'preview-failed');
      el.openSource.removeAttribute('href');
      clearPageNote();
      el.panelFooter.hidden = true;
      announce('The source panel opened, but no preview was available.');
    });
  }

  function closeCitation() {
    el.panel.hidden = true;
    el.app.classList.remove('is-panel-open');
    clearViewer();
    clearPageNote();
    el.openSource.removeAttribute('href');
    el.panelFooter.hidden = true;
    syncScrim();
    if (ui.panelTrigger && document.contains(ui.panelTrigger)) {
      ui.panelTrigger.focus();
    } else {
      el.composerInput.focus();
    }
    ui.panelTrigger = null;
  }

  /* ------------------------------------------------------------------------
     Recent questions
     ------------------------------------------------------------------------
     The list is built from what was asked in this session. It is not loaded
     history: there is no persistence, so an empty list on a fresh page is the
     honest result and the empty message says so.

     Each entry also records the context the question was asked under, so a
     question asked with no context selected is not presented later as though
     it had one.
     ------------------------------------------------------------------------ */

  function recordRecent(question) {
    var text = String(question || '').trim();
    if (text === '') { return; }

    /* Asking the same question twice moves it up rather than repeating it. */
    ui.recent = ui.recent.filter(function (entry) { return entry.question !== text; });
    ui.recent.unshift({ question: text, context: contextMeta() });

    if (ui.recent.length > RECENT_LIMIT) {
      ui.recent.length = RECENT_LIMIT;
    }

    renderRecent();
  }

  function renderRecent() {
    el.recentList.textContent = '';
    el.recentEmpty.hidden = ui.recent.length > 0;

    ui.recent.forEach(function (entry) {
      var item = el.tplRecent.content.firstElementChild.cloneNode(true);
      var button = item.querySelector('.recent__item');
      var active = ui.lastQuestion !== null && entry.question === ui.lastQuestion;

      button.querySelector('.recent__label').textContent = entry.question;
      button.querySelector('.recent__meta').textContent = entry.context;
      button.setAttribute('data-recent-question', entry.question);
      button.classList.toggle('is-active', active);
      if (active) {
        button.setAttribute('aria-current', 'true');
      }

      el.recentList.appendChild(item);
    });
  }

  /* ------------------------------------------------------------------------
     Profile popover
     ------------------------------------------------------------------------
     An inline disclosure, so Escape closes it and it never traps focus. What
     it reports is a statement of fact about this build, not a signed-in user:
     there is no account, no storage, and no document index.
     ------------------------------------------------------------------------ */

  function syncProfilePopover() {
    el.profileBtn.setAttribute(
      'aria-expanded',
      el.profilePopover.hidden ? 'false' : 'true'
    );
  }

  function openProfilePopover() {
    el.profilePopover.hidden = false;
    syncProfilePopover();
  }

  function closeProfilePopover() {
    el.profilePopover.hidden = true;
    syncProfilePopover();
  }

  function toggleProfilePopover() {
    if (el.profilePopover.hidden) {
      openProfilePopover();
    } else {
      closeProfilePopover();
    }
  }

  /* ------------------------------------------------------------------------
     Composer
     ------------------------------------------------------------------------ */

  function autoSizeComposer() {
    el.composerInput.style.height = 'auto';
    el.composerInput.style.height = el.composerInput.scrollHeight + 'px';
  }

  /* ------------------------------------------------------------------------
     Prompt cards
     ------------------------------------------------------------------------ */

  function renderPrompts(prompts) {
    el.promptGrid.textContent = '';
    if (!prompts || prompts.length === 0) { return; }

    prompts.forEach(function (prompt) {
      var card = el.tplPrompt.content.firstElementChild.cloneNode(true);
      card.querySelector('.prompt-card__label').textContent = prompt.label;
      card.querySelector('.prompt-card__meta').textContent = prompt.meta;
      card.addEventListener('click', function () {
        if (runQuestion(prompt.question, true)) { clearComposer(); }
      });
      el.promptGrid.appendChild(card);
    });
  }

  /* ------------------------------------------------------------------------
     Wiring
     ------------------------------------------------------------------------ */

  function cache() {
    el.app = byId('app');
    el.sidebarToggle = byId('sidebar-toggle');
    el.newChat = byId('new-chat-btn');
    el.navChat = byId('nav-chat');
    el.navSyllabus = byId('nav-syllabus');
    el.navCirculars = byId('nav-circulars');
    el.recentList = byId('recent-list');
    el.recentEmpty = byId('recent-empty');
    el.profileBtn = byId('profile-btn');
    el.profilePopover = byId('profile-popover');
    el.profileClear = byId('profile-clear');
    el.popoverTheme = byId('popover-theme-state');
    el.contextSummary = byId('context-summary');
    el.contextSummaryText = byId('context-summary-text');
    el.themeToggle = byId('theme-toggle');
    el.themeIconSun = byId('theme-icon-sun');
    el.themeIconMoon = byId('theme-icon-moon');
    el.conversation = byId('conversation');
    el.messageList = byId('message-list');
    el.errorBody = byId('error-body');
    el.errorRetry = byId('error-retry');
    el.contextMissingOpen = byId('context-missing-open');
    el.contextMissingFields = byId('context-missing-fields');
    el.noEvidenceBody = byId('no-evidence-body');
    el.promptGrid = byId('prompt-grid');
    el.viewSyllabus = byId('view-syllabus');
    el.viewCirculars = byId('view-circulars');
    el.composer = byId('composer');
    el.composerInput = byId('composer-input');
    el.composerSend = byId('composer-send');
    el.panel = byId('citation-panel');
    el.panelTitle = byId('citation-panel-title');
    el.panelMeta = byId('citation-panel-meta');
    el.panelViewer = byId('citation-panel-viewer');
    el.panelClose = byId('citation-panel-close');
    el.panelFooter = byId('citation-panel-footer');
    el.openSource = byId('citation-open-source');
    el.pageNote = byId('citation-page-note');
    el.unavailable = byId('citation-unavailable');
    el.unavailableTitle = byId('citation-unavailable-title');
    el.fbDocument = byId('citation-fallback-document');
    el.fbVersion = byId('citation-fallback-version');
    el.fbType = byId('citation-fallback-type');
    el.fbContext = byId('citation-fallback-context');
    el.fbPage = byId('citation-fallback-page');
    el.scrim = byId('scrim');
    el.live = byId('live-region');
    el.tplMessage = byId('tpl-message');
    el.tplChip = byId('tpl-citation-chip');
    el.tplRef = byId('tpl-citation-ref');
    el.tplPrompt = byId('tpl-prompt-card');
    el.tplRecent = byId('tpl-recent-item');
  }

  function bindEvents() {
    el.sidebarToggle.addEventListener('click', toggleSidebar);
    el.themeToggle.addEventListener('click', toggleTheme);

    el.contextSummary.addEventListener('click', function () {
      openSidebar();
      var missing = api.findMissingContext(readContext());
      var target = byId(CONTEXT_SELECTS[missing[0] || 'scheme']);
      if (target) { target.focus(); }
    });

    el.contextMissingOpen.addEventListener('click', function () {
      openSidebar();
      var missing = api.findMissingContext(readContext());
      var target = byId(CONTEXT_SELECTS[missing[0] || 'scheme']);
      if (target) { target.focus(); }
    });

    Object.keys(CONTEXT_SELECTS).forEach(function (key) {
      byId(CONTEXT_SELECTS[key]).addEventListener('change', onContextChange);
    });

    el.newChat.addEventListener('click', startNewChat);

    /* Section navigation. Selecting Syllabus or Circulars is a real, visible
       change of section with no invented content behind it. */
    navItems().forEach(function (item) {
      item.node.addEventListener('click', function () {
        setView(item.view);
        announce(item.view === 'chat'
          ? 'Chat workspace.'
          : (item.view === 'syllabus' ? 'Syllabus section.' : 'Circulars section.'));

        /* On a phone the sidebar is a drawer that would cover whichever
           section was just selected, so it closes for every section rather
           than only the two that replace the conversation. */
        if (isNarrowLayout()) {
          closeSidebar();
          el.sidebarToggle.focus();
        }
      });
    });

    /* The "Ask a question instead" buttons inside the Syllabus and Circulars
       views. Delegated from the conversation column so both views (and any
       added later) are covered by one handler. */
    el.conversation.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-goto-view]');
      if (!trigger) { return; }
      setView(trigger.getAttribute('data-goto-view'));
      el.composerInput.focus();
    });

    /* A recent question is asked through exactly the same path as a typed one,
       so it cannot behave differently from one. */
    el.recentList.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-recent-question]');
      if (!trigger) { return; }
      if (runQuestion(trigger.getAttribute('data-recent-question'), true)) {
        clearComposer();
      }
      if (isNarrowLayout()) { closeSidebar(); }
    });

    el.profileBtn.addEventListener('click', toggleProfilePopover);

    el.profileClear.addEventListener('click', function () {
      closeProfilePopover();
      startNewChat();
    });

    /* A click anywhere outside the disclosure closes it. The button itself is
       excluded, because its own handler has already decided the new state. */
    document.addEventListener('click', function (event) {
      if (el.profilePopover.hidden) { return; }
      if (el.profilePopover.contains(event.target)) { return; }
      if (el.profileBtn.contains(event.target)) { return; }
      closeProfilePopover();
    });

    el.composer.addEventListener('submit', function (event) {
      event.preventDefault();
      if (runQuestion(el.composerInput.value, true)) { clearComposer(); }
    });

    el.composerInput.addEventListener('input', function () {
      autoSizeComposer();
      syncComposer();
    });

    el.composerInput.addEventListener('keydown', function (event) {
      /* Enter sends; Shift+Enter is a newline. isComposing is checked so that
         confirming an IME candidate does not send a half-typed question. */
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        el.composer.requestSubmit();
      }
    });

    el.errorRetry.addEventListener('click', function () {
      if (ui.lastQuestion) { runQuestion(ui.lastQuestion, false); }
    });

    /* Citation markers and chips are many and are replaced often, so the
       handlers live on the containers that hold them. */
    el.messageList.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-citation-id]');
      if (trigger) { openCitation(trigger.getAttribute('data-citation-id'), trigger); }
    });

    el.panelClose.addEventListener('click', closeCitation);

    el.scrim.addEventListener('click', function () {
      if (el.app.classList.contains('is-sidebar-open')) {
        closeSidebar();
      } else {
        closeCitation();
      }
    });

    /* Escape closes the surface that is on top, innermost first: the source
       panel, then the profile disclosure, then the narrow-screen drawer. */
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') { return; }
      if (!el.panel.hidden) {
        closeCitation();
      } else if (!el.profilePopover.hidden) {
        closeProfilePopover();
        el.profileBtn.focus();
      } else if (el.app.classList.contains('is-sidebar-open')) {
        closeSidebar();
        el.sidebarToggle.focus();
      }
    });

    /* Crossing the breakpoint changes what the sidebar state means: a
       drawer that is open at 900px must not leave the docked sidebar closed
       at 1400px, and the aria-expanded value has to follow. */
    var wide = window.matchMedia('(max-width: 1023px)');
    var onBreakpointChange = function () {
      el.app.classList.remove('is-sidebar-open');
      syncSidebarAria();
      syncScrim();
    };
    if (wide.addEventListener) {
      wide.addEventListener('change', onBreakpointChange);
    } else if (wide.addListener) {
      wide.addListener(onBreakpointChange);
    }
  }

  /* ------------------------------------------------------------------------
     Start-up
     ------------------------------------------------------------------------ */

  function init() {
    cache();

    if (!api) {
      /* Without the data seam there is nothing honest to show, so the error
         state is used rather than a partially working interface. */
      el.errorBody.textContent = 'The data layer did not load, so questions cannot be answered. No answer has been guessed in its place.';
      el.errorRetry.hidden = true;
      setState('error');
      return;
    }

    bindEvents();
    /* The new surfaces are synced from state rather than trusted to match the
       markup, so the attribute values the markup ships with and the values at
       run time cannot drift apart. */
    syncNav();
    renderRecent();
    syncProfilePopover();
    setState('empty');
    syncSidebarAria();
    syncScrim();
    syncComposer();
    /* The markup already states the default theme; this only makes the button
       name and icon agree with it. */
    syncThemeToggle(currentTheme());
    renderContextSummary();

    api.getContextOptions()
      .then(renderContextOptions)
      .catch(function () {
        el.errorBody.textContent = 'The academic context options could not be loaded.';
        setState('error');
      });

    api.getSuggestedPrompts()
      .then(renderPrompts)
      .catch(function () {
        /* Prompt suggestions are a convenience: losing them must not take the
           question box away, so this failure is not escalated to the error
           state. */
        renderPrompts([]);
      });
  }

  init();
})();
