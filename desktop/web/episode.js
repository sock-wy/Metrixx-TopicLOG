// Episode tab (desktop app only): pick a topic -> Claude drafts a MYCAST script (with web search) ->
// edit / regenerate -> approve -> ElevenLabs MP3. Talks to the local server under /api/ep/.
(function () {
  const root = document.getElementById('dash-root');
  const tabs = root.querySelector('.tl-tabs');
  const pages = () => [...root.querySelectorAll('.tl-page')];
  if (!tabs) return;
  const h = (tag, attrs, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return e;
  };
  const put = (el, ...kids) => el.replaceChildren(...kids.flat().filter((c) => c != null && c !== false));
  const api = async (path, body) => {
    const r = await fetch('/api/ep/' + path, body === undefined ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json(); if (j.error) throw new Error(j.error); return j;
  };
  const fmt = (iso) => iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '–';
  const words = (s) => (s.trim().match(/\S+/g) || []).length;
  const STATUS = { draft: 'Draft', approved: 'Approved', audio: 'Audio made', discarded: 'Discarded' };

  // ---------------------------------------------------------------- tab + page
  const tab = h('button', { class: 'tl-tab', role: 'tab', id: 'tab-episode', 'data-ep': '1', 'aria-selected': 'false' }, 'Episode');
  tabs.append(tab);
  const page = h('section', { class: 'tl-page', id: 'episode', role: 'tabpanel', 'aria-labelledby': 'tab-episode', hidden: true });
  const last = pages().pop(); last.after(page);
  function show() {
    pages().forEach((p) => { p.hidden = p !== page; });
    tabs.querySelectorAll('.tl-tab').forEach((b) => b.setAttribute('aria-selected', b === tab ? 'true' : 'false'));
    try { history.replaceState(null, '', '#episode'); } catch (e) { /* ignore */ }
    refresh();
  }
  tab.addEventListener('click', show);
  tabs.querySelectorAll('.tl-tab:not([data-ep])').forEach((b) => b.addEventListener('click', () => { page.hidden = true; tab.setAttribute('aria-selected', 'false'); }));

  // ---------------------------------------------------------------- layout
  const pick = h('select', { 'aria-label': 'Topic for the episode' });
  const draftBtn = h('button', { class: 'btn primary', type: 'button' }, 'Draft script');
  const newMsg = h('span', { class: 'ep-msg' });
  const newCard = h('div', { class: 'tl-card' },
    h('h3', null, 'New MYCAST episode'),
    h('div', { class: 'ep-new' }, pick, draftBtn, newMsg),
    h('p', { class: 'tl-note' }, 'Claude reads this pull\'s digest, checks the story on the web and drafts a spoken script (1–3 minutes). Nothing is recorded until you approve the script and press Make audio.'));
  // own script (e.g. Jim's): paste it, skip the Claude draft, then approve -> Make audio as usual
  const pTitle = h('input', { class: 'ep-input', placeholder: 'Title', 'aria-label': 'Title of your script', style: 'flex:2 1 16rem' });
  const pTopic = h('input', { class: 'ep-input', placeholder: 'Ticker / topic (optional)', 'aria-label': 'Topic', style: 'flex:1 1 9rem' });
  const pText = h('textarea', { class: 'ep-script', placeholder: 'Paste the full spoken script here.', 'aria-label': 'Your script', style: 'min-height:12rem' });
  const pMsg = h('span', { class: 'ep-msg' });
  const pBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    if (dirty && !confirm('Discard unsaved edits in the open episode?')) return;
    pBtn.disabled = true;
    try { const ep = await api('paste', { title: pTitle.value, topic: pTopic.value, script: pText.value });
      pTitle.value = pTopic.value = pText.value = ''; pMsg.textContent = ''; pasteCard.open = false; dirty = false; await open(ep.id);
    } catch (e) { pMsg.textContent = e.message; }
    pBtn.disabled = false; refresh();
  } }, 'Use this script');
  const pasteCard = h('details', { class: 'tl-card ep-paste' }, h('summary', null, h('strong', null, 'Use my own script'), ' · paste a finished script (no Claude draft), then approve and Make audio with ElevenLabs'),
    h('div', { class: 'ep-row', style: 'margin-top:8px' }, pTitle, pTopic), pText, h('div', { class: 'ep-row' }, pBtn, pMsg));
  const list = h('div', { class: 'ep-list' });
  const editor = h('div', { class: 'tl-card' }, h('div', { class: 'ep-empty' }, 'Draft a script, or pick an episode on the left.'));
  page.append(newCard, pasteCard, h('div', { class: 'ep-grid' }, h('div', { class: 'ep-list-wrap' }, h('p', { class: 'tl-note', style: 'margin-bottom:6px' }, 'Episodes on this computer'), list), editor));

  let cur = null;          // episode shown in the editor
  let dirty = false;       // unsaved edits in the editor
  let timer = null;
  let keys = {};

  async function refresh() {
    let d;
    try { d = await api('list'); } catch (e) { newMsg.textContent = e.message; return; }
    keys = d.keys || {};
    // topic picker
    const run = d.candidates.run;
    const prev = pick.value;
    pick.replaceChildren(...(d.candidates.top.length ? [
      ...d.candidates.top.map((t) => h('option', { value: t.topic }, `#${t.rank} ${t.topic} · ${t.name || ''}${t.catalyst ? ' · ' + t.catalyst : ''}`)),
      h('option', { value: '' }, 'Let Claude choose from the top 3'),
    ] : [h('option', { value: '' }, 'No digest yet: pull first')]));
    if (prev && [...pick.options].some((o) => o.value === prev)) pick.value = prev;
    const missing = ['anthropic_api_key'].filter((k) => !keys[k]);
    draftBtn.disabled = !d.candidates.top.length || missing.length > 0;
    // pick of record = the 16:15 ET (15:15 CT) pull; any pull from 16:10 ET on counts (the day's first such pull)
    const hm = (run && run.run_et || '').slice(11, 16); const mins = hm ? Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3)) : -1;
    const record = mins >= 16 * 60 + 10;
    const ct = hm ? `${String((Number(hm.slice(0, 2)) + 23) % 24).padStart(2, '0')}:${hm.slice(3)} CT` : '';
    newMsg.textContent = missing.length ? 'Set the Anthropic key with Episode keys… in the app bar first (or use your own script below).'
      : run ? `From the pull of ${run.run_et.slice(0, 10)} ${ct}${record ? ' (pick of record)' : ' (not the 15:15 CT pick of record)'}.` : '';
    // list
    list.replaceChildren(...(d.episodes.length ? d.episodes.filter((e) => e.status !== 'discarded' || (cur && cur.id === e.id)).map((e) => h('button', {
      class: 'ep-item', type: 'button', 'aria-current': cur && cur.id === e.id ? 'true' : 'false', onclick: () => open(e.id),
    }, h('span', { class: 't' }, e.title || e.topic || 'Drafting…'),
    h('span', { class: 'm' }, h('span', { class: 'ep-status ' + (e.busy ? 'busy' : e.status) }, e.busy ? (e.busy === 'audio' ? 'Making audio…' : 'Drafting…') : STATUS[e.status] || e.status),
      `${e.date || ''} · ${e.topic || 'auto'} · v${e.versions}`))) : [h('p', { class: 'tl-note' }, 'None yet.')]));
    if (cur) {
      const fresh = d.episodes.find((e) => e.id === cur.id);
      if (fresh && (fresh.busy || cur.busy) && !dirty) open(cur.id, true);
    }
    clearTimeout(timer);
    if (d.episodes.some((e) => e.busy) && !page.hidden) timer = setTimeout(refresh, 3000);
  }

  draftBtn.addEventListener('click', async () => {
    if (dirty && !confirm('Discard unsaved edits in the open episode?')) return;
    draftBtn.disabled = true;
    try { const r = await api('new', { topic: pick.value || null }); dirty = false; await open(r.id); } catch (e) { newMsg.textContent = e.message; }
    draftBtn.disabled = false; refresh();
  });

  async function open(id, quiet) {
    if (!quiet && dirty && cur && cur.id !== id && !confirm('Discard unsaved edits?')) return;
    try { cur = await api(id); } catch (e) { put(editor, h('p', { class: 'ep-err' }, e.message)); return; }
    dirty = false; render(); if (!quiet) refresh();
  }

  async function act(action, body, msgEl) {
    try { cur = await api(`${cur.id}/${action}`, body || {}); dirty = false; render(); refresh(); return true; }
    catch (e) { (msgEl || editor.querySelector('.ep-msg.act')).textContent = e.message; return false; }
  }

  // ---------------------------------------------------------------- editor
  function render() {
    const ep = cur; if (!ep) return;
    const v = ep.versions[ep.versions.length - 1];
    const busy = ep.busy;
    if (!v) {
      put(editor, h('div', { class: 'ep-empty' }, busy ? `Claude is reading the digest and checking the story on the web${ep.topic ? ' for ' + ep.topic : ''}… (1–3 minutes)` : 'No draft.'),
        ep.error ? h('p', { class: 'ep-err' }, 'Draft failed: ' + ep.error) : null,
        ep.error ? h('div', { class: 'ep-row' }, h('button', { class: 'btn', type: 'button', onclick: () => { draftBtn.click(); } }, 'Try again')) : null);
      return;
    }
    const title = h('input', { class: 'ep-title', value: v.title || '', 'aria-label': 'Episode title', oninput: () => { dirty = true; saveBtn.disabled = false; } });
    const ta = h('textarea', { class: 'ep-script', 'aria-label': 'Script', spellcheck: 'true' });
    ta.value = v.script || '';
    const count = h('span');
    const upd = () => { const n = words(ta.value); count.textContent = `${n} words · about ${(n / 140).toFixed(1)} min spoken · ${ta.value.length} characters`; };
    ta.addEventListener('input', () => { dirty = true; saveBtn.disabled = false; upd(); }); upd();
    const msg = h('span', { class: 'ep-msg act' });
    const approved = ep.status === 'approved' || ep.status === 'audio';
    const saveBtn = h('button', { class: 'btn', type: 'button', disabled: true, onclick: () => act('save', { title: title.value, script: ta.value }) }, 'Save edits');
    const approveBtn = h('button', { class: 'btn primary', type: 'button', disabled: !!busy || approved && !dirty,
      onclick: () => act('approve', { title: title.value, script: ta.value }) }, approved && !dirty ? `Approved (v${ep.approved_version})` : 'Approve');
    const unapproveBtn = approved ? h('button', { class: 'btn', type: 'button', disabled: !!busy, onclick: () => act('unapprove') }, 'Back to draft') : null;
    const discardBtn = h('button', { class: 'btn danger', type: 'button', disabled: !!busy, onclick: () => { if (confirm('Discard this episode? It stays on disk but leaves the list.')) act('discard'); } }, 'Discard');
    const note = h('input', { class: 'ep-input', placeholder: 'Revision note for Claude, e.g. "shorter Teaching Moment, open with the 777X"', 'aria-label': 'Revision note' });
    const regenBtn = h('button', { class: 'btn', type: 'button', disabled: !!busy || !!ep.own_script, title: ep.own_script ? 'Your own script: edit it directly' : null, onclick: async () => {
      if (dirty && !confirm('Regenerate from the last saved version? Unsaved edits are lost.')) return;
      if (await act('regen', { note: note.value })) note.value = '';
    } }, busy === 'drafting' ? 'Regenerating…' : 'Regenerate');
    const expMd = h('button', { class: 'btn', type: 'button', onclick: async () => { try { const r = await api(`${ep.id}/export`, { format: 'md' }); msg.textContent = 'Saved ' + r.path; } catch (e) { msg.textContent = e.message; } } }, 'Export .md');
    const expTxt = h('button', { class: 'btn', type: 'button', onclick: async () => { try { const r = await api(`${ep.id}/export`, { format: 'txt' }); msg.textContent = 'Saved ' + r.path; } catch (e) { msg.textContent = e.message; } } }, 'Export .txt');
    const audioReady = approved && !dirty;
    const audioBtn = h('button', { class: 'btn primary', type: 'button', disabled: !!busy || !audioReady || !(keys.elevenlabs_api_key && keys.elevenlabs_voice_id),
      title: !(keys.elevenlabs_api_key && keys.elevenlabs_voice_id) ? 'Set the ElevenLabs key and voice ID with Keys…' : audioReady ? 'Render the approved script with ElevenLabs' : 'Approve the script first',
      onclick: () => act('audio') }, busy === 'audio' ? 'Making audio…' : ep.has_audio ? 'Make audio again' : 'Make audio');
    const audioRow = h('div', { class: 'ep-row' }, audioBtn);
    if (ep.has_audio) {
      audioRow.append(h('audio', { controls: true, preload: 'none', src: `/api/ep/${ep.id}/audio.mp3?t=${encodeURIComponent(ep.audio.at)}` }),
        h('button', { class: 'btn', type: 'button', onclick: () => api(`${ep.id}/reveal`, {}) }, 'Show file'),
        h('span', { class: 'ep-msg' }, `v${ep.audio.version} · ${(ep.audio.bytes / 1e6).toFixed(1)} MB${ep.audio.downloads ? ' · in Topic Log Data/audio' : ''}${ep.audio.version !== ep.approved_version ? ' · made from an older version' : ''}`));
    }
    if (!audioReady && !busy) audioRow.append(h('span', { class: 'ep-msg' }, dirty ? 'Save and approve your edits to make audio.' : 'Approve the script to make audio.'));
    const verSel = h('select', { class: 'ep-input', style: 'flex:0 0 auto', 'aria-label': 'Version history', onchange: () => {
      const n = Number(verSel.value); if (n === v.n) return;
      if (confirm(`Restore version ${n} as a new version?`)) act('restore', { n }); else verSel.value = String(v.n);
    } }, ...ep.versions.slice().reverse().map((x) => h('option', { value: String(x.n) }, `v${x.n} · ${x.source}${x.note ? ': ' + x.note.slice(0, 40) : ''} · ${fmt(x.at)}`)));
    verSel.value = String(v.n);
    const f = v.frame || {};
    const frame = h('table', { class: 'tl-table ep-frame' }, h('tbody', null,
      ...[['Tags', (f.tags || []).join(' · ')], ['Headline', f.headline], ['Deck', f.deck],
        ...(f.beats || []).map((b, i) => [`Beat ${i + 1}`, b]),
        ...(f.probabilities || []).map((p, i) => [`Probability ${i + 1}`, [p.venue, p.label, p.prob, p.note].filter(Boolean).join(' · ')]),
        ['Net Read', f.netread]].filter((r) => r[1]).map(([k, val]) => h('tr', null, h('td', null, k), h('td', null, String(val).replace(/<\/?(em|b)>/g, ''))))));
    put(editor, 
      h('div', { class: 'ep-head' }, title, h('span', { class: 'ep-status ' + (busy ? 'busy' : ep.status) }, busy ? (busy === 'audio' ? 'Making audio…' : 'Drafting…') : STATUS[ep.status]), verSel),
      h('div', { class: 'ep-meta' }, h('span', null, `${ep.name || ''} (${ep.topic || '–'})`), h('span', null, `Episode date ${ep.date}`),
        ep.own_script ? h('span', null, 'Own script (pasted)') : h('span', null, `Topic Log pull ${(ep.run && ep.run.run_et) || '–'} ET`), v.searches != null ? h('span', null, `${v.searches} web searches`) : null, count),
      v.why ? h('p', { class: 'ep-why' }, v.why) : null,
      ep.error ? h('p', { class: 'ep-err' }, 'Last step failed: ' + ep.error) : null,
      (v.checks || []).length ? h('div', { class: 'ep-checks' }, h('h4', null, 'Check before recording'), h('ul', null, ...v.checks.map((c) => h('li', null, c)))) : null,
      ta,
      h('div', { class: 'ep-row' }, saveBtn, approveBtn, unapproveBtn, discardBtn, expMd, expTxt, msg),
      ep.own_script ? null : h('div', { class: 'ep-row' }, note, regenBtn),
      audioRow,
      h('details', null, h('summary', null, 'Audio frame fields'), frame),
      (v.sources || []).length ? h('details', { class: 'ep-src' }, h('summary', null, `Sources (${v.sources.length})`),
        h('ul', null, ...v.sources.map((s) => h('li', null, h('a', { href: s.url, target: '_blank', rel: 'noopener' }, s.title || s.url))))) : null,
    );
  }

  // ---------------------------------------------------------------- keys in the app bar
  const bar = document.querySelector('.app-bar');
  const quit = document.getElementById('ab-quit');
  const kBtn = h('button', { type: 'button', title: 'Anthropic and ElevenLabs keys for MYCAST episodes' }, 'Episode keys…');
  const inp = (ph, label) => h('input', { type: 'password', placeholder: ph, 'aria-label': label, size: '16' });
  const kA = inp('Anthropic sk-ant-…', 'Anthropic API key'), kE = inp('ElevenLabs key', 'ElevenLabs API key'), kV = inp('Voice ID', 'ElevenLabs voice ID');
  kV.type = 'text';
  const kMsg = h('span');
  const kForm = h('span', { id: 'ab-keysform', hidden: true }, kA, kE, kV, h('button', { type: 'button', onclick: async () => {
    const body = { anthropic_api_key: kA.value, elevenlabs_api_key: kE.value, elevenlabs_voice_id: kV.value };
    try { keys = await api('keys', body); kA.value = kE.value = kV.value = ''; kForm.hidden = true; refresh(); if (cur) render(); } catch (e) { kMsg.textContent = e.message; }
  } }, 'Save'), kMsg);
  kBtn.addEventListener('click', async () => {
    kForm.hidden = !kForm.hidden;
    if (!kForm.hidden) {
      try { keys = await api('keys'); } catch (e) { /* ignore */ }
      kA.placeholder = keys.anthropic_api_key ? 'Anthropic key set (type to replace)' : 'Anthropic sk-ant-…';
      kE.placeholder = keys.elevenlabs_api_key ? 'ElevenLabs key set' : 'ElevenLabs key';
      kV.placeholder = keys.elevenlabs_voice_id ? 'Voice ID set' : 'Voice ID';
      kMsg.textContent = keys.path ? `Stored in ${keys.path}` : '';
      kA.focus();
    }
  });
  bar.insertBefore(kBtn, quit); bar.insertBefore(kForm, quit);

  if (location.hash === '#episode') show(); else refresh();
})();
