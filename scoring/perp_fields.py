"""Kalshi perps columns for 2_topic_log: perp_funding_rate, perp_funding_z, perp_oi_chg_pct.

Definitions live in config/perps.yaml. The math is in pure functions (`from_data`) so it can be
tested without the network; `compute` fetches the data and calls them.

No look-ahead: every input is dated at or before `asof`, and each result records the newest
timestamp it used (`perp_asof_funding`, `perp_asof_oi`).
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

import yaml

FIELDS = ["perp_funding_rate", "perp_funding_z", "perp_oi_chg_pct"]


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def funding_fields(rows, asof: dt.datetime, window_days=30, min_settlements=15, clip=5.0):
    """rows: funding settlements (any order). Returns (rate, z, latest_time_used)."""
    past = sorted((r for r in rows if _ts(r["funding_time"]) <= asof), key=lambda r: r["funding_time"])
    if not past:
        return None, None, None
    last = past[-1]
    rate = float(last["funding_rate"])
    t_last = _ts(last["funding_time"])
    lo = t_last - dt.timedelta(days=window_days)
    hist = [float(r["funding_rate"]) for r in past[:-1] if _ts(r["funding_time"]) >= lo]
    z = None
    if len(hist) >= min_settlements:
        sd = statistics.pstdev(hist)
        if sd > 0:
            z = max(-clip, min(clip, (rate - statistics.fmean(hist)) / sd))
    return rate, z, t_last


def oi_change(candles, asof: dt.datetime, lookback_hours=24):
    """candles: hourly, each with end_period_ts and open_interest. Returns (pct_change, latest_time_used)."""
    by_end = {int(c["end_period_ts"]): c for c in candles}
    closed = sorted(t for t in by_end if t <= asof.timestamp())
    if not closed:
        return None, None
    t1 = closed[-1]
    t0 = t1 - lookback_hours * 3600
    if t0 not in by_end:
        return None, None
    oi1, oi0 = (float(by_end[t]["open_interest"] or 0) for t in (t1, t0))
    if oi0 <= 0 or oi1 <= 0:
        return None, None
    return oi1 / oi0 - 1.0, dt.datetime.fromtimestamp(t1, dt.timezone.utc)


def from_data(funding_rows, hourly_candles, asof, cfg):
    f = cfg["fields"]
    rate, z, t_f = funding_fields(funding_rows, asof, f["perp_funding_z"]["window_days"],
                                  f["perp_funding_z"]["min_settlements"], f["perp_funding_z"]["clip"])
    oi, t_o = oi_change(hourly_candles, asof, f["perp_oi_chg_pct"]["lookback_hours"])
    out = {"perp_funding_rate": rate, "perp_funding_z": z, "perp_oi_chg_pct": oi,
           "perp_asof_funding": t_f.isoformat() if t_f else None,
           "perp_asof_oi": t_o.isoformat() if t_o else None}
    for k in FIELDS:
        v = out[k]
        if v is not None and not math.isfinite(v):
            out[k] = None
    return out


def compute(ticker: str, asof: dt.datetime, cfg, fetch=None):
    """Perp columns for one Topic Log ticker as of `asof` (aware UTC). Blank dict if unmapped."""
    perp = (cfg.get("map") or {}).get(ticker)
    blank = {k: None for k in FIELDS} | {"perp_ticker": perp, "perp_asof_funding": None, "perp_asof_oi": None}
    if not perp:
        return blank
    if fetch is None:
        from ingestion import kalshi_perps as fetch
    days = cfg["fields"]["perp_funding_z"]["window_days"] + 3
    rows = fetch.funding_history(perp, asof - dt.timedelta(days=days), asof)
    hrs = cfg["fields"]["perp_oi_chg_pct"]["lookback_hours"] + 4
    cs = fetch.candles(perp, asof - dt.timedelta(hours=hrs), asof, period_minutes=60)
    out = from_data(rows, cs, asof, cfg)
    out["perp_ticker"] = perp
    return out
