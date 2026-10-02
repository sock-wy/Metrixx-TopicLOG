"""Labels: how newsworthy was each ticker after the pick?

Return window: 15:00 ET on pick day t -> 15:00 ET on the ticker's next session
(next calendar day for crypto, next trading day for indices), from Kalshi
settlement values of the 15:00 hourly event. Everything in the window happens
after the pick.

    abn_move   = |r_fwd| / sigma_20

sigma_20 uses Yahoo daily log returns dated strictly before t
(rolling, never the full sample). `prev_move` is the same measure for the period
that ended at the pick (known at the pick) and drives the momentum benchmark.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

MAX_GAP_DAYS = 4


def _fwd_back(prices: pd.DataFrame):
    out = {}
    for tk, g in prices.groupby("ticker"):
        s = g.set_index("date")["price_1500_et"].sort_index()
        dates = list(s.index)
        for i, d in enumerate(dates):
            nxt = dates[i + 1] if i + 1 < len(dates) else None
            prv = dates[i - 1] if i > 0 else None
            r_f = np.log(s[nxt] / s[d]) if nxt and (nxt - d).days <= MAX_GAP_DAYS else np.nan
            r_b = np.log(s[d] / s[prv]) if prv and (d - prv).days <= MAX_GAP_DAYS else np.nan
            out[(tk, d)] = (r_f, r_b, nxt)
    return out


def _yahoo_returns(vol_scale: pd.DataFrame):
    rets = {}
    for tk, g in vol_scale.groupby("ticker"):
        s = g.set_index("date")["close"].sort_index()
        rets[tk] = np.log(s).diff().dropna()
    return rets


def build_labels(prices, vol_scale, pick_days, tickers, vol_window=20):
    fb = _fwd_back(prices)
    yr = _yahoo_returns(vol_scale)
    rows = []
    for t in pick_days:
        for tk in tickers:
            if (tk, t) not in fb:
                continue
            r_f, r_b, nxt = fb[(tk, t)]
            hist = yr[tk][yr[tk].index < t]
            sig = hist.iloc[-vol_window:].std(ddof=1) if len(hist) >= vol_window else np.nan
            row = dict(date=t, ticker=tk, next_date=nxt, r_fwd=r_f, r_prev=r_b, sigma20=sig,
                       abn_move=abs(r_f) / sig if sig and sig > 0 else np.nan,
                       prev_move=abs(r_b) / sig if sig and sig > 0 else np.nan)
            rows.append(row)
    return pd.DataFrame(rows)

