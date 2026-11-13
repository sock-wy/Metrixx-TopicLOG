// App bar: pull status, refresh interval, refresh now, Adanos key, quit.
(function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (iso) => { if (!iso) return '–'; const d = new Date(iso); return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
  let lastSeen = null;
  async function poll() {
    try {
      const s = await (await fetch('/api/status', { cache: 'no-store' })).json();
      $('ab-dot').className = 'dot' + (s.running ? ' busy' : s.error ? ' err' : '');
      $('ab-text').textContent = s.running ? 'Pulling Kalshi, Adanos, prices and free sources…'
        : s.error ? `Last pull failed: ${s.error}` : `Last pull ${fmt(s.last_ok)} · next ${fmt(s.next_run)}`;
      $('ab-refresh').disabled = s.running;
      status = s;
      const on = (s.schedule || []).filter((x) => x.on).map((x) => x.t);
      $('ab-sched-sum').textContent = on.join(' · ') + ' CT' + (s.weekdays_only ? ' (weekdays)' : '');
      $('ab-key').textContent = s.has_key ? '' : 'No Adanos key';
      if (!$('ab-keyform').hidden || !$('ab-keyform').dataset.built) drawKeys(s);
      $('ab-key').className = s.has_key ? 'key-ok' : 'key-missing';
      if (s.last_ok && s.last_ok !== lastSeen && !s.running) { if (lastSeen !== null) window.TLDATA.load(); lastSeen = s.last_ok; }
    } catch (e) {
      $('ab-dot').className = 'dot err'; $('ab-text').textContent = 'The app has stopped. Open Topic Log again.';
    }
  }
  const post = (path, body) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  $('ab-refresh').addEventListener('click', async () => { await post('/api/refresh'); setTimeout(poll, 300); });
  // ---- schedule panel
  let status = null; let rows = [];
  const panel = $('ab-sched-panel');
  function drawRows() {
    const box = $('sched-rows'); box.replaceChildren();
    rows.sort((a, b) => a.t.localeCompare(b.t));
    rows.forEach((r, i) => {
      const lock = r.t === (status && status.pick_slot);
      const line = document.createElement('div'); line.className = 'sched-row';
      const t = document.createElement('input'); t.type = 'time'; t.value = r.t; t.disabled = lock; t.setAttribute('aria-label', 'Pull time ' + (i + 1));
      t.addEventListener('change', () => { r.t = t.value; drawRows(); });
      const on = document.createElement('input'); on.type = 'checkbox'; on.checked = r.on; on.disabled = lock; on.setAttribute('aria-label', 'On');
      on.addEventListener('change', () => { r.on = on.checked; });
      const lab = document.createElement('label'); lab.append(on, ' on');
      line.append(t, lab);
      if (lock) { const b = document.createElement('span'); b.className = 'badge'; b.textContent = 'pick of record'; line.append(b); }
      else { const x = document.createElement('button'); x.type = 'button'; x.textContent = 'Remove'; x.addEventListener('click', () => { rows.splice(i, 1); drawRows(); }); line.append(x); }
      box.append(line);
    });
    $('sched-add').disabled = rows.length >= ((status && status.max_slots) || 6);
  }
  $('ab-sched').addEventListener('click', () => {
    if (!panel.hidden) { panel.hidden = true; return; }
    rows = ((status && status.schedule) || []).map((x) => ({ ...x }));
    $('sched-wk').checked = !!(status && status.weekdays_only);
    $('sched-err').textContent = '';
    $('sched-next').textContent = status && status.next_run ? `Next pull now: ${fmt(status.next_run)} (your computer's time)` : '';
    drawRows(); panel.hidden = false;
  });
  $('sched-add').addEventListener('click', () => {
    const used = new Set(rows.map((r) => r.t)); let h = 18;
    while (used.has(String(h).padStart(2, '0') + ':15') && h < 23) h++;
    rows.push({ t: String(h).padStart(2, '0') + ':15', on: true }); drawRows();
  });
  $('sched-cancel').addEventListener('click', () => { panel.hidden = true; });
  $('sched-save').addEventListener('click', async () => {
    const r = await (await post('/api/schedule', { schedule: rows, weekdays_only: $('sched-wk').checked })).json();
    if (r.error) { $('sched-err').textContent = r.error; return; }
    panel.hidden = true; poll();
  });
  $('ab-folder').addEventListener('click', () => post('/api/open-folder', {}));
  $('ab-reload').addEventListener('click', () => { window.TLDATA.load(); const b = $('ab-reload'); b.textContent = 'Refreshed'; setTimeout(() => { b.textContent = 'Refresh view'; }, 1200); });
  // ---- data keys: one row per keyed source; a source without a key is grey and not pulled
  const SRC = [['adanos_key', 'Adanos', 'social attention (needed)'], ['bigdata_key', 'Bigdata.com', 'US stock & ETF prices'],
               ['benzinga_key', 'Benzinga', 'prices, movers, earnings'], ['helius_key', 'Helius', 'Solana on-chain (not used yet)']];
  function drawKeys(s) {
    const f = $('ab-keyform'); f.dataset.built = '1'; f.replaceChildren();
    const has = s.keys || {};
    for (const [k, name, what] of SRC) {
      const row = document.createElement('span'); row.className = 'keyrow' + (has[k] ? ' on' : ' off');
      row.title = has[k] ? `${name}: key saved, pulled with every pull` : `${name}: no key, not pulled`;
      const inp = document.createElement('input'); inp.type = 'password'; inp.size = 12; inp.dataset.k = k;
      inp.placeholder = has[k] ? '•••• saved' : 'API key'; inp.setAttribute('aria-label', name + ' API key');
      row.append(Object.assign(document.createElement('b'), { textContent: name }), inp);
      f.append(row);
    }
    const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save';
    save.addEventListener('click', async () => {
      const body = {}; f.querySelectorAll('input').forEach((i) => { if (i.value.trim()) body[i.dataset.k] = i.value.trim(); });
      if (!Object.keys(body).length) return;
      body.refresh = !!body.adanos_key; await post('/api/settings', body); f.hidden = true; poll();
    });
    f.append(save);
  }
  $('ab-keybtn').addEventListener('click', () => { const f = $('ab-keyform'); f.hidden = !f.hidden; if (!f.hidden) poll(); });
;
  $('ab-quit').addEventListener('click', async () => { await post('/api/quit'); document.body.innerHTML = '<p style="padding:40px;font-family:sans-serif">Topic Log has quit. You can close this window.</p>'; });
  poll(); setInterval(poll, 5000);
})();
