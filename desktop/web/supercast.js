// Supercast tab (desktop app, Apps section): which MP3s in Topic Log Data/audio are not on Supercast yet, upload
// them through a browser window, and a daily upload time. Talks to the local server under /api/sc/.
(function () {
  if (document.documentElement.dataset.edition === 'customer') return;
  const root = document.getElementById('dash-root');
  const tabs = root && root.querySelector('.tl-tabs');
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
    const r = await fetch('/api/sc/' + path, body === undefined ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json(); if (j.error) throw new Error(j.error); return j;
  };
  const fmt = (iso) => iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '–';
  const LABEL = { pending: 'Not uploaded', published: 'Published', draft: 'Draft on Supercast', uploaded: 'Uploaded by Topic Log',
                  skipped: 'Skipped', 'older version': 'Older version' };

  // ---------------------------------------------------------------- tab + page
  const tab = h('button', { class: 'tl-tab', role: 'tab', id: 'tab-supercast', 'data-ep': 'supercast', 'data-group': 'apps', 'aria-selected': 'false' }, 'Supercast');
  tabs.append(tab);
  const page = h('section', { class: 'tl-page', id: 'supercast', role: 'tabpanel', 'aria-labelledby': 'tab-supercast', hidden: true });
  [...root.querySelectorAll('.tl-page')].pop().after(page);
  let timer = null, cfg = null, list = null, showAll = false;
  function show() {
    root.querySelectorAll('.tl-page').forEach((p) => { p.hidden = p !== page; });
    tabs.querySelectorAll('.tl-tab').forEach((b) => b.setAttribute('aria-selected', b === tab ? 'true' : 'false'));
    try { history.replaceState(null, '', '#supercast'); } catch (e) { /* ignore */ }
    load();
  }
  tab.addEventListener('click', show);
  tabs.addEventListener('click', (e) => { const b = e.target.closest('.tl-tab'); if (b && b !== tab) { page.hidden = true; tab.setAttribute('aria-selected', 'false'); } });

  // ---------------------------------------------------------------- settings card
  const tok = h('input', { type: 'password', class: 'ep-input', placeholder: 'Supercast API token', 'aria-label': 'Supercast API token', autocomplete: 'off' });
  const site = h('input', { class: 'ep-input', placeholder: 'e.g. metrixxjocelyn', 'aria-label': 'Supercast site' });
  const mode = h('select', { 'aria-label': 'Upload as' }, h('option', { value: 'draft' }, 'Save as draft'), h('option', { value: 'publish' }, 'Publish now'));
  const email = h('input', { type: 'checkbox', 'aria-label': 'Email subscribers' });
  const on = h('input', { type: 'checkbox', 'aria-label': 'Daily upload on' });
  const at = h('input', { type: 'time', 'aria-label': 'Daily upload time (Chicago)' });
  const setMsg = h('span', { class: 'tl-note' });
  async function save() {
    setMsg.textContent = 'Saving…';
    try {
      cfg = await api('settings', { supercast_token: tok.value, supercast_site: site.value, supercast_mode: mode.value,
        supercast_email: email.checked, supercast_on: on.checked, supercast_time: at.value });
      tok.value = ''; setMsg.textContent = 'Saved.'; draw();
    } catch (e) { setMsg.textContent = e.message; }
  }
  const setCard = h('div', { class: 'tl-card' },
    h('h3', null, 'Supercast'),
    h('p', { class: 'tl-note' }, 'Check compares the MP3s in Topic Log Data/audio with the episodes on Supercast (API, read only). Supercast has no upload API, so Upload opens a browser window and fills in Episodes › New Episode for you. The first time, log in to Supercast in that window; it stays logged in.'),
    h('div', { class: 'sc-form' },
      h('label', null, h('b', null, 'API token'), tok),
      h('label', null, h('b', null, 'Site'), h('span', { class: 'sc-site' }, 'https://', site, '.supercast.com')),
      h('label', null, h('b', null, 'Upload as'), mode),
      h('label', { class: 'sc-inline' }, email, ' Email subscribers when publishing'),
      h('label', { class: 'sc-inline' }, on, ' Upload new MP3s every day at ', at, ' Chicago time')),
    h('div', { class: 'mp4-row' }, h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save'), setMsg),
    h('p', { class: 'tl-note', id: 'sc-auto' }));

  // ---------------------------------------------------------------- list + log
  const msg = h('span', { class: 'tl-note' });
  const listBox = h('div', { class: 'sc-list' });
  const logBox = h('pre', { class: 'sc-log', hidden: true });
  const allBox = h('input', { type: 'checkbox', 'aria-label': 'Show all MP3s', onchange: (e) => { showAll = e.target.checked; drawList(); } });
  const checkBtn = h('button', { class: 'btn', type: 'button', onclick: check }, 'Check');
  const upBtn = h('button', { class: 'btn primary', type: 'button', onclick: upload }, 'Upload selected');
  const skipBtn = h('button', { class: 'btn', type: 'button', onclick: () => mark('skip') }, 'Skip selected');
  const listCard = h('div', { class: 'tl-card' },
    h('h3', null, 'MP3s'),
    h('div', { class: 'mp4-row' }, checkBtn, upBtn, skipBtn, h('label', { class: 'sc-inline' }, allBox, ' Show uploaded and older versions'),
      h('button', { class: 'btn', type: 'button', onclick: () => api('open', {}) }, 'Open folder'), msg),
    listBox, logBox);
  page.append(setCard, listCard);

  const chosen = () => [...listBox.querySelectorAll('input[type=checkbox]:checked')].map((c) => c.value);
  async function check() {
    msg.textContent = 'Checking Supercast…';
    try { list = await api('check', {}); msg.textContent = `${list.remote_count} episodes on Supercast · ${list.pending} MP3(s) not uploaded · checked ${fmt(list.checked)}`; }
    catch (e) { msg.textContent = e.message; }
    drawList();
  }
  async function upload() {
    const f = chosen();
    if (!f.length) { msg.textContent = 'Tick the MP3s to upload.'; return; }
    try { cfg = await api('upload', { files: f }); msg.textContent = 'Uploading… a browser window opens.'; draw(); poll(); }
    catch (e) { msg.textContent = e.message; }
  }
  async function mark(what) {
    const f = chosen();
    if (!f.length) { msg.textContent = 'Tick the MP3s first.'; return; }
    try { await api(what, { files: f }); await check(); } catch (e) { msg.textContent = e.message; }
  }
  function drawList() {
    if (!list) { put(listBox, h('p', { class: 'tl-note' }, 'Press Check to see which MP3s are not on Supercast yet.')); return; }
    const rows = list.files.filter((r) => showAll || r.status === 'pending');
    if (!rows.length) { put(listBox, h('p', { class: 'tl-note' }, showAll ? `No MP3s in ${list.folder}.` : 'Everything is on Supercast.')); return; }
    put(listBox, h('table', { class: 'sc-table' },
      h('thead', null, h('tr', null, h('th', null, ''), h('th', null, 'Title'), h('th', null, 'File'), h('th', null, 'Date'), h('th', null, 'MB'), h('th', null, 'Status'))),
      h('tbody', null, rows.map((r) => h('tr', { class: 'st-' + r.status.replace(/\s/g, '-') },
        h('td', null, h('input', { type: 'checkbox', value: r.file, checked: r.status === 'pending', 'aria-label': r.title })),
        h('td', null, r.title), h('td', null, h('code', null, r.file)), h('td', null, r.date), h('td', null, r.size_mb),
        h('td', null, LABEL[r.status] || r.status, r.status === 'skipped' ? h('button', { class: 'btn sc-mini', type: 'button',
          onclick: async () => { await api('unskip', { files: [r.file] }); check(); } }, 'Undo') : null))))));
  }
  function draw() {
    if (!cfg) return;
    tok.placeholder = cfg.token ? 'Token saved (type to replace)' : 'Supercast API token (Settings › API)';
    site.value = site.value || cfg.site; mode.value = cfg.mode; email.checked = cfg.email; on.checked = cfg.on; at.value = cfg.time;
    const st = cfg.state || {}, last = st.last;
    put(page.querySelector('#sc-auto'), cfg.on
      ? `Daily upload is on: every day at ${cfg.time} Chicago time, new MP3s from the last 2 days are uploaded as ${cfg.mode === 'publish' ? 'published episodes' : 'drafts'} (older ones need a click). Topic Log has to be open then.`
      : 'Daily upload is off.',
      last ? ` Last ${last.auto ? 'scheduled ' : ''}upload ${fmt(last.at)}: ${last.note || `${last.done.length} uploaded, ${last.failed.length} failed`}${last.error ? ' · ' + last.error : ''}.` : '');
    logBox.hidden = !(st.log && st.log.length);
    logBox.textContent = (st.log || []).join('\n');
    upBtn.disabled = !!st.running;
    upBtn.textContent = st.running ? 'Uploading…' : 'Upload selected';
  }
  async function poll() {
    clearTimeout(timer);
    try { cfg = await api(''); draw(); } catch (e) { return; }
    if (cfg.state && cfg.state.running) timer = setTimeout(poll, 2000);
    else if (list) check();
  }
  async function load() {
    try { cfg = await api(''); } catch (e) { msg.textContent = e.message; return; }
    draw(); drawList();
    if (cfg.state && cfg.state.running) poll();
    else if (cfg.token && !list) check();
  }
  if (location.hash === '#supercast') show();
})();
