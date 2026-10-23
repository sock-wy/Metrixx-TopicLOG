"""Study `broad_v2`: evaluate Topic Log scoring variants on backtest/broad/features.parquet.

Each day, every topic in the pool gets a score from the variant (same construction as the dashboard:
within-day percentile of each component, weighted mean, quality multiplier, tiers) and is compared with
what happened after the pick:
  label_move  next-session |move| / sigma20     (does the pick move?)
  label_attn  next-day Adanos mentions vs the topic's 20-day mean   (does the pick draw attention?)

Metrics per day: rank IC (Spearman) over the pool; mean label percentile of the top 5 and of the top 1.
Discovery 2026-08-26 .. 09-30, holdout 10-01 .. 10-21. 95% CIs by bootstrap over days.
Writes backtest/broad/results.json.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
F = ROOT / "backtest" / "broad"
SPLIT = dt.date(2026, 10, 1)
PL = ["reddit", "x", "news"]
W0 = dict(attention_shift=.25, activity_shift=.10, money_flow=.20, money_stock=.10, market_move=.20, sentiment_shift=.15, momentum=0)
COMP = list(W0)
rng = np.random.default_rng(7)


def wmean(pairs):
    num = den = 0.0
    for v, w in pairs:
        if v is not None and not (isinstance(v, float) and np.isnan(v)) and w and w > 0:
            num += v * w; den += w
    return num / den if den else np.nan


def combine(r, cfg):
    k, p = cfg["kalshi"], cfg["poly"]
    plats = cfg["plats"]
    pre = "ad3_" if cfg.get("smooth") else "ad_"
    kv = r.k_vol if r.k_vol == r.k_vol else 0
    pw = 1.0 if r.p_move == r.p_move else 0  # Polymarket volume history is not in the backfill: equal weight
    out = {}
    out["money_flow"] = r.k_flow if k else np.nan
    out["money_stock"] = r.k_oi_chg if k else np.nan
    out["market_move"] = wmean([(r.k_move if k else None, kv), (r.p_move if p else None, pw * max(kv, 1))])
    vals = lambda name: [getattr(r, f"{pre}{name}_{x}") for x in plats if getattr(r, f"{pre}{name}_{x}") == getattr(r, f"{pre}{name}_{x}")]  # noqa: E731
    a = vals("buzz_d"); out["attention_shift"] = np.mean(a) if a else np.nan
    if cfg.get("attn_level"):  # abnormal attention level: mentions on t-1 vs the topic's own 20-day mean (all platforms)
        out["attention_shift"] = r.ad_level_z
    if cfg.get("smooth_act"):
        a = [getattr(r, f"ad3_ment_chg_{x}") for x in plats if getattr(r, f"ad3_ment_chg_{x}") == getattr(r, f"ad3_ment_chg_{x}")]
        out["activity_shift"] = np.mean(a) if a else np.nan
    a = vals("ment_chg"); out["activity_shift"] = np.mean(a) if a else np.nan
    a = vals("sent_d"); out["sentiment_shift"] = np.mean(np.abs(a)) if a else np.nan
    out["momentum"] = r.momentum
    out["pm_evidence"] = bool((k and kv > 0) or (p and pw > 0))
    out["spread"] = r.k_spread if k else np.nan
    out["zero"] = r.k_zero if k else np.nan
    fam = int(any(out[c] == out[c] for c in ("money_flow", "money_stock", "market_move"))) + \
        int(any(out[c] == out[c] for c in ("attention_shift", "activity_shift", "sentiment_shift")))
    out["families"] = fam
    return out


def pctrank(s):
    s = pd.Series(s, dtype=float)
    return s.rank(pct=True, method="average")


VARIANTS = {
    "V0":  dict(label="w0 as before (Kalshi + Reddit)", kalshi=True, poly=False, plats=["reddit"], tiers=True, quality=True),
    "V1":  dict(label="v2 now (Kalshi + Polymarket, Reddit + X + News)", kalshi=True, poly=True, plats=PL, tiers=True, quality=True),
    "V1n": dict(label="v2, tiers as labels only", kalshi=True, poly=True, plats=PL, tiers=False, quality=True),
    "V1q": dict(label="v2, no tiers, no quality", kalshi=True, poly=True, plats=PL, tiers=False, quality=False),
    "V2":  dict(label="v2 + 3-day smoothing for Adanos", kalshi=True, poly=True, plats=PL, smooth=True, tiers=False, quality=True),
    "V3":  dict(label="v2 + momentum weight 0.20", kalshi=True, poly=True, plats=PL, tiers=False, quality=True, w=dict(W0, momentum=.20)),
    "V4":  dict(label="v2 + smoothing + momentum 0.20", kalshi=True, poly=True, plats=PL, smooth=True, tiers=False, quality=True, w=dict(W0, momentum=.20)),
    "MKT": dict(label="market components only", kalshi=True, poly=True, plats=PL, tiers=False, quality=True,
                w=dict(W0, attention_shift=0, activity_shift=0, sentiment_shift=0)),
    "SOC": dict(label="Adanos components only", kalshi=True, poly=True, plats=PL, tiers=False, quality=True,
                w=dict(W0, money_flow=0, money_stock=0, market_move=0)),
    "W1":  dict(label="w1: attention level + momentum + market, no sentiment", kalshi=True, poly=True, plats=PL, attn_level=True, smooth_act=True,
                tiers=False, quality=True, w=dict(attention_shift=.30, activity_shift=.10, money_flow=.15, money_stock=.10, market_move=.10, sentiment_shift=0, momentum=.25)),
    "W1q": dict(label="w1 without quality", kalshi=True, poly=True, plats=PL, attn_level=True, smooth_act=True,
                tiers=False, quality=False, w=dict(attention_shift=.30, activity_shift=.10, money_flow=.15, money_stock=.10, market_move=.10, sentiment_shift=0, momentum=.25)),
    "W1n": dict(label="w1, missing inputs count as median", kalshi=True, poly=True, plats=PL, attn_level=True, smooth_act=True, neutral=True,
                tiers=False, quality=False, w=dict(attention_shift=.30, activity_shift=.10, money_flow=.15, money_stock=.10, market_move=.10, sentiment_shift=0, momentum=.25)),
    "W1c": dict(label="w1 compact: attention level 0.4, momentum 0.4, flow 0.1, OI 0.1", kalshi=True, poly=True, plats=PL, attn_level=True,
                tiers=False, quality=True, w=dict(attention_shift=.40, activity_shift=0, money_flow=.10, money_stock=.10, market_move=0, sentiment_shift=0, momentum=.40)),
    "AL":  dict(label="attention level only", kalshi=True, poly=True, plats=PL, attn_level=True, tiers=False, quality=False,
                w={c: (1 if c == "attention_shift" else 0) for c in COMP}),
    "M":   dict(label="momentum only (benchmark)", kalshi=True, poly=True, plats=PL, tiers=False, quality=False,
                w={c: (1 if c == "momentum" else 0) for c in COMP}),
}
Q = dict(q_free=.05, q_slope=.5, q_floor=.6, q_zero_pen=.4, q_single=.9)
T = dict(t1_days=2, t1_pct=.7, t2_flow=.7, t2_attn=.5, t3_attn=.8)
MACRO = [dt.date(2026, 9, 11), dt.date(2026, 9, 16), dt.date(2026, 10, 14), dt.date(2026, 10, 28)]


def td_until(d, e):
    return int(np.busday_count(d, e)) if e >= d else None


def score_day(g, cfg):
    w = cfg.get("w", W0)
    rows = [combine(r, cfg) for r in g.itertuples()]
    c = pd.DataFrame(rows, index=g.index)
    gate = (~c.pm_evidence) | (c.zero > .8) | (c.spread > .3)
    live = c[~gate].copy()
    gl = g.loc[live.index]
    if len(live) < 5:
        return None
    pr = {k: pctrank(live[k]) for k in COMP}
    if cfg.get("neutral"):  # a missing component counts as the pool median (0.5) instead of being dropped
        num = sum(pr[k].fillna(0.5) * w[k] for k in COMP)
        den = pd.Series(sum(w.values()), index=live.index)
    else:
        num = sum(pr[k].fillna(0) * w[k] * live[k].notna() for k in COMP)
        den = sum(w[k] * live[k].notna() for k in COMP)
    raw = (num / den.replace(0, np.nan)).fillna(0)
    if cfg.get("quality"):
        sf = (1 - (live.spread - Q["q_free"]).clip(lower=0) / Q["q_slope"]).clip(Q["q_floor"], 1).fillna(1)
        zf = (1 - Q["q_zero_pen"] * live.zero).fillna(1)
        q = sf * zf * np.where(live.families >= 2, 1, Q["q_single"])
    else:
        q = 1
    score = raw * q
    key = score.copy()
    if cfg.get("tiers"):
        d = gl.date.iloc[0]
        cat = gl.asset_class.isin(["index", "rates", "fx"]) & any((td_until(d, e) is not None and td_until(d, e) <= T["t1_days"]) for e in MACRO)
        pm, pf, pa = pr["market_move"].fillna(0), pr["money_flow"].fillna(0), pr["attention_shift"].fillna(0)
        tier = np.where(cat & ((pm >= T["t1_pct"]) | (pf >= T["t1_pct"])), 1,
                        np.where((pf >= T["t2_flow"]) & (pa >= T["t2_attn"]), 2, np.where(pa >= T["t3_attn"], 3, 4)))
        key = (5 - tier) + score  # tier first, then score
    return pd.DataFrame({"topic": gl.topic, "score": score, "key": key, "label_move": gl.label_move, "label_attn": gl.label_attn})


def day_metrics(s, label):
    s = s.dropna(subset=[label])
    if len(s) < 5:
        return None
    lp = s[label].rank(pct=True)
    order = s.sort_values("key", ascending=False).index
    ic = s["key"].rank().corr(s[label].rank())
    return dict(ic=ic, top1=lp.loc[order[0]], top5=lp.loc[order[:5]].mean(), n=len(s))


def boot(x, n=4000):
    x = np.asarray([v for v in x if v == v])
    if len(x) < 3:
        return [np.nan, np.nan, np.nan]
    m = rng.choice(x, size=(n, len(x))).mean(1)
    return [float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def main():
    f = pd.read_parquet(F / "features.parquet")
    res = {"variants": {}, "components": {}, "meta": {}}
    days = sorted(f.date.unique())
    res["meta"] = dict(days=len(days), first=str(days[0]), last=str(days[-1]), topics=int(f.topic.nunique()),
                       discovery=[str(d) for d in days if d < SPLIT][::max(1, len(days))],
                       n_disc=sum(d < SPLIT for d in days), n_hold=sum(d >= SPLIT for d in days))
    per_day = {}
    for name, cfg in VARIANTS.items():
        out = {}
        for label in ("label_move", "label_attn"):
            rows = []
            for d, g in f.groupby("date"):
                s = score_day(g, cfg)
                if s is None:
                    continue
                m = day_metrics(s, label)
                if m:
                    rows.append(dict(date=d, **m))
            r = pd.DataFrame(rows)
            per_day[(name, label)] = r
            o = {}
            for part, sub in (("all", r), ("discovery", r[r.date < SPLIT]), ("holdout", r[r.date >= SPLIT])):
                o[part] = {k: boot(sub[k]) for k in ("ic", "top1", "top5")} | {"days": int(len(sub)), "pool": float(sub.n.mean()) if len(sub) else 0}
            out[label] = o
        res["variants"][name] = dict(label=cfg["label"], **out)
        print(name, cfg["label"], {lb: (round(out[lb]["all"]["ic"][0], 3), round(out[lb]["all"]["top5"][0], 3)) for lb in out})
    # paired differences vs V1 and vs M on top5 / ic
    pairs = {}
    for name in VARIANTS:
        for ref in ("V1", "M"):
            if name == ref:
                continue
            for label in ("label_move", "label_attn"):
                a, b = per_day[(name, label)], per_day[(ref, label)]
                j = a.merge(b, on="date", suffixes=("", "_r"))
                pairs[f"{name}-{ref}-{label}"] = {k: boot(j[k] - j[k + "_r"]) for k in ("ic", "top5")} | {
                    "holdout": {k: boot((j[k] - j[k + "_r"])[j.date >= SPLIT]) for k in ("ic", "top5")}}
    res["pairs"] = pairs
    # component ICs over every topic with a value (no gates), and per source
    cfg = VARIANTS["V1"]
    comp_rows = []
    for d, g in f.groupby("date"):
        c = pd.DataFrame([combine(r, cfg) for r in g.itertuples()], index=g.index)
        for extra in ["k_flow", "k_oi_chg", "k_move", "p_move", "k_vol"] + [f"ad_{m}_{p}" for m in ("buzz_d", "ment_chg") for p in PL] + \
                     [f"ad3_{m}_{p}" for m in ("buzz_d", "ment_chg") for p in PL] + ["ad_level_z"]:
            c[extra] = g[extra]
        for p in PL:
            c[f"ad_sent_abs_{p}"] = g[f"ad_sent_d_{p}"].abs()
        c["label_move"], c["label_attn"] = g.label_move, g.label_attn
        for col in [x for x in c.columns if x not in ("pm_evidence", "families", "label_move", "label_attn")]:
            for label in ("label_move", "label_attn"):
                s = c[[col, label]].dropna()
                if len(s) >= 8 and s[col].nunique() > 2:
                    comp_rows.append(dict(date=d, comp=col, label=label, ic=s[col].rank().corr(s[label].rank()), n=len(s)))
    cr = pd.DataFrame(comp_rows)
    for (comp, label), g in cr.groupby(["comp", "label"]):
        res["components"].setdefault(comp, {})[label] = dict(all=boot(g.ic), discovery=boot(g[g.date < SPLIT].ic), holdout=boot(g[g.date >= SPLIT].ic),
                                                             days=int(len(g)), n=float(g.n.mean()))
    # daily series for charts
    res["daily"] = {f"{n}|{lb}": per_day[(n, lb)][["date", "ic", "top5"]].assign(date=lambda x: x.date.astype(str)).round(4).to_dict("records")
                    for (n, lb) in per_day if n in ("V0", "V1", "W1", "W1c", "M")}
    (F / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print("components (all days, IC with label_move / label_attn):")
    for comp, v in sorted(res["components"].items()):
        print(f"  {comp:22s}", {lb: (round(x['all'][0], 3), round(x['all'][1], 3), round(x['all'][2], 3), round(x['n'])) for lb, x in v.items()})


if __name__ == "__main__":
    main()
