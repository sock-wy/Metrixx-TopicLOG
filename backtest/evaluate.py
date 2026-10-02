"""Metrics for one run, plus cross-run multiple-testing correction.

Per day, over the evaluated pool:
  IC            Spearman(demand_score, label)
  pick_pctl     percentile of the pick's label within the pool (0..1; random = 0.5)
  hit_top1      the pick had the largest label
  mom_*         same for the momentum benchmark (largest prev_move = biggest mover into the pick)
Aggregates: means, bootstrap 95% CI over days, permutation p-value of mean pick_pctl
against uniformly random picks, paired pick-vs-momentum difference.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scoring.scoring import COMPONENTS


def spearman(x, y):
    x, y = pd.Series(list(x), dtype=float), pd.Series(list(y), dtype=float)
    ok = x.notna() & y.notna()
    x, y = x[ok].rank(), y[ok].rank()
    if len(x) < 3 or x.nunique() < 2 or y.nunique() < 2:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def pctl(values, v):
    a = np.asarray(values, float)
    n = len(a)
    return (np.sum(a < v) + 0.5 * (np.sum(a == v) - 1)) / (n - 1) if n >= 2 else np.nan


def per_day(pools: pd.DataFrame) -> pd.DataFrame:
    out = []
    for t, g in pools.groupby("date"):
        g = g.sort_values("rank")
        y = g.label.values
        pick = g.iloc[0]
        mom = g.loc[g.prev_move.fillna(-1).idxmax()]
        rec = dict(date=t, n=len(g), pick=pick.ticker,
                   IC=spearman(g.demand_score, g.label),
                   pick_pctl=pctl(y, pick.label), hit_top1=float(pick.label == y.max()),
                   mom_pick=mom.ticker, mom_pctl=pctl(y, mom.label), mom_hit_top1=float(mom.label == y.max()),
                   rand_hit_top1=1 / len(g),
                   IC_crypto=spearman(*g.loc[g.asset_class == "crypto", ["demand_score", "label"]].values.T)
                   if (g.asset_class == "crypto").sum() >= 3 else np.nan)
        for k in COMPONENTS:
            rec[f"IC_{k}"] = spearman(g[f"pct_{k}"], g.label)
        out.append(rec)
    return pd.DataFrame(out)


def boot_ci(x, rng, n=5000):
    x = np.asarray(pd.Series(x).dropna(), float)
    if len(x) < 3:
        return [np.nan, np.nan]
    idx = rng.integers(0, len(x), (n, len(x)))
    m = x[idx].mean(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def perm_p_pick(d: pd.DataFrame, rng, n=20000):
    """P(mean percentile of uniformly random picks >= observed). One-sided."""
    obs = d.pick_pctl.mean()
    sims = np.zeros(n)
    for k in d.n:
        sims += rng.integers(0, k, n) / (k - 1)
    sims /= len(d)
    return float((sims >= obs - 1e-12).mean())


def perm_p_ic(pools: pd.DataFrame, rng, n=5000):
    """P(mean daily IC under within-day random ordering >= observed). One-sided."""
    obs, sims, k = [], np.zeros(n), 0
    for _, g in pools.groupby("date"):
        if len(g) < 3:
            continue
        y = g.label.rank().values
        x = g.demand_score.rank().values
        if np.std(x) == 0 or np.std(y) == 0:
            continue
        obs.append(np.corrcoef(x, y)[0, 1])
        perm = np.argsort(rng.random((n, len(x))), axis=1)
        xs = x[perm]
        xs = (xs - xs.mean(1, keepdims=True)) / xs.std(1, keepdims=True)
        yz = (y - y.mean()) / y.std()
        sims += (xs * yz).mean(1)
        k += 1
    if not k:
        return np.nan, np.nan
    null = sims / k
    return float((null >= np.mean(obs) - 1e-12).mean()), float(null.std())


def tstat(x):
    x = pd.Series(x).dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std() > 0 else np.nan


def summarize(days: pd.DataFrame, pools: pd.DataFrame, rng) -> dict:
    d = per_day(pools)
    d["weekend"] = [pd.Timestamp(t).weekday() >= 5 for t in d.date]
    diff = d.pick_pctl - d.mom_pctl
    s = dict(
        days=int(len(d)), avg_pool=round(float(d.n.mean()), 2),
        IC_mean=round(float(d.IC.mean()), 4), IC_t=round(tstat(d.IC), 2),
        IC_ci95=[round(v, 4) for v in boot_ci(d.IC, rng)],
        **dict(zip(["IC_p_value", "IC_null_sd"], [round(v, 4) for v in perm_p_ic(pools, rng)])),
        pick_pctl=round(float(d.pick_pctl.mean()), 4),
        pick_pctl_ci95=[round(v, 4) for v in boot_ci(d.pick_pctl, rng)],
        p_value_vs_random=round(perm_p_pick(d, rng), 4),
        hit_top1=round(float(d.hit_top1.mean()), 4), random_hit_top1=round(float(d.rand_hit_top1.mean()), 4),
        momentum_pctl=round(float(d.mom_pctl.mean()), 4), momentum_hit_top1=round(float(d.mom_hit_top1.mean()), 4),
        pick_minus_momentum=round(float(diff.mean()), 4),
        pick_minus_momentum_ci95=[round(v, 4) for v in boot_ci(diff, rng)],
        IC_crypto_only=round(float(d.IC_crypto.mean()), 4) if d.IC_crypto.notna().any() else None,
        IC_weekday=round(float(d.loc[~d.weekend, "IC"].mean()), 4) if (~d.weekend).any() else None,
        IC_weekend=round(float(d.loc[d.weekend, "IC"].mean()), 4) if d.weekend.any() else None,
        component_IC={k: dict(mean=round(float(d[f"IC_{k}"].mean()), 4) if d[f"IC_{k}"].notna().any() else None,
                              t=round(tstat(d[f"IC_{k}"]), 2) if d[f"IC_{k}"].notna().sum() > 2 else None,
                              days=int(d[f"IC_{k}"].notna().sum())) for k in COMPONENTS},
        picks_by_ticker=days.pick.value_counts().to_dict() if len(days) else {},
        picks_by_tier=days.pick_tier.value_counts().to_dict() if len(days) else {},
    )
    return s, d


def holm(pvals: dict) -> dict:
    """Holm-Bonferroni adjusted p-values for a family of tests."""
    items = sorted((p, k) for k, p in pvals.items() if p is not None and not np.isnan(p))
    m, out, running = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = round(running, 4)
    return out
