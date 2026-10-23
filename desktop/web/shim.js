// A small stand-in for the claude.ai Dashboard runtime (`dash`), so the same page runs locally.
// Data comes from the local server (/api/data/<id>); filters persist in localStorage.
(function () {
  const IDS = ['topic_log', 'score_history', 'daily_log', 'runs', 'adanos_daily', 'symbol_appendix', 'market_data',
    'us_stocks', 'earnings_calendar', 'us_movers', 'polymarket', 'crypto_spot', 'events'];
  const DEFAULTS = {
    w_attention_shift: 0.35, w_attention_x: 0.35, w_activity_shift: 0, w_money_flow: 0, w_money_stock: 0.05, w_market_move: 0, w_sentiment_shift: 0, w_momentum: 0.125, w_volume_abn: 0.125,
    attn_mode: 'level', act_mode: '3d', missing_mode: 'median', stock_mode: 'abn', _v: 4,
    src_kalshi: true, src_polymarket: true, src_reddit: true, src_x: true, src_news: true, src_momentum: true,
    uni_kalshi: true, uni_polymarket: true, uni_adanos: true, uni_movers: true, classes_off: [],
    g2_mode: 'prediction', g3_zero: 0.8, g3_spread: 0.3,
    quality_on: false, q_free: 0.05, q_slope: 0.5, q_floor: 0.6, q_zero_pen: 0.4, q_single: 0.9,
    tier_mode: 'labels', t1_days: 2, t1_pct: 0.7, t2_flow: 0.7, t2_attn: 0.5, t3_attn: 0.8,
  };
  const store = {}; const calcs = {}; const subs = [];
  let params = { ...DEFAULTS };
  try { Object.assign(params, JSON.parse(localStorage.getItem('tl.params') || '{}')); } catch (e) { /* first run */ }
  if (params._v !== 4) { params = { ...DEFAULTS }; }  // first start of v0.4: begin from the w2 defaults
  const save = () => { try { localStorage.setItem('tl.params', JSON.stringify(params)); } catch (e) { /* ignore */ } };

  function compute() {
    for (const [id, c] of Object.entries(calcs)) {
      const ins = c.inputs.map((i) => store[i]);
      if (ins.some((s) => !s || s.status === 'loading')) { store[id] = { status: 'loading', data: [] }; continue; }
      if (ins.some((s) => s.status !== 'ok')) { store[id] = { status: 'error', data: [] }; continue; }
      try { store[id] = { status: 'ok', data: c.fn(...ins.map((s) => s.data)) }; } catch (e) { console.error(id, e); store[id] = { status: 'error', data: [], message: String(e) }; }
    }
  }
  let pending = false;
  function notify() {
    if (pending) return; pending = true;
    requestAnimationFrame(() => {
      pending = false; compute();
      for (const f of subs) { try { f(); } catch (e) { console.error(e); } }
    });
  }
  window.dash = {
    data(id) {
      const s = store[id] || { status: 'loading', data: [] };
      const d = s.data || [];
      return { status: s.status, data: d, rows: d, columns: Array.isArray(d) && d[0] ? Object.keys(d[0]) : [], message: s.message, refreshing: !!s.refreshing, meta: [] };
    },
    onData(fn) { subs.push(fn); try { fn(); } catch (e) { console.error(e); } },
    calc(id, spec) { calcs[id] = spec; store[id] = { status: 'loading', data: [] }; },
    loader() {},
    params() { return { ...params }; },
    setParams(p) { Object.assign(params, p); save(); notify(); },
    resetParams() { params = { ...DEFAULTS }; save(); notify(); },
    setLink(name) { try { history.replaceState(null, '', '#' + name); } catch (e) { /* ignore */ } },
    colors: ['#3b6fd8', '#d0753a', '#2f9e7a', '#9a5bd1', '#c9a227', '#d0507a', '#4aa3c7', '#7c8a3a'],
    refresh() { load(); },
  };
  async function load() {
    for (const id of IDS) if (store[id] && store[id].status === 'ok') store[id].refreshing = true;
    await Promise.all(IDS.map(async (id) => {
      try {
        const r = await fetch('/api/data/' + id, { cache: 'no-store' });
        const d = await r.json();
        store[id] = { status: 'ok', data: Array.isArray(d) ? d : (d.rows || d.data || []) };
      } catch (e) { store[id] = { status: 'error', data: [], message: String(e) }; }
    }));
    notify();
  }
  window.TLDATA = { load };
  let w = 0;
  window.addEventListener('resize', () => { if (Math.abs(window.innerWidth - w) > 4) { w = window.innerWidth; notify(); } });
  load();
})();
