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
      if (document.activeElement !== $('ab-interval')) $('ab-interval').value = String(s.interval_min);
      $('ab-key').textContent = s.has_key ? 'Adanos key set' : 'No Adanos key';
      $('ab-key').className = s.has_key ? 'key-ok' : 'key-missing';
      if (s.last_ok && s.last_ok !== lastSeen && !s.running) { if (lastSeen !== null) window.TLDATA.load(); lastSeen = s.last_ok; }
    } catch (e) {
      $('ab-dot').className = 'dot err'; $('ab-text').textContent = 'The app has stopped. Open Topic Log again.';
    }
  }
  const post = (path, body) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  $('ab-refresh').addEventListener('click', async () => { await post('/api/refresh'); setTimeout(poll, 300); });
  $('ab-interval').addEventListener('change', async (e) => { await post('/api/settings', { interval_min: Number(e.target.value) }); poll(); });
  $('ab-reload').addEventListener('click', () => { window.TLDATA.load(); const b = $('ab-reload'); b.textContent = 'Refreshed'; setTimeout(() => { b.textContent = 'Refresh view'; }, 1200); });
  $('ab-keybtn').addEventListener('click', () => { const f = $('ab-keyform'); f.hidden = !f.hidden; if (!f.hidden) $('ab-keyinput').focus(); });
  $('ab-keysave').addEventListener('click', async () => {
    const v = $('ab-keyinput').value.trim(); if (!v) return;
    await post('/api/settings', { adanos_key: v, refresh: true }); $('ab-keyinput').value = ''; $('ab-keyform').hidden = true; poll();
  });
  $('ab-quit').addEventListener('click', async () => { await post('/api/quit'); document.body.innerHTML = '<p style="padding:40px;font-family:sans-serif">Topic Log has quit. You can close this window.</p>'; });
  poll(); setInterval(poll, 5000);
})();
