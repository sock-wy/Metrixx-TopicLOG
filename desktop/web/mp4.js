// Generating MP4 tab (desktop app, Apps section): MP3 + script -> scene images -> review -> Shotstack -> MP4.
// Talks to the local server under /api/mp4/. Each video is a folder in Topic Log Data/episodes/.
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
    const r = await fetch('/api/mp4/' + path, body === undefined ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json(); if (j.error) throw new Error(j.error); return j;
  };
  const STEPS = [['align', 'Word timings'], ['plan', 'Scene plan'], ['data', 'Prices & checks'], ['charts', 'Scene images'],
                 ['upload', 'Upload'], ['timeline', 'Timeline'], ['render', 'Render']];
  const STATUS = { queued: 'Queued', running: 'Working…', review: 'Ready to review', rendering: 'Rendering…', done: 'Done', error: 'Stopped' };
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

  // ---------------------------------------------------------------- tab + page
  const tab = h('button', { class: 'tl-tab', role: 'tab', id: 'tab-mp4', 'data-ep': 'mp4', 'data-group': 'apps', 'aria-selected': 'false' }, 'Generating MP4');
  tabs.append(tab);
  const page = h('section', { class: 'tl-page', id: 'mp4', role: 'tabpanel', 'aria-labelledby': 'tab-mp4', hidden: true });
  [...root.querySelectorAll('.tl-page')].pop().after(page);
  let timer = null, cur = null, data = null;
  function show() {
    root.querySelectorAll('.tl-page').forEach((p) => { p.hidden = p !== page; });
    tabs.querySelectorAll('.tl-tab').forEach((b) => b.setAttribute('aria-selected', b === tab ? 'true' : 'false'));
    try { history.replaceState(null, '', '#mp4'); } catch (e) { /* ignore */ }
    refresh();
  }
  tab.addEventListener('click', show);
  tabs.addEventListener('click', (e) => { const b = e.target.closest('.tl-tab'); if (b && b !== tab) { page.hidden = true; tab.setAttribute('aria-selected', 'false'); } });

  // ---------------------------------------------------------------- new video
  const epSel = h('select', { 'aria-label': 'Episode with audio' });
  const mp3In = h('input', { type: 'file', accept: '.mp3,audio/mpeg', 'aria-label': 'MP3 file' });
  const mdIn = h('input', { type: 'file', accept: '.md,.txt,text/plain,text/markdown', 'aria-label': 'Script file' });
  const msg = h('span', { class: 'tl-note' });
  const keysLine = h('p', { class: 'tl-note' });
  const read = (f, how) => new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = bad; r[how](f); });
  async function start(body) {
    msg.textContent = 'Starting…';
    try { const r = await api('start', body); cur = r.job; msg.textContent = ''; await refresh(); } catch (e) { msg.textContent = e.message; }
  }
  const fromEp = h('button', { class: 'btn primary', type: 'button', onclick: () => epSel.value ? start({ episode: epSel.value }) : (msg.textContent = 'No episode with audio yet.') }, 'Generate');
  const fromFiles = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const a = mp3In.files[0], s = mdIn.files[0];
    if (!a || !s) { msg.textContent = 'Choose both the MP3 and the script.'; return; }
    start({ audio_b64: await read(a, 'readAsDataURL'), audio_name: a.name, script: await read(s, 'readAsText'), script_name: s.name });
  } }, 'Generate');
  const newCard = h('div', { class: 'tl-card' },
    h('h3', null, 'Generating MP4'),
    h('p', { class: 'tl-note' }, 'MP3 + script → word timings (ElevenLabs) → scene plan (Claude) → prices and number checks → scene images (ApexCharts / DXcharts) → you review → Shotstack renders the MP4. Each video gets its own folder in Topic Log Data/episodes.'),
    keysLine,
    h('div', { class: 'mp4-row' }, h('b', null, 'From an episode'), epSel, fromEp),
    h('div', { class: 'mp4-row' }, h('b', null, 'From files'), h('label', null, 'MP3 ', mp3In), h('label', null, 'Script ', mdIn), fromFiles),
    msg);
  const list = h('div', { class: 'mp4-list' });
  const detail = h('div', { class: 'mp4-detail' });
  page.append(newCard, h('div', { class: 'mp4-grid' }, h('div', { class: 'tl-card' }, h('h3', null, 'Videos'), list), detail));

  // ---------------------------------------------------------------- data
  async function refresh() {
    try { data = await api('jobs'); } catch (e) { put(list, h('p', { class: 'tl-note' }, e.message)); return; }
    const k = data.keys;
    put(keysLine, `Keys: Anthropic ${k.anthropic ? '✓' : '✗'} · ElevenLabs ${k.elevenlabs ? '✓' : '✗'} · Shotstack ${k.shotstack ? '✓ (' + (k.shotstack_env === 'v1' ? 'production' : 'stage, watermarked') + ')' : '✗'} · prices from ${k.prices}. Set keys with Episode keys… and Data keys… in the app bar.`);
    const keep = epSel.value;
    put(epSel, data.episodes.length ? data.episodes.map((e) => h('option', { value: e.id }, `${e.date || ''} · ${e.topic || e.title || e.id}`)) : h('option', { value: '' }, 'No episode with audio yet'));
    if (keep) epSel.value = keep;
    if (!cur && data.jobs.length) cur = data.jobs[0].folder;
    put(list, data.jobs.length ? data.jobs.map((j) => h('button', { type: 'button', class: 'mp4-item' + (j.folder === cur ? ' on' : ''), onclick: () => { cur = j.folder; draw(); } },
      h('b', null, j.title || j.folder), h('span', null, `${j.folder} · ${STATUS[j.status] || j.status}`))) : h('p', { class: 'tl-note' }, 'No videos yet.'));
    draw();
    clearTimeout(timer);
    if (!page.hidden && data.jobs.some((j) => ['queued', 'running', 'rendering'].includes(j.status))) timer = setTimeout(refresh, 3000);
  }

  function draw() {
    const j = data && data.jobs.find((x) => x.folder === cur);
    if (!j) { put(detail); return; }
    const file = (p) => `/api/mp4/file/${encodeURIComponent(j.folder)}/${p}`;
    const steps = h('ol', { class: 'mp4-steps' }, STEPS.map(([k, label]) => {
      const s = (j.steps || {})[k] || {};
      return h('li', { class: 'st-' + (s.status || 'todo') }, h('b', null, label), s.msg ? h('span', null, ' · ' + s.msg) : null);
    }));
    const kids = [h('h3', null, j.title || j.folder), h('p', { class: 'tl-note' }, `${STATUS[j.status] || j.status} · folder ${data.root}/${j.folder}`), steps];
    if (j.status === 'error') {
      kids.push(h('p', { class: 'mp4-err' }, j.error || 'Stopped.'),
        h('button', { class: 'btn', type: 'button', onclick: async () => { await api(j.steps && j.steps.upload ? 'render' : 'retry', { job: j.folder }); refresh(); } }, 'Retry'));
    }
    if (j.status === 'review' || j.status === 'done' || (j.status === 'error' && j.scenes)) {
      if ((j.checks || []).length) kids.push(h('div', { class: 'mp4-checks' }, h('b', null, 'Check before rendering'), h('ul', null, j.checks.map((c) => h('li', { class: c.level }, c.msg)))));
      kids.push(h('div', { class: 'mp4-scenes' }, (j.scenes || []).map((s) => h('figure', null,
        h('a', { href: file(s.image), target: '_blank' }, h('img', { src: file(s.image) + '?t=' + encodeURIComponent(j.updated || ''), alt: `Scene ${s.n}`, loading: 'lazy' })),
        h('figcaption', null, h('b', null, `${s.n} · ${mmss(s.start)}–${mmss(s.end)}`), ` ${s.type} · starts at "${s.anchor || 'the beginning'}"`)))));
    }
    if (j.status === 'review') {
      const note = h('input', { class: 'ep-input', placeholder: 'Change something: e.g. "use a price chart for scene 4, shorter title on scene 2"', 'aria-label': 'Changes to the plan' });
      const env = data.keys.shotstack_env === 'v1' ? 'production (uses credits)' : 'stage (free, watermarked)';
      kids.push(h('div', { class: 'mp4-row' }, note, h('button', { class: 'btn', type: 'button', onclick: async () => { if (!note.value.trim()) return; await api('revise', { job: j.folder, note: note.value }); refresh(); } }, 'Redo plan')),
        h('div', { class: 'mp4-row' }, h('button', { class: 'btn primary', type: 'button', disabled: !data.keys.shotstack, onclick: async () => {
          try { await api('render', { job: j.folder }); refresh(); } catch (e) { alert(e.message); }
        } }, `Render on Shotstack · ${env}`)));
    }
    if (j.status === 'done' && j.video) {
      kids.push(h('video', { src: file(j.video), controls: true, class: 'mp4-video', preload: 'metadata' }),
        h('div', { class: 'mp4-row' }, h('button', { class: 'btn', type: 'button', onclick: () => api('open', { job: j.folder, what: 'video' }) }, 'Show MP4 in folder')));
    }
    kids.push(h('div', { class: 'mp4-row' }, h('button', { class: 'btn', type: 'button', onclick: () => api('open', { job: j.folder, what: 'folder' }) }, 'Open folder')));
    put(detail, h('div', { class: 'tl-card' }, kids));
  }
  if (location.hash === '#mp4') show();
})();
