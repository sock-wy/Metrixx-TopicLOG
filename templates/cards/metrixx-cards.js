/*
 * Metrixx option & prediction-market card library
 * ------------------------------------------------
 * One function per strategy. Each card is a plain config object:
 *
 *   { id, strategy, underlying, spot, params, title?, subtitle? }
 *
 * buildCard(config)         -> Plotly figure JSON { data, layout, meta }
 * buildComparison(configs)  -> Plotly figure JSON overlaying several strategies
 *
 * The output is plain JSON, so the same figure can be rendered live in a
 * browser with Plotly.js or exported to PNG with Kaleido (see visuals/).
 *
 * Works as a <script> tag (window.MetrixxCards) and as a Node module.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MetrixxCards = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ------------------------------------------------------------------
  // Theme: the only place colours, fonts and sizes are defined.
  // Align this block with the existing P/L panel style.
  // ------------------------------------------------------------------
  const THEME = {
    width: 1280,
    height: 720,
    font: 'Inter, "Helvetica Neue", Arial, sans-serif',
    mono: '"IBM Plex Mono", Menlo, Consolas, monospace',
    background: '#0F1620',
    grid: 'rgba(230, 236, 242, 0.08)',
    zero: 'rgba(230, 236, 242, 0.35)',
    text: '#E6ECF2',
    muted: '#8FA0B3',
    line: '#E6ECF2',
    profit: '#3FB68B',
    loss: '#E5604D',
    spot: '#F2C94C',
    strike: '#7C8CF8',
    series: ['#E6ECF2', '#58A6FF', '#F2C94C', '#C792EA'],
  };

  // ------------------------------------------------------------------
  // Payoff engine (value at expiry, in dollars)
  // Leg: { kind: call|put|stock|binary, side: long|short, qty, multiplier,
  //        strike, premium | entry | price, direction (binary: above|below) }
  // ------------------------------------------------------------------
  const DEFAULT_MULTIPLIER = { call: 100, put: 100, stock: 1, binary: 1 };
  const EPS = 1e-6;

  function legPnl(leg, S) {
    const sign = leg.side === 'short' ? -1 : 1;
    const qty = leg.qty == null ? 1 : leg.qty;
    const m = leg.multiplier == null ? DEFAULT_MULTIPLIER[leg.kind] : leg.multiplier;
    const k = sign * qty * m;
    switch (leg.kind) {
      case 'call': return k * (Math.max(S - leg.strike, 0) - leg.premium);
      case 'put': return k * (Math.max(leg.strike - S, 0) - leg.premium);
      case 'stock': return k * (S - leg.entry);
      case 'binary': {
        const win = leg.direction === 'below' ? S < leg.strike : S >= leg.strike;
        return k * ((win ? 1 : 0) - leg.price);
      }
      default: throw new Error('Unknown leg kind: ' + leg.kind);
    }
  }

  function pnl(legs, S) {
    let total = 0;
    for (const leg of legs) total += legPnl(leg, S);
    return total;
  }

  function netCost(legs) {
    // Positive = debit paid, negative = credit received
    let c = 0;
    for (const leg of legs) {
      const sign = leg.side === 'short' ? -1 : 1;
      const qty = leg.qty == null ? 1 : leg.qty;
      const m = leg.multiplier == null ? DEFAULT_MULTIPLIER[leg.kind] : leg.multiplier;
      const unit = leg.kind === 'stock' ? leg.entry : leg.kind === 'binary' ? leg.price : leg.premium;
      c += sign * qty * m * unit;
    }
    return c;
  }

  // Kink points: payoff is piecewise linear between these, so extremes and
  // breakevens can be found exactly rather than by sampling.
  function kinks(legs) {
    const pts = new Set([0]);
    for (const leg of legs) {
      if (leg.strike != null) {
        pts.add(leg.strike);
        if (leg.kind === 'binary') pts.add(leg.strike - EPS);
      }
    }
    return Array.from(pts).filter((x) => x >= 0).sort((a, b) => a - b);
  }

  function analyse(legs) {
    const ks = kinks(legs);
    const far = Math.max(...ks, 1) * 10 + 1;
    const pts = ks.concat([far]);
    const vals = pts.map((x) => pnl(legs, x));
    const tailSlope = pnl(legs, far + 1) - pnl(legs, far);

    const maxP = Math.max(...vals);
    const minP = Math.min(...vals);
    const maxProfit = tailSlope > EPS ? Infinity : maxP;
    const maxLoss = tailSlope < -EPS ? -Infinity : minP;

    const breakevens = [];
    for (let i = 0; i < pts.length - 1; i++) {
      const a = vals[i], b = vals[i + 1];
      if (a === 0) breakevens.push(pts[i]);
      else if ((a < 0 && b > 0) || (a > 0 && b < 0)) {
        breakevens.push(pts[i] + (pts[i + 1] - pts[i]) * (-a / (b - a)));
      }
    }
    // Merge near-duplicates (binary jumps produce two points EPS apart)
    const be = [];
    for (const x of breakevens) if (!be.some((y) => Math.abs(y - x) < 1e-3)) be.push(x);

    return { maxProfit, maxLoss, breakevens: be, netCost: netCost(legs) };
  }

  // ------------------------------------------------------------------
  // Strategy registry: params -> legs. Add a strategy by adding one entry.
  // ------------------------------------------------------------------
  const STRATEGIES = {
    long_call: {
      label: 'Long call',
      legs: (p) => [{ kind: 'call', side: 'long', strike: p.strike, premium: p.premium, qty: p.qty }],
      describe: (p) => `${p.strike} call @ ${p.premium}`,
    },
    long_put: {
      label: 'Long put',
      legs: (p) => [{ kind: 'put', side: 'long', strike: p.strike, premium: p.premium, qty: p.qty }],
      describe: (p) => `${p.strike} put @ ${p.premium}`,
    },
    long_straddle: {
      label: 'Long straddle',
      legs: (p) => [
        { kind: 'call', side: 'long', strike: p.strike, premium: p.call_premium, qty: p.qty },
        { kind: 'put', side: 'long', strike: p.strike, premium: p.put_premium, qty: p.qty },
      ],
      describe: (p) => `${p.strike} call @ ${p.call_premium} + ${p.strike} put @ ${p.put_premium}`,
    },
    long_strangle: {
      label: 'Long strangle',
      legs: (p) => [
        { kind: 'put', side: 'long', strike: p.put_strike, premium: p.put_premium, qty: p.qty },
        { kind: 'call', side: 'long', strike: p.call_strike, premium: p.call_premium, qty: p.qty },
      ],
      describe: (p) => `${p.put_strike} put @ ${p.put_premium} + ${p.call_strike} call @ ${p.call_premium}`,
    },
    bull_call_spread: {
      label: 'Bull call spread',
      legs: (p) => [
        { kind: 'call', side: 'long', strike: p.long_strike, premium: p.long_premium, qty: p.qty },
        { kind: 'call', side: 'short', strike: p.short_strike, premium: p.short_premium, qty: p.qty },
      ],
      describe: (p) => `+${p.long_strike}C @ ${p.long_premium} / −${p.short_strike}C @ ${p.short_premium}`,
    },
    bear_put_spread: {
      label: 'Bear put spread',
      legs: (p) => [
        { kind: 'put', side: 'long', strike: p.long_strike, premium: p.long_premium, qty: p.qty },
        { kind: 'put', side: 'short', strike: p.short_strike, premium: p.short_premium, qty: p.qty },
      ],
      describe: (p) => `+${p.long_strike}P @ ${p.long_premium} / −${p.short_strike}P @ ${p.short_premium}`,
    },
    iron_condor: {
      label: 'Iron condor (short)',
      legs: (p) => [
        { kind: 'put', side: 'long', strike: p.put_long, premium: p.put_long_premium, qty: p.qty },
        { kind: 'put', side: 'short', strike: p.put_short, premium: p.put_short_premium, qty: p.qty },
        { kind: 'call', side: 'short', strike: p.call_short, premium: p.call_short_premium, qty: p.qty },
        { kind: 'call', side: 'long', strike: p.call_long, premium: p.call_long_premium, qty: p.qty },
      ],
      describe: (p) => `${p.put_long}/${p.put_short}P · ${p.call_short}/${p.call_long}C`,
    },
    covered_call: {
      label: 'Covered call',
      legs: (p) => [
        { kind: 'stock', side: 'long', entry: p.entry, qty: p.shares == null ? 100 : p.shares },
        { kind: 'call', side: 'short', strike: p.strike, premium: p.premium, qty: (p.shares == null ? 100 : p.shares) / 100 },
      ],
      describe: (p) => `${p.shares == null ? 100 : p.shares} sh @ ${p.entry} − ${p.strike}C @ ${p.premium}`,
    },
    // Prediction-market YES contract (Polymarket / Kalshi): pays $1 per
    // contract if the condition holds at expiry. `stake` dollars buys
    // stake / price contracts. For an up/down market, strike = reference price.
    binary_step: {
      label: 'Prediction market (binary)',
      legs: (p) => [{
        kind: 'binary', side: 'long', strike: p.strike, price: p.price,
        direction: p.direction || 'above', qty: p.stake / p.price,
      }],
      describe: (p) => `YES ${p.direction === 'below' ? '<' : '≥'} ${p.strike} @ ${p.price} · $${p.stake} stake`,
    },
  };
  STRATEGIES.polymarket_step = STRATEGIES.binary_step;

  function resolve(config) {
    const s = STRATEGIES[config.strategy];
    if (!s) throw new Error('Unknown strategy: ' + config.strategy + '. Known: ' + Object.keys(STRATEGIES).join(', '));
    const legs = s.legs(config.params);
    return { strategy: s, legs, stats: analyse(legs) };
  }

  // ------------------------------------------------------------------
  // Formatting
  // ------------------------------------------------------------------
  function money(v) {
    if (v === Infinity) return 'Unlimited';
    if (v === -Infinity) return 'Unlimited';
    const s = Math.abs(v) >= 1000
      ? Math.round(Math.abs(v)).toLocaleString('en-US')
      : Math.abs(v).toFixed(Math.abs(v) < 10 ? 2 : 0);
    return (v < 0 ? '−$' : '$') + s;
  }
  function price(v) { return Number(v.toFixed(2)).toString(); }
  // Plotly renders any text containing two '$' as LaTeX; use the HTML entity instead.
  function esc(t) { return String(t).replace(/\$/g, '&#36;'); }

  // ------------------------------------------------------------------
  // Chart helpers
  // ------------------------------------------------------------------
  function xRange(config, legsList) {
    if (config.range) return config.range;
    const strikes = [];
    for (const legs of legsList) for (const l of legs) if (l.strike != null) strikes.push(l.strike);
    const spot = config.spot;
    const lo = Math.min(spot * 0.88, ...strikes.map((k) => k - spot * 0.04));
    const hi = Math.max(spot * 1.12, ...strikes.map((k) => k + spot * 0.04));
    return [Math.max(0, lo), hi];
  }

  function grid(range, legs, n) {
    const [lo, hi] = range;
    const xs = new Set();
    for (let i = 0; i <= n; i++) xs.add(lo + ((hi - lo) * i) / n);
    for (const l of legs) {
      if (l.strike != null && l.strike > lo && l.strike < hi) {
        xs.add(l.strike);
        if (l.kind === 'binary') xs.add(l.strike - EPS);
      }
    }
    return Array.from(xs).sort((a, b) => a - b);
  }

  function baseLayout(title, subtitle, xTitle) {
    const T = THEME;
    return {
      width: T.width,
      height: T.height,
      paper_bgcolor: T.background,
      plot_bgcolor: T.background,
      font: { family: T.font, color: T.text, size: 16 },
      margin: { l: 96, r: 330, t: 120, b: 80 },
      showlegend: false,
      xaxis: {
        title: { text: xTitle, font: { color: T.muted, size: 15 } },
        gridcolor: T.grid, zeroline: false, tickfont: { color: T.muted, family: T.mono, size: 14 },
        linecolor: T.grid,
      },
      yaxis: {
        title: { text: 'P/L at expiry ($)', font: { color: T.muted, size: 15 } },
        gridcolor: T.grid, zeroline: true, zerolinecolor: T.zero, zerolinewidth: 1.5,
        tickformat: '$,.0f', tickfont: { color: T.muted, family: T.mono, size: 14 },
      },
      shapes: [],
      annotations: [
        { text: `<b>${esc(title)}</b>`, xref: 'paper', yref: 'paper', x: 0, y: 1.16, xanchor: 'left', yanchor: 'bottom',
          showarrow: false, font: { size: 30, color: T.text } },
        { text: esc(subtitle), xref: 'paper', yref: 'paper', x: 0, y: 1.10, xanchor: 'left', yanchor: 'bottom',
          showarrow: false, font: { size: 16, color: T.muted, family: T.mono } },
      ],
    };
  }

  function vline(x, color, dash, label) {
    return {
      shape: { type: 'line', xref: 'x', yref: 'paper', x0: x, x1: x, y0: 0, y1: 1,
        line: { color, width: 1.5, dash } },
      annotation: label ? { text: label, x, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom', showarrow: false,
        font: { size: 13, color, family: THEME.mono } } : null,
    };
  }

  function statsPanel(rows, y0) {
    // Right-hand panel: label / value pairs
    const T = THEME;
    const out = [];
    let y = y0 == null ? 1 : y0;
    for (const [label, value, color] of rows) {
      out.push({ text: esc(label.toUpperCase()), xref: 'paper', yref: 'paper', x: 1.04, y, xanchor: 'left', yanchor: 'top',
        showarrow: false, font: { size: 12, color: T.muted, family: T.mono } });
      out.push({ text: `<b>${esc(value)}</b>`, xref: 'paper', yref: 'paper', x: 1.04, y: y - 0.045, xanchor: 'left', yanchor: 'top',
        showarrow: false, font: { size: 22, color: color || T.text } });
      y -= 0.15;
    }
    return out;
  }

  // ------------------------------------------------------------------
  // Single-strategy card
  // ------------------------------------------------------------------
  function buildCard(config) {
    const T = THEME;
    const { strategy, legs, stats } = resolve(config);
    const range = xRange(config, [legs]);
    const xs = grid(range, legs, 400);
    const ys = xs.map((x) => pnl(legs, x));

    const title = config.title || `${config.underlying} · ${strategy.label}`;
    const subtitle = config.subtitle || `${strategy.describe(config.params)}   ·   spot ${price(config.spot)}`;
    const layout = baseLayout(title, subtitle, `${config.underlying} at expiry`);

    const data = [
      { type: 'scatter', mode: 'lines', x: xs, y: ys.map((y) => Math.max(y, 0)), fill: 'tozeroy',
        fillcolor: 'rgba(63, 182, 139, 0.18)', line: { width: 0 }, hoverinfo: 'skip', name: 'profit' },
      { type: 'scatter', mode: 'lines', x: xs, y: ys.map((y) => Math.min(y, 0)), fill: 'tozeroy',
        fillcolor: 'rgba(229, 96, 77, 0.18)', line: { width: 0 }, hoverinfo: 'skip', name: 'loss' },
      { type: 'scatter', mode: 'lines', x: xs, y: ys, name: strategy.label,
        line: { color: T.line, width: 3.5, shape: 'linear' },
        hovertemplate: '%{x:.2f}<br>P/L %{y:$,.0f}<extra></extra>' },
    ];

    // Strike and spot markers
    const strikes = Array.from(new Set(legs.filter((l) => l.strike != null).map((l) => l.strike)));
    for (const k of strikes) {
      const v = vline(k, T.strike, 'dot', `K ${price(k)}`);
      layout.shapes.push(v.shape); layout.annotations.push(v.annotation);
    }
    const sv = vline(config.spot, T.spot, 'dash', `spot ${price(config.spot)}`);
    layout.shapes.push(sv.shape);
    sv.annotation.y = 1.04;
    layout.annotations.push(sv.annotation);

    // Breakeven points
    const be = stats.breakevens.filter((x) => x >= range[0] && x <= range[1]);
    if (be.length) {
      data.push({ type: 'scatter', mode: 'markers', x: be, y: be.map(() => 0), name: 'breakeven',
        marker: { size: 12, color: T.background, line: { color: T.text, width: 2.5 } },
        hovertemplate: 'Breakeven %{x:.2f}<extra></extra>' });
    }

    const cost = stats.netCost;
    layout.annotations.push(...statsPanel([
      ['Max profit', money(stats.maxProfit), T.profit],
      ['Max loss', money(stats.maxLoss), T.loss],
      ['Breakeven', be.length ? be.map(price).join(' / ') : '—'],
      [cost >= 0 ? 'Net debit' : 'Net credit', money(Math.abs(cost))],
    ]));

    return {
      data,
      layout,
      meta: {
        id: config.id, strategy: config.strategy, underlying: config.underlying,
        maxProfit: stats.maxProfit, maxLoss: stats.maxLoss, breakevens: stats.breakevens, netCost: cost,
      },
    };
  }

  // ------------------------------------------------------------------
  // Comparison / scenario chart: several strategies on one axis
  // (e.g. the updown_vs_option angle: binary bet vs option of similar cost)
  // ------------------------------------------------------------------
  function buildComparison(spec) {
    const T = THEME;
    const members = spec.members.map((c) => Object.assign({ underlying: spec.underlying, spot: spec.spot }, c));
    const resolved = members.map(resolve);
    const range = xRange(spec, resolved.map((r) => r.legs));
    const allLegs = [].concat(...resolved.map((r) => r.legs));

    const title = spec.title || `${spec.underlying} · scenario comparison`;
    const subtitle = spec.subtitle || `spot ${price(spec.spot)}`;
    const layout = baseLayout(title, subtitle, `${spec.underlying} at expiry`);
    layout.showlegend = true;
    layout.legend = { x: 0, y: 1.02, xanchor: 'left', yanchor: 'bottom', orientation: 'h',
      font: { size: 15, color: T.text }, bgcolor: 'rgba(0,0,0,0)' };
    layout.margin.t = 150;
    layout.annotations[0].y = 1.20;
    layout.annotations[1].y = 1.14;

    const data = resolved.map((r, i) => {
      const xs = grid(range, allLegs, 400);
      return {
        type: 'scatter', mode: 'lines', x: xs, y: xs.map((x) => pnl(r.legs, x)),
        name: esc(members[i].label || r.strategy.label),
        line: { color: T.series[i % T.series.length], width: 3.5 },
        hovertemplate: '%{x:.2f}<br>P/L %{y:$,.0f}<extra>' + (members[i].label || r.strategy.label) + '</extra>',
      };
    });

    const sv = vline(spec.spot, T.spot, 'dash', `spot ${price(spec.spot)}`);
    layout.shapes.push(sv.shape);
    layout.annotations.push(sv.annotation);

    // Stats per member
    const rows = [];
    resolved.forEach((r, i) => {
      const name = members[i].label || r.strategy.label;
      rows.push([name + ' · max profit / loss', `${money(r.stats.maxProfit)} / ${money(r.stats.maxLoss)}`, T.series[i % T.series.length]]);
      rows.push(['Breakeven', r.stats.breakevens.map(price).join(' / ') || '—']);
    });
    layout.annotations.push(...statsPanel(rows));

    return {
      data,
      layout,
      meta: {
        id: spec.id, type: 'comparison', underlying: spec.underlying,
        members: resolved.map((r, i) => ({
          label: members[i].label || r.strategy.label, strategy: members[i].strategy,
          maxProfit: r.stats.maxProfit, maxLoss: r.stats.maxLoss,
          breakevens: r.stats.breakevens, netCost: r.stats.netCost,
        })),
      },
    };
  }

  // Build every card and comparison in a deck config: { cards: [], comparisons: [] }
  function buildDeck(deck) {
    const out = {};
    for (const c of deck.cards || []) out[c.id] = buildCard(c);
    for (const c of deck.comparisons || []) out[c.id] = buildComparison(c);
    return out;
  }

  return {
    THEME, STRATEGIES,
    legPnl, pnl, netCost, analyse,
    buildCard, buildComparison, buildDeck,
  };
});
