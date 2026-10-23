"""Build backtest/v3/results.html from results.json (+ daily IC series recomputed from the panel)."""
from __future__ import annotations

import html
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
V3 = ROOT / "backtest" / "v3"
sys.path.insert(0, str(V3))
import evaluate as ev  # noqa: E402

R = json.loads((V3 / "results.json").read_text())
esc = html.escape


def fmt(v, d=3, sign=True):
    return "–" if v is None or v != v else (f"{v:+.{d}f}" if sign else f"{v:.{d}f}")


# ------------------------------------------------------------------ daily series for the time chart
def daily_series():
    df = pd.read_parquet(V3 / "panel.parquet")
    df["day"] = pd.to_datetime(df.day)
    E = df[df.day >= ev.ADANOS_START].copy()
    both = E.dropna(subset=["label_attn", "label_move"]).copy()
    both["label_comb"] = 0.7 * ev.daypct(both, "label_attn") + 0.3 * ev.daypct(both, "label_move")
    E = E.merge(both[["day", "entity", "label_comb"]], on=["day", "entity"], how="left")
    P = E[(E.k_vol > 0) | E.p_move.notna()].copy()
    flat = lambda w: sum(w[c] * ev.daypct(P, c).fillna(0.5) for c in w) / sum(w.values())  # noqa: E731
    P["w2"] = flat({"lvl20_all": .35, "lvl20_x": .35, "vol_abn": .125, "mom": .125, "k_oi_abn": .05})
    P["w1"] = flat({"lvl20_all": .30, "act3_all": .10, "k_flow": .15, "k_oi_chg": .10, "k_move": .10, "mom": .25})
    num = sum(w * ev.daypct(P, c).fillna(0) for c, w in {"buzzd1_reddit": .25, "act1_reddit": .10, "k_flow": .20, "k_oi_chg": .10, "k_move": .20, "sentd1_reddit": .15}.items())
    den = sum(w * P[c].notna() for c, w in {"buzzd1_reddit": .25, "act1_reddit": .10, "k_flow": .20, "k_oi_chg": .10, "k_move": .20, "sentd1_reddit": .15}.items())
    P["w0"] = num / den.replace(0, np.nan)
    out = {}
    for c in ("w2", "w1", "w0", "mom"):
        r = ev.day_ic(P, c, "label_comb", 10)
        out[c] = [(str(d.date()), float(i), float(t)) for d, i, t in zip(r.day, r.ic, r.top5)]
    flatres = {c: {"hold_ic": ev.boot(pd.Series([x[1] for x in v if x[0] >= "2026-10-01"])), "hold_top5": ev.boot(pd.Series([x[2] for x in v if x[0] >= "2026-10-01"])),
                   "all_ic": ev.boot(pd.Series([x[1] for x in v])), "all_top5": ev.boot(pd.Series([x[2] for x in v]))} for c, v in out.items()}
    return out, flatres


SER, FLAT = daily_series()
COL = {"w2": "var(--acc)", "w1": "var(--s2)", "w0": "var(--old)", "mom": "var(--mom)"}
NAME = {"w2": "w2 (new default)", "w1": "w1 (current)", "w0": "w0 (playbook)", "mom": "momentum only"}


def time_chart():
    W, H, ml, mr, mt, mb = 720, 260, 44, 16, 14, 28
    days = sorted({d for v in SER.values() for d, _, _ in v})
    x = lambda d: ml + days.index(d) / max(1, len(days) - 1) * (W - ml - mr)  # noqa: E731
    lo, hi = -0.2, 0.7
    y = lambda v: mt + (hi - v) / (hi - lo) * (H - mt - mb)  # noqa: E731
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Daily rank IC by version">']
    for t in (-0.2, 0, 0.2, 0.4, 0.6):
        o.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="{"ref" if t == 0 else "grid"}"/><text x="{ml - 6}" y="{y(t) + 4:.1f}" text-anchor="end" class="tick">{t:g}</text>')
    if "2026-10-01" in days:
        xs = x("2026-10-01")
        o.append(f'<rect x="{xs:.1f}" y="{mt}" width="{W - mr - xs:.1f}" height="{H - mt - mb}" class="hold"/><text x="{xs + 6:.1f}" y="{mt + 12}" class="tick">holdout</text>')
    for i, d in enumerate(days):
        if i % 7 == 0:
            o.append(f'<text x="{x(d):.1f}" y="{H - 8}" text-anchor="middle" class="tick">{d[5:]}</text>')
    for c in ("w0", "mom", "w1", "w2"):
        pts = " ".join(f"{x(d):.1f},{y(max(lo, min(hi, v))):.1f}" for d, v, _ in SER[c])
        o.append(f'<polyline points="{pts}" fill="none" stroke="{COL[c]}" stroke-width="{2.4 if c == "w2" else 1.4}" opacity="{1 if c in ("w2", "w1") else .8}"/>')
    o.append("</svg>")
    return "\n".join(o)


def dots(rows, lo, hi, ref, label_fmt=lambda v: f"{v:+.2f}"):
    """rows: [(name, cls, (m, a, b))]"""
    W, rh, ml, mr, mt = 720, 24, 310, 24, 22
    H = mt + rh * len(rows) + 26
    x = lambda v: ml + (min(hi, max(lo, v)) - lo) / (hi - lo) * (W - ml - mr)  # noqa: E731
    o = [f'<svg viewBox="0 0 {W} {H}" role="img">']
    step = 0.1 if hi - lo <= 0.8 else 0.2
    t = lo
    while t <= hi + 1e-9:
        o.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{mt - 6}" y2="{H - 24}" class="{"ref" if abs(t - ref) < 1e-9 else "grid"}"/><text x="{x(t):.1f}" y="{H - 8}" text-anchor="middle" class="tick">{t:.1f}</text>')
        t = round(t + step, 6)
    for i, (n, cls, (m, a, b)) in enumerate(rows):
        yy = mt + rh * i + rh / 2
        o.append(f'<text x="{ml - 10}" y="{yy + 4:.1f}" text-anchor="end" class="lab {cls}">{esc(n)}</text>')
        if m == m:
            o.append(f'<line x1="{x(a):.1f}" x2="{x(b):.1f}" y1="{yy:.1f}" y2="{yy:.1f}" class="ci {cls}"/><circle cx="{x(m):.1f}" cy="{yy:.1f}" r="5" class="pt {cls}"><title>{esc(n)}: {m:.3f} (95% CI {a:.3f} to {b:.3f})</title></circle>')
    o.append("</svg>")
    return "\n".join(o)


def feat_table(d, key, lab, names, top=None):
    rows = R[d][key][lab]
    items = sorted(rows.items(), key=lambda kv: -kv[1]["all"]["ic"][0])[: top or None]
    tr = []
    champ = set(R["meta"]["selected"][d])
    for f, v in items:
        sig = v["p_holm"] < 0.05 and v["all"]["ic"][0] > 0
        cls = "acc" if f in champ else ""
        tr.append(f'<tr class="{cls}"><td class="l">{esc(names.get(f, f))}{" ★" if f in champ else ""}</td><td>{fmt(v["discovery"]["ic"][0])}</td>'
                  f'<td>{fmt(v["holdout"]["ic"][0])}</td><td title="95% CI {v["all"]["ic"][1]:+.3f} to {v["all"]["ic"][2]:+.3f}">{fmt(v["all"]["ic"][0])}</td>'
                  f'<td>{fmt(v["all"]["top5"][0], 2, False)}</td><td>{"yes" if sig else "no"}</td><td>{v["all"]["n"]:.0f}</td></tr>')
    return ('<div class="tbl"><table><thead><tr><th>Input</th><th>IC discovery</th><th>IC holdout</th><th>IC all days</th><th>Top-5 pct</th>'
            '<th>Significant (Holm)</th><th>Topics / day</th></tr></thead><tbody>' + "".join(tr) + "</tbody></table></div>")


O = R["overall"]["prediction"]
OA = R["overall"]["all"]
M = R["meta"]
cd = R["D"]["cooldown_top1"]
F = FLAT
d_w1 = O["overall_minus_w1"]["holdout"]
d_mom = O["overall_minus_mom"]["holdout"]

overall_rows = [(NAME[c], {"w2": "acc", "mom": "mom"}.get(c, "oth"), tuple(F[c]["hold_ic"])) for c in ("w2", "w1", "w0", "mom")]
overall_top5 = [(NAME[c], {"w2": "acc", "mom": "mom"}.get(c, "oth"), tuple(F[c]["hold_top5"])) for c in ("w2", "w1", "w0", "mom")]
A_rows = [(ev.A_FEATS.get(f, f), "acc" if f in M["selected"]["A"] else "oth", tuple(v["all"]["ic"]))
          for f, v in sorted(R["A"]["single"]["label_comb"].items(), key=lambda kv: -kv[1]["all"]["ic"][0])][:12]
B_rows = [(ev.B_FEATS.get(f, f), "acc" if f in M["selected"]["B"] else "oth", tuple(v["all"]["ic"]))
          for f, v in sorted(R["B"]["single_long"]["label_move"].items(), key=lambda kv: -kv[1]["all"]["ic"][0])]
C_rows = [(ev.C_FEATS.get(f, f), "acc" if f in M["selected"]["C"] else "oth", tuple(v["all"]["ic"]))
          for f, v in sorted(R["C"]["single_long"]["label_move"].items(), key=lambda kv: -kv[1]["all"]["ic"][0]) if not f.startswith("pp_") and f != "p_move"]

page = f"""<title>Topic Log Backtest v3</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column; verdict first, then the overall race, then each direction, then rules and limits. */
:root {{
  --bg: #f6f7f5; --panel: #ffffff; --ink: #1b2125; --muted: #5d686e; --line: #dde1dc;
  --acc: #1f6f8b; --mom: #b5651d; --old: #8a9399; --s2: #6b8f3a; --hold: rgba(31,111,139,.06);
  --serif: "Newsreader", Georgia, serif; --sans: "IBM Plex Sans", -apple-system, "Segoe UI", sans-serif; --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #131618; --panel: #1a1e21; --ink: #e6e8e5; --muted: #98a1a5; --line: #2b3135;
  --acc: #5fb3d1; --mom: #e0a060; --old: #7c868c; --s2: #a3c46a; --hold: rgba(95,179,209,.08); color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #131618; --panel: #1a1e21; --ink: #e6e8e5; --muted: #98a1a5; --line: #2b3135;
  --acc: #5fb3d1; --mom: #e0a060; --old: #7c868c; --s2: #a3c46a; --hold: rgba(95,179,209,.08); color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.55;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 32px 64px; }}
main {{ max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 30px; }}
h1 {{ font-family: var(--serif); font-weight: 400; font-size: 2.1rem; line-height: 1.15; margin: 0; text-wrap: balance; }}
h2 {{ font-family: var(--serif); font-weight: 600; font-size: 1.35rem; margin: 0; text-wrap: balance; }}
h3 {{ font: 600 13px/1.3 var(--sans); margin: 0; }}
p {{ margin: 0; max-width: 70ch; }}
.eyebrow {{ font: 500 12px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }}
section {{ display: flex; flex-direction: column; gap: 12px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; display: flex; flex-direction: column; gap: 10px; }}
.card ul {{ margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 6px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr)); gap: 10px; }}
.kpi {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 2px; }}
.kpi b {{ font: 500 1.6rem/1.1 var(--serif); }} .kpi span {{ font-size: 12px; color: var(--muted); }}
.chart {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 14px 6px; overflow-x: auto; }}
.chart .sub {{ font-size: 12px; color: var(--muted); margin: 2px 0 6px; }}
.stack {{ display: flex; flex-direction: column; gap: 14px; }}
.pair {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 14px; }}
svg {{ width: 100%; height: auto; display: block; min-width: 440px; }}
svg text {{ fill: var(--muted); font: 11px var(--sans); }} svg .lab {{ fill: var(--ink); font-size: 12px; }}
svg .lab.acc {{ fill: var(--acc); font-weight: 600; }} svg .lab.mom {{ fill: var(--mom); font-weight: 600; }}
svg .grid {{ stroke: var(--line); }} svg .ref {{ stroke: var(--muted); stroke-dasharray: 3 3; }} svg .hold {{ fill: var(--hold); }}
svg .ci {{ stroke-width: 2; stroke: var(--old); opacity: .6; }} svg .pt {{ fill: var(--old); stroke: var(--panel); stroke-width: 1.5; }}
svg .ci.acc {{ stroke: var(--acc); opacity: 1; }} svg .pt.acc {{ fill: var(--acc); }} svg .ci.mom {{ stroke: var(--mom); opacity: 1; }} svg .pt.mom {{ fill: var(--mom); }}
.legend {{ display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }}
.legend i {{ display: inline-block; width: 14px; height: 3px; margin-right: 6px; vertical-align: 3px; border-radius: 2px; }}
.tbl {{ overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }}
table {{ border-collapse: collapse; width: 100%; font: 12.5px/1.35 var(--mono); font-variant-numeric: tabular-nums; }}
th, td {{ padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
th {{ font: 500 11px/1.3 var(--sans); color: var(--muted); }}
th:first-child, td.l {{ text-align: left; font-family: var(--sans); white-space: normal; min-width: 14rem; }}
tr.acc td {{ color: var(--acc); }}
.kv {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; font-size: 14px; }} .kv dt {{ color: var(--muted); }} .kv dd {{ margin: 0; }}
code {{ font-family: var(--mono); font-size: .92em; }}
</style>
<main>
<header style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">Study v3 · four directions · {M['A']['days']} days of social data, {M['B']['days']} days of prices, {M['C']['days']} days of Kalshi</span>
  <h1>w2: what the Topic Log should rank by</h1>
  <p>Every trading day at 15:00 ET the backtest rebuilds what the dashboard could see, ranks the topics, and checks the next day: how much the topic is talked about (70% of the target) and how much its price moves (30%). Each direction (social, price, prediction markets, rules) gets its own champion; the champions are then combined.</p>
</header>

<div class="kpis">
  <div class="kpi"><span>Holdout rank IC, w2</span><b>{fmt(F['w2']['hold_ic'][0], 2)}</b><span>w1 {fmt(F['w1']['hold_ic'][0], 2)} · w0 {fmt(F['w0']['hold_ic'][0], 2)} · momentum {fmt(F['mom']['hold_ic'][0], 2)}</span></div>
  <div class="kpi"><span>Top 5 land at, w2</span><b>{F['w2']['hold_top5'][0] * 100:.0f}%</b><span>of the pool on the next day's outcome (random 50%)</span></div>
  <div class="kpi"><span>w2 minus w1, holdout IC</span><b>{fmt(d_w1[0], 2)}</b><span>95% CI {fmt(d_w1[1], 2)} to {fmt(d_w1[2], 2)}</span></div>
  <div class="kpi"><span>Topics per day in the pool</span><b>{O['overall']['label_comb']['all']['n']:.0f}</b><span>with a prediction market (G2), out of ~{M['A']['per_day']:.0f} with social data</span></div>
</div>

<section class="card">
  <h2>Result</h2>
  <ul>
    <li><b>Social (A) is the strongest direction.</b> How far a topic's mentions sit above its own 20-day normal predicts the next day best. X on its own adds to the all-platform figure. 1-day changes are weak, and sentiment changes point the wrong way (on X, big sentiment swings come before <i>less</i> attention).</li>
    <li><b>Price (B): trading volume beats the price move.</b> Over {M['B']['days']} trading days and ~{M['B']['per_day']:.0f} stocks a day, volume traded so far vs normal is the best single price input (IC {fmt(R['B']['single_long']['label_move']['vol_abn']['all']['ic'][0], 3)} with the next move; |24h move| {fmt(R['B']['single_long']['label_move']['mom']['all']['ic'][0], 3)}). The champion uses both.</li>
    <li><b>Prediction markets (C) are weak.</b> Open interest and volume vs their own normal beat the 24h changes used so far, but none holds up on the holdout. They stay in w2 with weight 0.05 and keep their role as the G2 gate.</li>
    <li><b>Rules (D):</b> median vs dropping missing inputs makes no difference; a cooldown costs a little accuracy but spreads picks over more topics; capping the top 5 at two per asset class costs a lot.</li>
    <li><b>w2 = attention 0.35 · attention on X 0.35 · volume 0.125 · momentum 0.125 · open interest vs normal 0.05.</b> It beats w1 by {fmt(d_w1[0], 2)} IC on the holdout and momentum alone by {fmt(d_mom[0], 2)}.</li>
  </ul>
</section>

<section>
  <h2>The overall race</h2>
  <p>Topics with a prediction market (the dashboard's G2 pool), daily rank IC with the combined target. Shaded: holdout days, never used to choose anything.</p>
  <div class="chart">
    <div class="legend">{''.join(f'<span><i style="background:{COL[c]}"></i>{NAME[c]}</span>' for c in ("w2", "w1", "w0", "mom"))}</div>
    {time_chart()}
  </div>
  <div class="stack">
    <div class="chart"><h3>Holdout rank IC</h3><p class="sub">95% intervals over days</p>{dots(overall_rows, -0.2, 0.6, 0)}</div>
    <div class="chart"><h3>Holdout top-5 percentile</h3><p class="sub">where the day's top 5 land; 0.5 = random</p>{dots(overall_top5, 0.3, 0.9, 0.5)}</div>
  </div>
</section>

<section>
  <h2>A · Social (Adanos)</h2>
  <p>{M['A']['days']} trading days ({M['A']['first']} to {M['A']['last']}), ~{M['A']['per_day']:.0f} topics a day. Rank IC with the combined target, all days. ★ = in the champion: <b>{' + '.join(esc(ev.A_FEATS.get(f, f)) for f in M['selected']['A'])}</b>.</p>
  <div class="chart">{dots(A_rows, -0.2, 0.4, 0)}</div>
  {feat_table('A', 'single', 'label_comb', ev.A_FEATS)}
</section>

<section>
  <h2>B · Price and momentum</h2>
  <p>{M['B']['days']} trading days ({M['B']['first']} to {M['B']['last']}), ~{M['B']['per_day']:.0f} stocks and topics a day. Rank IC with the next session's abnormal move. Champion: <b>{' + '.join(esc(ev.B_FEATS.get(f, f)) for f in M['selected']['B'])}</b>.</p>
  <div class="chart">{dots(B_rows, -0.1, 0.2, 0)}</div>
  {feat_table('B', 'single_long', 'label_move', ev.B_FEATS)}
  <p>On the combined target (social era) the order is the same: volume {fmt(R['B']['single']['label_comb']['vol_abn']['all']['ic'][0])}, range {fmt(R['B']['single']['label_comb']['rng_abn']['all']['ic'][0])}, |24h move| {fmt(R['B']['single']['label_comb']['mom']['all']['ic'][0])}.</p>
</section>

<section>
  <h2>C · Prediction markets (Kalshi, Polymarket, perps)</h2>
  <p>{M['C']['days']} trading days of Kalshi ({M['C']['first']} to {M['C']['last']}), ~{M['C']['per_day']:.0f} topics a day with volume. Rank IC with the next session's abnormal move. Champion (chosen on the combined target): <b>{' + '.join(esc(ev.C_FEATS.get(f, f)) for f in M['selected']['C'])}</b>.</p>
  <div class="chart">{dots(C_rows, -0.1, 0.2, 0)}</div>
  {feat_table('C', 'single', 'label_comb', ev.C_FEATS)}
  <p>Kalshi perps only cover 28 underlyings since June, about 15 of them priced topics on a given day: too few to test. Their funding and volume are now archived on every pull.</p>
</section>

<section>
  <h2>D · Rules</h2>
  <div class="tbl"><table><thead><tr><th>Rule</th><th>All days</th><th>Holdout</th><th>Note</th></tr></thead><tbody>
    <tr><td class="l">Missing input = median (w2)</td><td>{fmt(R['D']['missing']['overall']['all']['ic'][0])}</td><td>{fmt(R['D']['missing']['overall']['holdout']['ic'][0])}</td><td>rank IC</td></tr>
    <tr><td class="l">Missing input left out, weights rescaled</td><td>{fmt(R['D']['missing']['drop_missing']['all']['ic'][0])}</td><td>{fmt(R['D']['missing']['drop_missing']['holdout']['ic'][0])}</td><td>rank IC; same</td></tr>
    {''.join(f"<tr><td class='l'>Daily pick, no repeat within {k} days</td><td>{cd[k]['all'][0]:.3f}</td><td>{cd[k]['holdout'][0]:.3f}</td><td>pick's percentile; {cd[k]['unique_picks']} different topics</td></tr>" for k in ('0', '1', '3', '5'))}
    <tr><td class="l">Top 5, no class limit</td><td>{R['D']['top5_cap0']['all'][0]:.3f}</td><td>{R['D']['top5_cap0']['holdout'][0]:.3f}</td><td>top-5 percentile</td></tr>
    <tr><td class="l">Top 5, at most 2 per asset class</td><td>{R['D']['top5_cap2']['all'][0]:.3f}</td><td>{R['D']['top5_cap2']['holdout'][0]:.3f}</td><td>top-5 percentile</td></tr>
    <tr><td class="l">G2 off: every topic with social data competes</td><td>{fmt(OA['overall']['label_comb']['all']['ic'][0])}</td><td>{fmt(OA['overall']['label_comb']['holdout']['ic'][0])}</td><td>best weights there: A {OA['weights']['A']}, B {OA['weights']['B']}; top 5 at {OA['overall']['label_comb']['holdout']['top5'][0]:.2f}</td></tr>
  </tbody></table></div>
  <p>Quality multiplier and tiers were tested in the previous study and are off by default; G3 needs order-book spreads the backfill does not have.</p>
</section>

<section>
  <h2>Is momentum in?</h2>
  <p>Yes, twice. The price direction tested six versions of it on {M['B']['days']} days: the plain |24h move| ÷ σ is good (IC {fmt(R['B']['single_long']['label_move']['mom']['all']['ic'][0], 3)}), trading volume vs normal is better ({fmt(R['B']['single_long']['label_move']['vol_abn']['all']['ic'][0], 3)}), and w2 uses both with 0.125 each. Momentum alone is also the benchmark every version is compared with: on the holdout w2 beats it by {fmt(d_mom[0], 2)} IC (95% CI {fmt(d_mom[1], 2)} to {fmt(d_mom[2], 2)}).</p>
</section>

<section class="card">
  <h2>Method and limits</h2>
  <ul>
    <li>Data: Yahoo hourly bars for ~2,000 stocks and every priced topic (2 years); Adanos daily for ~4,500 symbols on Reddit, X, News (90 days, the key's limit); Kalshi hourly candles since February (4.2M rows, before and after the historical cutoff); Kalshi perps since June; Polymarket daily prices.</li>
    <li>No look-ahead: prices from bars ended by 15:00 ET, Adanos from complete UTC days up to t−1, Kalshi from candles ended by 15:00 ET. Labels start after the pick.</li>
    <li>Discovery chose every champion and weight; the holdout (Oct 1–22, 15 days) was used once. One-sided t-tests on daily IC with Holm correction inside each direction.</li>
    <li>The social era is short ({M['A']['days']} days). The archive now records every pull, so the holdout grows by a day each day; re-run in mid-November with fresh, unseen data.</li>
    <li>Attention is persistent: busy topics tend to stay busy. That is what an editor wants to know, and it is why the social inputs say little about price moves.</li>
    <li>Kalshi coverage per day is thin (~50 topics) and history before the cutoff keeps the 4 most traded markets of the most traded event per series and day.</li>
  </ul>
  <p style="color:var(--muted);font-size:13px">Code: <code>backtest/v3/build.py</code>, <code>evaluate.py</code>, <code>page.py</code> on branch <code>feat/dashboard</code>.</p>
</section>
</main>
"""
(V3 / "results.html").write_text(page)
print("wrote", V3 / "results.html", len(page), {c: round(F[c]["hold_ic"][0], 3) for c in F})
