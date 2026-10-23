"""Build backtest/broad/results.html (study broad_v2) from backtest/broad/results.json."""
from __future__ import annotations

import html
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "backtest/broad/results.json").read_text())
V = R["variants"]
SHOW = ["V0", "V1", "V1q", "V3", "MKT", "SOC", "W1", "W1q", "W1n", "AL", "M"]
NAMES = {"V0": "w0 before v2", "V1": "v2 as shipped", "V1q": "v2, no tiers or quality", "V3": "v2 + momentum 0.2",
         "MKT": "market inputs only", "SOC": "Adanos inputs only", "W1": "w1 with quality", "W1q": "w1, missing left out", "W1n": "w1 (new default)",
         "AL": "attention level only", "M": "momentum only"}
ROLE = {"W1n": "acc", "M": "mom", "V0": "old", "V1": "old"}
LABELS = {"label_move": "Next-session price move", "label_attn": "Next-day attention"}


def esc(s):
    return html.escape(str(s))


def dot_chart(label, metric="top5", part="holdout"):
    rows = [(k, V[k][label][part][metric]) for k in SHOW]
    lo = 0.3 if metric != "ic" else -0.2
    hi = 0.85 if metric != "ic" else 0.5
    W, rh, ml, mr, mt = 560, 26, 170, 20, 26
    H = mt + rh * len(rows) + 30
    x = lambda v: ml + (v - lo) / (hi - lo) * (W - ml - mr)  # noqa: E731
    ref = 0.5 if metric != "ic" else 0
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(LABELS[label])}: {metric} by variant">']
    ticks = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8] if metric != "ic" else [-0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4, 0.5]
    for t in ticks:
        out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{mt - 6}" y2="{H - 26}" class="grid"/>')
        out.append(f'<text x="{x(t):.1f}" y="{H - 10}" class="tick" text-anchor="middle">{t:g}</text>')
    out.append(f'<line x1="{x(ref):.1f}" x2="{x(ref):.1f}" y1="{mt - 10}" y2="{H - 26}" class="ref"/>')
    out.append(f'<text x="{x(ref) + 4:.1f}" y="{mt - 12}" class="tick">random</text>')
    for i, (k, (m, a, b)) in enumerate(rows):
        y = mt + rh * i + rh / 2
        cls = ROLE.get(k, "oth")
        out.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" class="lab {cls}">{esc(NAMES[k])}</text>')
        if m == m:
            out.append(f'<line x1="{x(max(a, lo)):.1f}" x2="{x(min(b, hi)):.1f}" y1="{y:.1f}" y2="{y:.1f}" class="ci {cls}"/>')
            out.append(f'<circle cx="{x(m):.1f}" cy="{y:.1f}" r="5" class="pt {cls}"><title>{esc(NAMES[k])}: {m:.3f} (95% CI {a:.3f} to {b:.3f})</title></circle>')
    out.append("</svg>")
    return "\n".join(out)


def comp_chart():
    comps = [("ad_level_z", "Attention level (w1)"), ("momentum", "Momentum"), ("ad3_ment_chg_x", "Mentions 3-day, X"),
             ("activity_shift", "Activity 1-day (w0)"), ("attention_shift", "Buzz change 1-day (w0)"),
             ("money_stock", "Open interest change"), ("money_flow", "Volume change"), ("k_move", "Kalshi prob move"),
             ("p_move", "Polymarket prob move"), ("sentiment_shift", "Sentiment change")]
    C = R["components"]
    W, rh, ml, mr, mt = 560, 30, 170, 20, 30
    H = mt + rh * len(comps) + 30
    lo, hi = -0.2, 0.4
    x = lambda v: ml + (v - lo) / (hi - lo) * (W - ml - mr)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Rank IC of each input with each label">']
    for t in (-0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4):
        out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{mt - 6}" y2="{H - 26}" class="{"ref" if t == 0 else "grid"}"/>')
        out.append(f'<text x="{x(t):.1f}" y="{H - 10}" class="tick" text-anchor="middle">{t:g}</text>')
    for i, (c, name) in enumerate(comps):
        y0 = mt + rh * i
        out.append(f'<text x="{ml - 10}" y="{y0 + rh / 2 + 4:.1f}" text-anchor="end" class="lab">{esc(name)}</text>')
        for j, (lb, cls) in enumerate((("label_move", "s1"), ("label_attn", "s2"))):
            v = C.get(c, {}).get(lb)
            if not v:
                continue
            m, a, b = v["all"]
            yy = y0 + 8 + j * 11
            x0, x1 = sorted((x(0), x(m)))
            out.append(f'<rect x="{x0:.1f}" y="{yy - 4:.1f}" width="{max(1, x1 - x0):.1f}" height="8" rx="1.5" class="bar {cls}"><title>{esc(name)} · {esc(LABELS[lb])}: IC {m:+.3f} (95% CI {a:+.3f} to {b:+.3f})</title></rect>')
            out.append(f'<line x1="{x(a):.1f}" x2="{x(b):.1f}" y1="{yy:.1f}" y2="{yy:.1f}" class="whisk"/>')
    out.append("</svg>")
    return "\n".join(out)


def table():
    th = "".join(f"<th>{h}</th>" for h in ("Variant", "Move IC disc.", "Move IC hold.", "Move top-5 hold.", "Attn IC disc.", "Attn IC hold.", "Attn top-5 hold.", "Pool"))
    rows = []
    for k, v in V.items():
        def c(lb, part, met):
            m, a, b = v[lb][part][met]
            return f'<td title="95% CI {a:.3f} to {b:.3f}">{m:+.3f}</td>' if met == "ic" else f'<td title="95% CI {a:.3f} to {b:.3f}">{m:.3f}</td>'
        rows.append(f'<tr class="{ROLE.get(k, "")}"><td class="l"><b>{k}</b> {esc(v["label"])}</td>{c("label_move", "discovery", "ic")}{c("label_move", "holdout", "ic")}'
                    f'{c("label_move", "holdout", "top5")}{c("label_attn", "discovery", "ic")}{c("label_attn", "holdout", "ic")}{c("label_attn", "holdout", "top5")}'
                    f'<td>{v["label_move"]["all"]["pool"]:.0f}</td></tr>')
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def pair(k, lb, met="ic"):
    m, a, b = R["pairs"][k]["holdout"][met]
    return f"{m:+.2f} (95% CI {a:+.2f} to {b:+.2f})"


meta = R["meta"]
page = f"""<title>Topic Log Backtest</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column, charts full column width, the decision first. */
:root {{
  --bg: #f7f7f4; --panel: #ffffff; --ink: #1c2226; --muted: #5f6a70; --line: #dfe2de;
  --acc: #1f6f8b; --mom: #b5651d; --old: #8a9399; --s1: #4b7f99; --s2: #c0843a;
  --serif: "Newsreader", Georgia, serif; --sans: "IBM Plex Sans", -apple-system, "Segoe UI", sans-serif; --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #141719; --panel: #1b1f22; --ink: #e7e9e6; --muted: #9aa3a7; --line: #2c3236;
  --acc: #5fb3d1; --mom: #e0a060; --old: #7c868c; --s1: #79a9c2; --s2: #dba566; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #141719; --panel: #1b1f22; --ink: #e7e9e6; --muted: #9aa3a7; --line: #2c3236;
  --acc: #5fb3d1; --mom: #e0a060; --old: #7c868c; --s1: #79a9c2; --s2: #dba566; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.55;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); padding-block: 32px 64px; }}
main {{ max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 28px; }}
h1 {{ font-family: var(--serif); font-weight: 400; font-size: 2.1rem; line-height: 1.15; margin: 0; text-wrap: balance; }}
h2 {{ font-family: var(--serif); font-weight: 600; font-size: 1.3rem; margin: 0; text-wrap: balance; }}
p {{ margin: 0; max-width: 68ch; }}
.eyebrow {{ font: 500 12px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }}
.lede {{ font-size: 1.05rem; color: var(--ink); }}
section {{ display: flex; flex-direction: column; gap: 12px; }}
.verdict {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; display: flex; flex-direction: column; gap: 10px; }}
.verdict ul, .notes ul {{ margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 6px; }}
.chart {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 14px 6px; overflow-x: auto; }}
.chart h3 {{ font: 600 13px/1.3 var(--sans); margin: 0 0 4px; }}
.chart .sub {{ font-size: 12px; color: var(--muted); margin: 0 0 6px; }}
.pair {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap: 14px; }}
svg {{ width: 100%; height: auto; display: block; min-width: 420px; }}
svg text {{ fill: var(--muted); font: 11px var(--sans); }}
svg .lab {{ fill: var(--ink); font-size: 12px; }}
svg .lab.acc {{ fill: var(--acc); font-weight: 600; }} svg .lab.mom {{ fill: var(--mom); font-weight: 600; }}
svg .grid {{ stroke: var(--line); stroke-width: 1; }} svg .ref {{ stroke: var(--muted); stroke-dasharray: 3 3; }}
svg .ci {{ stroke-width: 2; stroke: var(--old); }} svg .pt {{ fill: var(--old); stroke: var(--panel); stroke-width: 1.5; }}
svg .ci.acc {{ stroke: var(--acc); }} svg .pt.acc {{ fill: var(--acc); }} svg .ci.mom {{ stroke: var(--mom); }} svg .pt.mom {{ fill: var(--mom); }}
svg .ci.oth {{ stroke: var(--old); opacity: .55; }} svg .pt.oth {{ fill: var(--old); opacity: .8; }}
svg .bar.s1 {{ fill: var(--s1); }} svg .bar.s2 {{ fill: var(--s2); }} svg .whisk {{ stroke: var(--ink); stroke-width: 1; opacity: .55; }}
.legend {{ display: flex; gap: 14px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }}
.tbl {{ overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }}
table {{ border-collapse: collapse; width: 100%; font: 12.5px/1.35 var(--mono); font-variant-numeric: tabular-nums; }}
th, td {{ padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
th {{ font: 500 11px/1.3 var(--sans); color: var(--muted); text-align: right; }}
th:first-child, td.l {{ text-align: left; font-family: var(--sans); white-space: normal; min-width: 15rem; }}
tr.acc td {{ color: var(--acc); }} tr.mom td {{ color: var(--mom); }}
.kv {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; font-size: 14px; }}
.kv dt {{ color: var(--muted); }} .kv dd {{ margin: 0; }}
code {{ font-family: var(--mono); font-size: .92em; }}
</style>
<main>
<header style="display:flex;flex-direction:column;gap:10px">
  <span class="eyebrow">Study broad_v2 · {meta['first']} to {meta['last']} · {meta['days']} trading days · {meta['topics']} topics</span>
  <h1>Which version of the Topic Log score picks the topics that matter the next day?</h1>
  <p class="lede">Each trading day at 15:00 ET the dashboard's pull was rebuilt from the backfill, every scoring variant ranked the topics that pass the gates, and the ranking was compared with what happened after the pick: the next session's price move, and the next day's Adanos mentions against the topic's normal level.</p>
</header>

<section class="verdict">
  <h2>Result</h2>
  <ul>
    <li><b>w0 and v2 as shipped do no better than chance.</b> On the holdout their rank IC is about zero for price moves and for attention.</li>
    <li><b>The 1-day changes are the weak part, the data is not.</b> How far a topic's mentions sit above its own 20-day normal predicts the next day's attention strongly (IC +0.35), and 3-day mention changes beat 1-day changes. Sentiment change has no signal, or a negative one.</li>
    <li><b>Prediction-market inputs add little.</b> Volume and open-interest changes are slightly positive and not significant; probability moves are about zero.</li>
    <li><b>w1 is the new default.</b> On the holdout it beats v2 by {pair('W1n-V1-label_move', 'label_move')} IC on price moves and {pair('W1n-V1-label_attn', 'label_attn')} on attention.</li>
    <li><b>Momentum is still as good on price moves.</b> w1 ties it there ({pair('W1n-M-label_move', 'label_move')}) and beats it on attention ({pair('W1n-M-label_attn', 'label_attn')}). Momentum is now in the score with weight 0.25.</li>
  </ul>
</section>

<section>
  <h2>Where the top 5 picks land</h2>
  <p>Mean percentile of the day's top 5 among all gated topics, holdout days only ({meta['n_hold']} days). 0.5 is a random pick. Lines are 95% bootstrap intervals over days.</p>
  <div class="pair">
    <div class="chart"><h3>{LABELS['label_move']}</h3><p class="sub">|move| ÷ 20-day σ, next session at the same time</p>{dot_chart('label_move')}</div>
    <div class="chart"><h3>{LABELS['label_attn']}</h3><p class="sub">mentions on day t+1 vs the 20 days before (Reddit + X + News)</p>{dot_chart('label_attn')}</div>
  </div>
</section>

<section>
  <h2>Rank IC on the holdout</h2>
  <p>Daily Spearman correlation between the ranking and the outcome, over every topic in the pool. Rank IC uses the whole ranking, so it is steadier than the top 5.</p>
  <div class="pair">
    <div class="chart"><h3>{LABELS['label_move']}</h3>{dot_chart('label_move', 'ic')}</div>
    <div class="chart"><h3>{LABELS['label_attn']}</h3>{dot_chart('label_attn', 'ic')}</div>
  </div>
</section>

<section>
  <h2>Which inputs carry information</h2>
  <p>Rank IC of each input on its own, all {meta['days']} days, every topic that has the input (no gates).</p>
  <div class="chart">
    <div class="legend"><span><i style="background:var(--s1)"></i>next-session price move</span><span><i style="background:var(--s2)"></i>next-day attention</span></div>
    {comp_chart()}
  </div>
</section>

<section>
  <h2>What changed from w0 to w1</h2>
  <dl class="kv">
    <dt>Attention</dt><dd>1-day buzz change → mentions on t−1 against the topic's own mean over t−20…t−2 (log ratio, Reddit + X + News). Weight 0.25 → 0.30.</dd>
    <dt>Activity</dt><dd>1-day mention change → last 3 days against the 3 before. Weight 0.10.</dd>
    <dt>Momentum</dt><dd>Reference column → in the score, weight 0 → 0.25.</dd>
    <dt>Sentiment</dt><dd>0.15 → 0 (no signal, negative on attention).</dd>
    <dt>Money flow / stock / move</dt><dd>0.20 / 0.10 / 0.20 → 0.15 / 0.10 / 0.10.</dd>
    <dt>Missing inputs</dt><dd>Left out with weights rescaled → counted as the pool median (0.5). Same backtest result, and a topic with one strong input and nothing else can no longer top the list.</dd>
    <dt>Quality multiplier</dt><dd>On → off by default (switch kept). With it on, w1 loses about a third of its edge.</dd>
    <dt>Tiers</dt><dd>Rank by tier → labels only (switch kept). Ranking by tier did not help in any variant.</dd>
    <dt>Gates</dt><dd>Unchanged: G2 needs prediction-market volume, G3 spread and zero-trade limits.</dd>
  </dl>
</section>

<section>
  <h2>All variants</h2>
  <p>Discovery {meta['first']} to Sep 30 ({meta['n_disc']} days), holdout Oct 1 to {meta['last'][5:]} ({meta['n_hold']} days). Hover a number for its 95% interval.</p>
  <div class="tbl">{table()}</div>
</section>

<section class="notes">
  <h2>Limits</h2>
  <ul>
    <li>41 trading days and about 80 gated topics a day. Effects smaller than about 0.05 IC are hard to tell from zero.</li>
    <li>w1's inputs were chosen after looking at the input ICs over the full window, so its discovery numbers are not a clean test. The holdout agrees with discovery for every w1 variant.</li>
    <li>Kalshi's backfill keeps long-dated events for their last 30 days only, so Kalshi inputs are thinner before late September. Polymarket has daily prices but no volume history, so Polymarket only enters through probability moves here.</li>
    <li>Earnings dates are not in the backfill, so tier T1 for companies could not be tested. Cooldown (G4) is off in both the live dashboard and the backtest.</li>
    <li>Next-day attention is persistent: a topic that is busy today is usually busy tomorrow. That is what makes the attention level useful for choosing a topic, and it is also why it says little about price moves.</li>
  </ul>
  <p style="color:var(--muted);font-size:13px">Code: <code>backtest/broad_features.py</code>, <code>backtest/broad_eval.py</code>, <code>backtest/broad_page.py</code> on branch <code>feat/dashboard</code>.</p>
</section>
</main>
"""
(ROOT / "backtest/broad/results.html").write_text(page)
print("wrote", ROOT / "backtest/broad/results.html", len(page))
