"""Daily selection simulation.

For each pick day t (15:00 ET by default):
  1. take the feature rows built as of the pick (scoring.features),
  2. add days_since_covered from this simulation's own earlier picks (G4 / cooldown)
     and the catalyst distance (tier T1),
  3. score the pool with scoring.scoring.score_day (gates -> percentiles -> score -> tier),
  4. record the pool, gated rows, the pick and the post-pick label of every survivor.
Sanity modes replace the score (random / oracle) or permute labels, to prove the
harness itself is unbiased.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from scoring.features import _none
from scoring.scoring import COMPONENTS, score_day

INPUT_KEYS = [
    "buzz_delta_1d", "trade_count_pct_change_1d", "mkt_volume_delta_1d", "mkt_oi_delta_1d",
    "mkt_prob_delta_1d", "mkt_prob_range_1d", "sentiment_delta_1d", "avg_spread",
    "zero_trade_market_pct", "sources_available", "has_market_evidence", "mkt_ladder_depth",
]


def trading_days_between(a, b, cal_days):
    return sum(1 for d in cal_days if a < d <= b)


def catalyst_distance(t, ticker_class, cats, nyse_days):
    """Trading days from pick day t to the next applicable catalyst (0 = same day), or None."""
    best = None
    for c in cats["events"]:
        if ticker_class not in cats["applies_to"] or c["date"] < t:
            continue
        n = trading_days_between(t, c["date"], nyse_days)
        if best is None or n < best:
            best = n
    return best


def run(features, labels, cfg, weights, study, universe, cats, rng):
    label_col = study.get("label", "abn_move")
    mode = study.get("mode", "normal")
    use_tiers = study.get("tiers", True)
    use_cooldown = study.get("cooldown", True)
    classes = {tk: s["asset_class"] for tk, s in universe["tickers"].items()}
    nyse_days = sorted(set(features.loc[features.ticker.map(classes) == "index", "date"]))
    lab = labels.set_index(["date", "ticker"])
    last_pick = {}
    days, pools, skipped = [], [], []
    for t in sorted(features.date.unique()):
        f_t = features[features.date == t]
        rows = []
        for r in f_t.to_dict("records"):
            x = {k: _none(r.get(k)) for k in INPUT_KEYS}
            x["ticker"] = r["ticker"]
            hme = r.get("has_market_evidence")
            x["has_market_evidence"] = bool(hme) if hme is not None and hme == hme else False
            lp = last_pick.get(r["ticker"]) if use_cooldown else None
            x["days_since_covered"] = (t - lp).days if lp else None
            x["catalyst_in_trading_days"] = catalyst_distance(t, classes[r["ticker"]], cats, nyse_days)
            rows.append(x)
        live, gated = score_day(rows, cfg, weights=weights, use_tiers=use_tiers)
        if not live:
            continue
        # labels; the system's pick is live[0]. If it has no label the day is skipped
        # (never replaced by the next name, which would bias the pick toward labelled names)
        y = {}
        for r in live:
            v = lab[label_col].get((t, r["ticker"]), np.nan)
            if pd.notna(v):
                y[r["ticker"]] = float(v)
        if mode == "normal":
            last_pick[live[0]["ticker"]] = t
            if live[0]["ticker"] not in y:
                skipped.append(dict(date=t, pick=live[0]["ticker"], reason="pick has no label"))
                continue
        live = [r for r in live if r["ticker"] in y]
        if len(live) < 2:
            skipped.append(dict(date=t, pick=live[0]["ticker"] if live else None, reason="pool < 2 after labels"))
            continue
        if mode == "placebo_random":
            for r in live:
                r["demand_score"] = float(rng.random())
        elif mode == "oracle":
            for r in live:
                r["demand_score"] = y[r["ticker"]]
        elif mode == "placebo_shuffle":
            vals = list(y.values())
            rng.shuffle(vals)
            y = dict(zip(y.keys(), vals))
        if mode != "normal":  # sanity modes rank on the substituted score only
            live.sort(key=lambda r: -r["demand_score"])
        pick = live[0]
        if mode != "normal":
            last_pick[pick["ticker"]] = t
        prev = {r["ticker"]: lab["prev_move"].get((t, r["ticker"]), np.nan) for r in live}
        days.append(dict(date=t, pick=pick["ticker"], pick_tier=pick["tier"],
                         pick_score=pick["demand_score"], pool_size=len(live),
                         pool=" ".join(r["ticker"] for r in live),
                         gated=" ".join(f"{g['ticker']}:{g['data_quality_flag']}" for g in gated),
                         n_gated=len(gated), weekday=t.weekday()))
        for rank, r in enumerate(live, 1):
            pools.append(dict(
                date=t, ticker=r["ticker"], asset_class=classes[r["ticker"]], rank=rank,
                tier=r["tier"], demand_score=r["demand_score"], raw_score=r["raw_score"],
                quality=r["quality"], cooldown=r["cooldown"], label=y[r["ticker"]],
                prev_move=prev[r["ticker"]],
                **{f"pct_{k}": r["pct"][k] for k in COMPONENTS},
            ))
    return pd.DataFrame(days), pd.DataFrame(pools), pd.DataFrame(skipped)
