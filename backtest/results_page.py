"""Build backtest/results.html: one page with every study's conclusion, charts and tables.

    python -m backtest.results_page

Reads the latest run of each study under backtest/runs/. Charts are static inline SVG, so the
page opens offline from the repo, on GitHub Pages, or as a published link.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "backtest" / "runs"
OUT = ROOT / "backtest" / "results.html"
COMPONENTS = ["attention_shift", "activity_shift", "money_flow", "money_stock", "market_move", "sentiment_shift"]


def esc(x):
    return html.escape(str(x))


def f(x, nd=3, sign=False):
    if x is None or x != x:
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def latest_runs(study):
    out = {}
    for d in sorted((RUNS / study).iterdir()):
        sj = d / "summary.json"
        if sj.exists():
            s = json.loads(sj.read_text())
            out[s.get("version", "run")] = (d, s)
    return out


# ------------------------------------------------------------------ svg helpers
class Scale:
    def __init__(self, d0, d1, r0, r1):
        self.d0, self.d1, self.r0, self.r1 = d0, d1, r0, r1

    def __call__(self, v):
        return self.r0 + (v - self.d0) / (self.d1 - self.d0) * (self.r1 - self.r0)


def ticks(lo, hi, step):
    out, v = [], lo
    while v <= hi + 1e-9:
        out.append(round(v, 6))
        v += step
    return out


def dot_ci_chart(rows, xlo, xhi, step, ref=None, ref_label="", xlabel="", series=None, height_per=34, left=150):
    """rows: [(label, [(series_key, value, lo, hi, tooltip), ...])]. Horizontal dot + CI."""
    series = series or {}
    W, L, R, T = 640, left, 24, 34
    H = T + height_per * len(rows) + 40
    x = Scale(xlo, xhi, L, W - R)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']
    for t in ticks(xlo, xhi, step):
        xx = x(t)
        p.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{T-8}" y2="{H-34}" class="grid"/>')
        p.append(f'<text x="{xx:.1f}" y="{H-18}" class="tick" text-anchor="middle">{t:g}</text>')
    if ref is not None:
        xr = x(ref)
        p.append(f'<line x1="{xr:.1f}" x2="{xr:.1f}" y1="{T-12}" y2="{H-34}" class="ref"/>')
        p.append(f'<text x="{xr+4:.1f}" y="{T-14}" class="tick">{esc(ref_label)}</text>')
    p.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H-2}" class="axis" text-anchor="middle">{esc(xlabel)}</text>')
    nser = max(len(r[1]) for r in rows)
    for i, (label, marks) in enumerate(rows):
        yc = T + height_per * i + height_per / 2
        p.append(f'<text x="{L-10}" y="{yc+4:.1f}" class="lab" text-anchor="end">{esc(label)}</text>')
        for j, (key, v, lo, hi, tip) in enumerate(marks):
            if v is None or v != v:
                continue
            off = (j - (nser - 1) / 2) * 9 if nser > 1 else 0
            y = yc + off
            cls, shape = series.get(key, ("s1", "dot"))
            g = f'<g class="mark {cls}"><title>{esc(tip)}</title>'
            if lo is not None and lo == lo:
                g += f'<line x1="{x(max(lo, xlo)):.1f}" x2="{x(min(hi, xhi)):.1f}" y1="{y:.1f}" y2="{y:.1f}" class="ci"/>'
            if shape == "diamond":
                g += f'<rect x="{x(v)-4.5:.1f}" y="{y-4.5:.1f}" width="9" height="9" transform="rotate(45 {x(v):.1f} {y:.1f})" class="pt"/>'
            else:
                g += f'<circle cx="{x(v):.1f}" cy="{y:.1f}" r="5.5" class="pt"/>'
            p.append(g + "</g>")
    p.append("</svg>")
    return "".join(p)


def stacked_chart(rows, keys, classes, labels, xlabel):
    W, L, R, T, bh = 640, 70, 24, 10, 20
    H = T + 30 * len(rows) + 40
    x = Scale(0, 1, L, W - R)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']
    for t in ticks(0, 1, 0.25):
        p.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T}" y2="{H-34}" class="grid"/>')
        p.append(f'<text x="{x(t):.1f}" y="{H-18}" class="tick" text-anchor="middle">{int(t*100)}%</text>')
    p.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-2}" class="axis" text-anchor="middle">{esc(xlabel)}</text>')
    for i, (label, vals) in enumerate(rows):
        y = T + 30 * i + 5
        p.append(f'<text x="{L-10}" y="{y+bh/2+4:.1f}" class="lab" text-anchor="end">{esc(label)}</text>')
        acc = 0.0
        for k in keys:
            v = vals.get(k, 0.0)
            if v <= 0:
                continue
            p.append(f'<g class="mark {classes[k]}"><title>{esc(label)} · {esc(labels[k])}: {v*100:.0f}% of days</title>'
                     f'<rect x="{x(acc):.1f}" y="{y}" width="{max(0.5, x(acc+v)-x(acc)-2):.1f}" height="{bh}" rx="3" class="bar"/></g>')
            acc += v
    p.append("</svg>")
    return "".join(p)


def line_chart(series, dates, shade_from=None, ylabel=""):
    """series: [(key, cls, label, values)] cumulative lines over dates."""
    W, L, R, T, B = 640, 46, 70, 14, 40
    H = 260
    allv = [v for _, _, _, vals in series for v in vals if v == v]
    lo, hi = min(0, min(allv)), max(allv)
    step = 2 if hi - lo > 8 else (1 if hi - lo > 4 else 0.5)
    lo, hi = (int(lo / step) - 1) * step, (int(hi / step) + 1) * step
    x = Scale(0, len(dates) - 1, L, W - R)
    y = Scale(lo, hi, H - B, T)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']
    if shade_from is not None and shade_from in dates:
        i0 = dates.index(shade_from)
        p.append(f'<rect x="{x(i0):.1f}" y="{T}" width="{x(len(dates)-1)-x(i0):.1f}" height="{H-B-T}" class="shade"/>')
        p.append(f'<text x="{x(i0)+6:.1f}" y="{T+14}" class="tick">holdout</text>')
    for t in ticks(lo, hi, step):
        p.append(f'<line x1="{L}" x2="{W-R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="{"zero" if t == 0 else "grid"}"/>')
        p.append(f'<text x="{L-6}" y="{y(t)+4:.1f}" class="tick" text-anchor="end">{t:g}</text>')
    for i, d in enumerate(dates):
        if d.day in (1, 15):
            p.append(f'<text x="{x(i):.1f}" y="{H-B+16}" class="tick" text-anchor="middle">{d:%b %d}</text>')
    p.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-4}" class="axis" text-anchor="middle">{esc(ylabel)}</text>')
    for key, cls, label, vals in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals) if v == v)
        last = [(i, v) for i, v in enumerate(vals) if v == v][-1]
        p.append(f'<g class="mark {cls}"><title>{esc(label)}: cumulative {last[1]:.2f}</title>'
                 f'<polyline points="{pts}" class="ln"/><circle cx="{x(last[0]):.1f}" cy="{y(last[1]):.1f}" r="4" class="pt"/>'
                 f'<text x="{x(last[0])+8:.1f}" y="{y(last[1])+4:.1f}" class="lab end">{esc(key)}</text></g>')
    p.append("</svg>")
    return "".join(p)


def legend(items):
    return '<div class="legend">' + "".join(
        f'<span><i class="sw {c} {s}"></i>{esc(t)}</span>' for c, s, t in items) + "</div>"


def table(head, rows, num_from=1):
    h = "".join(f'<th class="{"num" if i >= num_from else ""}">{esc(c)}</th>' for i, c in enumerate(head))
    b = "".join("<tr>" + "".join(f'<td class="{"num" if i >= num_from else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
                for r in rows)
    return f'<div class="tbl"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


# ------------------------------------------------------------------ study sections
SHORT = {
    "B_base": "Main version: w0, pick 15:00 ET, liquidity on ±2% band, volume floor",
    "B_atm3": "Liquidity on the 3 strikes nearest the money",
    "B_no_cooldown": "No cooldown: full pool every day",
    "D_kalshi_only": "Kalshi components only (no Adanos)",
    "C_no_tiers": "No priority tiers", "B_band_1pct": "Liquidity band ±1%", "B_band_3pct": "Liquidity band ±3%",
    "B_floor_off": "No volume floor", "B_floor_p5": "Volume floor at 5th percentile",
    "B_floor_p20": "Volume floor at 20th percentile", "B_cat_crypto": "CPI/FOMC also count for crypto",
    "B_idio": "Crypto label net of BTC beta",
}


def section_crypto_indices():
    runs = latest_runs("crypto_indices")
    order = ["B_base", "B_atm3", "B_no_cooldown", "D_kalshi_only"]
    S = {v: runs[v][1] for v in order if v in runs}
    base = S["B_base"]
    rows = [(v, [("pick", S[v]["pick_pctl"], *S[v]["pick_pctl_ci95"],
                  f"{v} pick percentile {S[v]['pick_pctl']:.3f} (95% CI {S[v]['pick_pctl_ci95'][0]:.2f}–{S[v]['pick_pctl_ci95'][1]:.2f})"),
                 ("mom", S[v]["momentum_pctl"], None, None, f"{v} momentum percentile {S[v]['momentum_pctl']:.3f}")])
            for v in S]
    c1 = dot_ci_chart(rows, 0.3, 0.8, 0.1, ref=0.5, ref_label="random", xlabel="Pick's percentile in the pool on the next move",
                      series={"pick": ("s1", "dot"), "mom": ("s2", "diamond")})
    # component IC
    comp_rows = []
    for k in COMPONENTS:
        marks = []
        for v, cls in (("B_base", "s1"), ("B_no_cooldown", "s3")):
            d = pd.read_csv(runs[v][0] / "daily_log.csv")
            x = d[f"IC_{k}"].dropna()
            if len(x) > 2:
                h = 1.96 * x.std(ddof=1) / len(x) ** 0.5
                marks.append((v, x.mean(), x.mean() - h, x.mean() + h, f"{k} · {v}: IC {x.mean():+.3f} ({len(x)} days)"))
        comp_rows.append((k, marks))
    c2 = dot_ci_chart(comp_rows, -0.4, 0.4, 0.2, ref=0, ref_label="", xlabel="Mean daily rank IC with the next move",
                      series={"B_base": ("s1", "dot"), "B_no_cooldown": ("s3", "dot")}, height_per=38)
    # gates
    d = pd.read_csv(runs["B_base"][0] / "daily_log.csv")
    feats = pd.read_csv(RUNS / "crypto_indices" / "features_B_base.csv")
    cand = feats.groupby("ticker").size()
    g = d.gated.dropna().str.split().explode().reset_index(drop=True).str.split(":", expand=True)
    g.columns = ["ticker", "gate"]
    share = pd.crosstab(g.ticker, g.gate).reindex(cand.index).fillna(0).div(cand, axis=0)
    order_t = share.sum(axis=1).sort_values(ascending=False).index
    c3 = stacked_chart([(t, share.loc[t].to_dict()) for t in order_t], ["G4", "G3", "G2"],
                       {"G2": "s4", "G3": "s2", "G4": "s1"},
                       {"G2": "G2 no traded contract", "G3": "G3 liquidity floor", "G4": "G4 cooldown"},
                       "Share of candidate days removed by a gate (B_base)")
    t1 = table(["Version", "Days", "Pool", "Pick pctl [95% CI]", "p", "IC", "Top-1 hit (random)", "Momentum pctl"],
               [[f"<b>{v}</b><br><span class='sub'>{esc(SHORT.get(v, ''))}</span>", S[v]["days"], S[v]["avg_pool"],
                 f"{S[v]['pick_pctl']:.3f} [{S[v]['pick_pctl_ci95'][0]:.2f}, {S[v]['pick_pctl_ci95'][1]:.2f}]",
                 f(S[v]["p_value_vs_random"]), f(S[v]["IC_mean"], sign=True),
                 f"{S[v]['hit_top1']:.2f} ({S[v]['random_hit_top1']:.2f})", f(S[v]["momentum_pctl"])] for v in S])
    arch = json.loads((RUNS / "crypto_indices" / "archived_versions.json").read_text())
    t2 = table(["Removed version", "Pick pctl", "p", "IC", "Momentum pctl"],
               [[f"{esc(a['version'])}<br><span class='sub'>{esc(SHORT.get(a['version'], ''))}</span>", f(a["pick_pctl"]),
                 f(a["p_value_vs_random"]), f(a["IC_mean"], sign=True), f(a["momentum_pctl"])] for a in arch])
    return f"""
<section id="crypto_indices">
  <header class="shead"><span class="eyebrow">Study 1 · Kalshi + Adanos · 2026-08-04 → 09-30</span>
    <h2>Crypto and indices</h2>
    <p class="facts">8 tickers (BTC ETH SOL XRP DOGE · SPX NDX DJI) · 54 evaluated days · pick at 15:00 ET · label: next-day |move| ÷ 20-day σ</p></header>
  <div class="verdict"><p><b>No version of <code>demand_score</code> beat a random pick.</b> The main version put its pick at the {base['pick_pctl']*100:.0f}th percentile (random = 50th, p = {base['p_value_vs_random']:.2f}). Picking the biggest recent mover landed at the {base['momentum_pctl']*100:.0f}th. With about 3.7 tickers a day, only effects above IC ≈ 0.17 are detectable.</p></div>
  <div class="grid2">
    <figure><figcaption>Where the pick landed</figcaption>{legend([("s1","dot","demand_score pick, 95% CI"),("s2","diamond","momentum pick")])}{c1}</figure>
    <figure><figcaption>Which components carry information</figcaption>{legend([("s1","dot","B_base"),("s3","dot","B_no_cooldown (full pool)")])}{c2}</figure>
  </div>
  <figure class="wide"><figcaption>Why tickers left the pool</figcaption>{legend([("s1","bar","G4 cooldown"),("s2","bar","G3 liquidity floor"),("s4","bar","G2 no traded contract")])}{c3}</figure>
  <h3>Versions</h3>{t1}
  <details><summary>Removed versions (8)</summary>{t2}</details>
</section>"""


def section_adanos():
    runs = latest_runs("adanos_crypto")
    d, s = runs["run"]
    sig, inp = s["signals"], s["inputs"]
    names = {"A0": "A0 · 1-day change (w0)", "A1": "A1 · abnormal level", "A2": "A2 · level, no percentile",
             "A3": "A3 · 3-day smoothing", "M": "M · momentum"}
    rows = [(names[k], [("disc", sig["discovery"][k]["IC"], *sig["discovery"][k]["ci95"], f"{k} discovery IC {sig['discovery'][k]['IC']:+.3f}"),
                        ("hold", sig["holdout"][k]["IC"], *sig["holdout"][k]["ci95"], f"{k} holdout IC {sig['holdout'][k]['IC']:+.3f}")])
            for k in ["A0", "A1", "A2", "A3", "M"]]
    c1 = dot_ci_chart(rows, -0.3, 0.4, 0.1, ref=0, xlabel="Mean daily rank IC with next-day range", left=190,
                      series={"disc": ("s4", "dot"), "hold": ("s1", "dot")}, height_per=40)
    inames = {"buzz_d1": "buzz · 1-day change", "mentions_d1": "mentions · 1-day change", "sentiment_d1": "sentiment · 1-day change",
              "buzz_z": "buzz · abnormal level", "mentions_z": "mentions · abnormal level", "sentiment_z": "sentiment · abnormal level"}
    ev = inp["evaluation"]
    rows2 = [(inames[k], [("in", ev[k]["IC"], *ev[k]["ci95"], f"{k}: IC {ev[k]['IC']:+.3f}, Holm p {ev[k]['p_holm']:.2f}")]) for k in inames]
    c2 = dot_ci_chart(rows2, -0.2, 0.2, 0.1, ref=0, xlabel="Mean daily rank IC, all 60 days", series={"in": ("s3", "dot")},
                      left=190)
    ic = pd.read_csv(d / "daily_ic.csv", parse_dates=["date"])
    ic["date"] = ic.date.dt.date
    ic = ic.sort_values("date")
    dates = list(ic.date)
    series = [("M", "s2", "momentum", ic.M.fillna(0).cumsum().tolist()),
              ("A3", "s1", "A3 3-day smoothing", ic.A3.fillna(0).cumsum().tolist()),
              ("A0", "s4", "A0 1-day change", ic.A0.fillna(0).cumsum().tolist())]
    c3 = line_chart(series, dates, shade_from=dt.date.fromisoformat(s["config"]["holdout"][0]),
                    ylabel="Cumulative daily IC (a straight rising line = a steady signal)")
    ho = sig["holdout"]
    t1 = table(["Version", "Discovery IC", "Holdout IC [95% CI]", "Holdout p (Holm)", "Holdout pick pctl", "Holdout IC, close label"],
               [[names[k], f(sig["discovery"][k]["IC"], sign=True),
                 f"{ho[k]['IC']:+.3f} [{ho[k]['ci95'][0]:+.2f}, {ho[k]['ci95'][1]:+.2f}]", f(ho[k]["p_holm"], 2),
                 f(ho[k]["pick_pctl"]), f(s["signals_close_label"]["holdout"][k]["IC"], sign=True)] for k in names])
    t2 = table(["Input", "IC, 60 days [95% CI]", "p (Holm)", "Holdout IC", "Min. detectable IC"],
               [[inames[k], f"{ev[k]['IC']:+.3f} [{ev[k]['ci95'][0]:+.2f}, {ev[k]['ci95'][1]:+.2f}]", f(ev[k]["p_holm"], 2),
                 f(inp["holdout"][k]["IC"], sign=True), f(ev[k]["mde"], 2)] for k in inames])
    va, vm = s["holdout_vs_A0"], s["holdout_vs_M"]
    t3 = table(["Pre-registered check (holdout)", "Result"], [
        ["Any input significant", "No"],
        ["Smallest detectable IC on the holdout", f"{s['decision']['max_mde_inputs']:.2f} (rule needs < 0.08)"],
        ["Carried variant (best of A1–A3 on discovery)", s["carried_variant"]],
        [f"{s['carried_variant']} − A0, daily IC", f"{va['mean']:+.3f} [{va['ci95'][0]:+.2f}, {va['ci95'][1]:+.2f}] · beats A0"],
        [f"{s['carried_variant']} − momentum, daily IC", f"{vm['mean']:+.3f} [{vm['ci95'][0]:+.2f}, {vm['ci95'][1]:+.2f}] · loses to momentum"],
        ["Verdict by the rule", esc(s["decision"]["verdict"])],
        ["Sanity: oracle IC / random IC (200 seeds)", f"{s['sanity_oracle_IC']:.2f} / {s['sanity_random_IC_mean']:+.3f}"],
    ], num_from=9)
    return f"""
<section id="adanos_crypto">
  <header class="shead"><span class="eyebrow">Study 2 · Adanos Reddit + Binance · pre-registered · 2026-08-03 → 10-01</span>
    <h2>Adanos signals on crypto</h2>
    <p class="facts">{s['n_tokens']} tokens fixed from July data · {s['n_rows']:,} token-days · discovery 36 days, holdout 24 · label: next-day high–low range ÷ its 20-day mean</p></header>
  <div class="verdict"><p><b>The 1-day change construction is the weak point; the data itself is weak too.</b> With the same Reddit inputs, 3-day smoothing beat w0's 1-day changes on the holdout ({va['mean']:+.2f} daily IC, 95% CI {va['ci95'][0]:+.2f} to {va['ci95'][1]:+.2f}). No single input was significant, and momentum (holdout IC {ho['M']['IC']:+.2f}) beat every Adanos version.</p></div>
  <div class="grid2">
    <figure><figcaption>Signal versions, discovery vs holdout</figcaption>{legend([("s4","dot","discovery"),("s1","dot","holdout, 95% CI")])}{c1}</figure>
    <figure><figcaption>Each Reddit input on its own</figcaption>{c2}</figure>
  </div>
  <figure class="wide"><figcaption>How the signals accumulate day by day</figcaption>{legend([("s2","line","momentum"),("s1","line","A3 · 3-day smoothing"),("s4","line","A0 · 1-day change")])}{c3}</figure>
  <h3>Versions</h3>{t1}
  <h3>Inputs</h3>{t2}
  <h3>Decision</h3>{t3}
  <p class="note">Universe: {esc(', '.join(s['universe']))}.</p>
</section>"""


CSS = """
/* Layout: a single reading column of study sections, each verdict → charts → tables. Tokens follow the playbook. */
:root{
  --bg:#EEF1F5; --paper:#FCFCFB; --ink:#141B24; --muted:#5B6776; --rule:#DCE1E7;
  --accent:#2448B8; --accent-soft:#E6ECFA;
  --s1:#2448B8; --s2:#C2481E; --s3:#1D7A5A; --s4:#8A94A0;
  --f-display:"Archivo","Helvetica Neue",Arial,sans-serif;
  --f-body:"IBM Plex Sans",-apple-system,"Segoe UI",sans-serif;
  --f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0E131A; --paper:#161C24; --ink:#E4E9EF; --muted:#98A5B4; --rule:#2B3440;
  --accent:#8AA6F5; --accent-soft:#1F2B48; --s1:#8AA6F5; --s2:#F08A62; --s3:#5CC99F; --s4:#7D8896; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0E131A; --paper:#161C24; --ink:#E4E9EF; --muted:#98A5B4; --rule:#2B3440;
  --accent:#8AA6F5; --accent-soft:#1F2B48; --s1:#8AA6F5; --s2:#F08A62; --s3:#5CC99F; --s4:#7D8896; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--f-body)}
.wrap{max-width:1040px;margin:0 auto;padding-inline:16px;padding-block:28px 64px;display:flex;flex-direction:column;gap:28px}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:end;gap:12px}
h1{font-family:var(--f-display);font-stretch:75%;font-weight:850;font-size:clamp(30px,5vw,44px);line-height:1;margin:0;text-wrap:balance}
.top p{margin:6px 0 0;color:var(--muted);max-width:62ch}
nav.jump{display:flex;gap:6px;flex-wrap:wrap}
nav.jump a{font-family:var(--f-mono);font-size:12px;padding:5px 10px;border:1px solid var(--rule);border-radius:99px;color:var(--ink);text-decoration:none;background:var(--paper)}
nav.jump a:hover,nav.jump a:focus-visible{border-color:var(--accent);outline:none}
section{background:var(--paper);border:1px solid var(--rule);border-radius:6px;padding:24px clamp(16px,3vw,32px);display:flex;flex-direction:column;gap:18px;min-width:0}
.shead{display:flex;flex-direction:column;gap:4px}
.eyebrow{font-family:var(--f-mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
h2{font-family:var(--f-display);font-stretch:80%;font-weight:800;font-size:28px;line-height:1.05;margin:0;text-wrap:balance}
h3{font-family:var(--f-display);font-stretch:90%;font-weight:700;font-size:16px;margin:6px 0 -6px}
.facts{margin:0;color:var(--muted);font-size:13.5px}
.verdict{border-left:3px solid var(--accent);background:var(--accent-soft);padding:12px 16px;border-radius:0 4px 4px 0}
.verdict p{margin:0;max-width:78ch}
code{font-family:var(--f-mono);font-size:.88em}
.grid2{display:flex;flex-direction:column;gap:22px}
figure{margin:0;display:flex;flex-direction:column;gap:6px;min-width:0}
figcaption{font-weight:600;font-size:14px}
.chart{width:100%;max-width:640px;height:auto;display:block}
.chart .grid{stroke:var(--rule);stroke-width:1}
.chart .zero,.chart .ref{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 3}
.chart .tick{fill:var(--muted);font:11px var(--f-mono)}
.chart .axis{fill:var(--muted);font:11.5px var(--f-body)}
.chart .lab{fill:var(--ink);font:12px var(--f-body)}
.chart .lab.end{font:600 11px var(--f-mono)}
.chart .shade{fill:var(--accent-soft)}
.chart .ci{stroke-width:2.2;stroke-linecap:round}
.chart .pt{stroke:var(--paper);stroke-width:2}
.chart .ln{fill:none;stroke-width:2.2;stroke-linejoin:round}
.chart .bar{stroke:none}
.chart .s1 .ci,.chart .s1 .ln{stroke:var(--s1)} .chart .s1 .pt,.chart .s1 .bar{fill:var(--s1)}
.chart .s2 .ci,.chart .s2 .ln{stroke:var(--s2)} .chart .s2 .pt,.chart .s2 .bar{fill:var(--s2)}
.chart .s3 .ci,.chart .s3 .ln{stroke:var(--s3)} .chart .s3 .pt,.chart .s3 .bar{fill:var(--s3)}
.chart .s4 .ci,.chart .s4 .ln{stroke:var(--s4)} .chart .s4 .pt,.chart .s4 .bar{fill:var(--s4)}
.chart .mark:hover .pt{stroke:var(--ink)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:10px;height:10px;border-radius:50%}
.sw.diamond{border-radius:1px;transform:rotate(45deg);width:9px;height:9px}
.sw.bar{border-radius:2px;width:12px}
.sw.line{border-radius:2px;height:3px;width:16px}
.sw.s1{background:var(--s1)} .sw.s2{background:var(--s2)} .sw.s3{background:var(--s3)} .sw.s4{background:var(--s4)}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-family:var(--f-mono);font-weight:500;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1.5px solid var(--ink);white-space:nowrap}
td.num,th.num{text-align:right;white-space:nowrap;font-family:var(--f-mono);font-size:12.5px}
.sub{color:var(--muted);font-size:12px}
details summary{cursor:pointer;font-weight:600;font-size:14px}
details[open] summary{margin-bottom:8px}
.note{margin:0;color:var(--muted);font-size:13px}
footer{color:var(--muted);font-size:13px;display:flex;flex-direction:column;gap:6px}
footer code{background:var(--paper);border:1px solid var(--rule);padding:1px 6px;border-radius:3px}
"""


def build():
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = f"""<title>Topic Log Backtests</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,600..900&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <div class="top">
    <div><h1>Topic Log Backtests</h1>
      <p>Does the Topic Log pick the tickers that turn out to move? Each study: the conclusion, the charts, the numbers.</p></div>
    <nav class="jump" aria-label="Studies"><a href="#crypto_indices">Study 1 · crypto + indices</a><a href="#adanos_crypto">Study 2 · Adanos</a></nav>
  </div>
  {section_crypto_indices()}
  {section_adanos()}
  <footer>
    <span>Built {built} from the latest runs in <code>backtest/runs/</code>. Hover a mark for its value.</span>
    <span>Reproduce: <code>python -m backtest.run --study backtest/studies/crypto_indices</code> · <code>python -m backtest.adanos_study run</code> · <code>python -m backtest.results_page</code></span>
  </footer>
</div>
"""
    doc = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + page.replace("</style>", "</style>\n</head><body>", 1)
           + "</body></html>\n")
    OUT.write_text(doc)
    print("->", OUT.relative_to(ROOT))
    return page


if __name__ == "__main__":
    build()
