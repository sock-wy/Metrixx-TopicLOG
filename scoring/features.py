"""Snapshot tables -> one feature row per (pick day, ticker), as of the pick time.

This is the bridge between `1_market_snapshots` (raw, 4 pulls a day) and the
inputs `scoring.scoring.score_day` expects. Every row carries `feature_asof_ts`,
the latest timestamp of any data it used; callers assert it is not after the pick.

Field mapping to the playbook (chapter 4):
  attention_shift  <- buzz_delta_1d              Adanos buzz_score, day t-1 minus day t-2
  activity_shift   <- trade_count_pct_change_1d  Adanos `mentions` % change, t-1 vs t-2
                                                 (Reddit has no trade count; mentions is its activity measure)
  sentiment_shift  <- sentiment_delta_1d         Adanos sentiment_score, t-1 minus t-2
  money_flow       <- mkt_volume_delta_1d        whole-ladder cumulative volume at the pick snapshot, % vs previous event
  money_stock      <- mkt_oi_delta_1d            whole-ladder open interest at the pick snapshot, % vs previous event
  market_move      <- mkt_prob_delta_1d, mkt_prob_range_1d
                                                 mid of the strike nearest 50% at the event's first snapshot,
                                                 tracked over the snapshots up to the pick
  avg_spread, zero_trade_market_pct              strikes within +/- atm_band of the implied median
Only tickers with a live Kalshi ladder at the pick are candidates (indices drop out on
weekends and holidays). Adanos uses complete UTC days only: day t is still open at 15:00 ET, so the newest
usable day is t-1.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from ingestion.common import UTC, et

DEFAULTS = dict(
    pick_hour_et=15,
    first_snapshot=(-1, 21),        # (day offset, hour ET) of the first snapshot of an event
    atm_band=0.02,
    liquidity_strikes=None,         # if set: measure liquidity on the N strikes nearest the implied median instead of the band
    volume_floor_pct=10,            # None disables the floor
    floor_window=30,
    floor_min_obs=10,
    use_adanos=True,
)


def _none(x):
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
    except TypeError:
        pass
    return x


def load_snapshots(folder):
    def rd(name, ts_cols=(), date_cols=()):
        df = pd.read_csv(f"{folder}/{name}.csv.gz")
        for c in ts_cols:
            df[c] = pd.to_datetime(df[c], utc=True)
        for c in date_cols:
            df[c] = pd.to_datetime(df[c]).dt.date
        return df
    return dict(
        strikes=rd("ladder_strikes", ["snapshot_ts"], ["event_date"]),
        totals=rd("ladder_totals", ["snapshot_ts"], ["event_date"]),
        prices=rd("prices", (), ["date"]),
        vol_scale=rd("vol_scale", (), ["date"]),
        adanos=rd("adanos_daily", (), ["date"]),
    )


def _mid(b, a):
    if b is None or a is None or (isinstance(b, float) and math.isnan(b)) or (isinstance(a, float) and math.isnan(a)):
        return None
    if a < b or a <= 0:
        return None
    return (a + b) / 2


def build_features(snap, pick_days, tickers, params=None):
    p = {**DEFAULTS, **(params or {})}
    totals, strikes, ad = snap["totals"], snap["strikes"], snap["adanos"]
    pick_h = p["pick_hour_et"]

    # pick-snapshot totals per (ticker, event_date): the event that is live at the pick time
    tot = totals.copy()
    tot["is_pick_snap"] = [ts == pd.Timestamp(et(d, pick_h)) for ts, d in zip(tot.snapshot_ts, tot.event_date)]
    pick_tot = tot[tot.is_pick_snap].set_index(["ticker", "event_date"]).sort_index()

    strikes_by = {k: g for k, g in strikes.groupby(["ticker", "event_date"])}
    ad_by = {k: g.set_index("date") for k, g in ad.groupby("ticker")}

    rows = []
    for tk in tickers:
        ev_dates = sorted(d for (t, d) in pick_tot.index if t == tk)
        vols = {d: pick_tot.loc[(tk, d), "total_cum_volume"] for d in ev_dates}
        ois = {d: pick_tot.loc[(tk, d), "total_open_interest"] for d in ev_dates}
        for t in pick_days:
            pick_ts = et(t, pick_h)
            r = dict(date=t, ticker=tk, pick_ts=pick_ts.isoformat())
            asof = []
            # ---- Kalshi ------------------------------------------------------------
            if t in vols:
                prev = [d for d in ev_dates if d < t]
                prev_d = prev[-1] if prev else None
                v, o = vols[t], ois[t]
                r["mkt_volume_24h"], r["mkt_open_interest"] = v, o
                r["prev_event_date"] = prev_d
                if prev_d is not None and (t - prev_d).days <= 4:
                    vp, op = vols[prev_d], ois[prev_d]
                    r["mkt_volume_delta_1d"] = (v / vp - 1) * 100 if vp > 0 else None
                    r["mkt_oi_delta_1d"] = (o / op - 1) * 100 if op > 0 else None
                    # volume floor: previous volume below its own trailing percentile -> drop money_flow
                    hist = [vols[d] for d in prev][-p["floor_window"]:]
                    r["volume_floor"] = None
                    if p["volume_floor_pct"] is not None and len(hist) >= p["floor_min_obs"]:
                        floor = float(np.percentile(hist, p["volume_floor_pct"]))
                        r["volume_floor"] = floor
                        if vp < floor:
                            r["mkt_volume_delta_1d"] = None
                            r["money_flow_floored"] = True
                r["mkt_ladder_depth"] = int(pick_tot.loc[(tk, t), "n_strikes"])
                # G2 (playbook): at least one open contract with volume -> anywhere on the ladder
                r["has_market_evidence"] = int(pick_tot.loc[(tk, t), "n_strikes_traded"]) > 0
                s = strikes_by.get((tk, t))
                if s is not None:
                    first_ts = pd.Timestamp(et(t + dt.timedelta(days=p["first_snapshot"][0]), p["first_snapshot"][1]))
                    snaps = sorted(ts for ts in s.snapshot_ts.unique() if ts <= pd.Timestamp(pick_ts))
                    # market_move: strike nearest 50% at the first snapshot, followed through the snapshots
                    s0 = s[s.snapshot_ts == (first_ts if first_ts in snaps else (snaps[0] if snaps else None))]
                    k0 = None
                    if len(s0):
                        m0 = [(_mid(b, a), k) for b, a, k in zip(s0.yes_bid, s0.yes_ask, s0.strike)]
                        m0 = [x for x in m0 if x[0] is not None]
                        if m0:
                            k0 = min(m0, key=lambda x: abs(x[0] - 0.5))[1]
                    if k0 is not None:
                        path = []
                        for ts in snaps:
                            row = s[(s.snapshot_ts == ts) & (s.strike == k0)]
                            if len(row):
                                m = _mid(row.yes_bid.iloc[0], row.yes_ask.iloc[0])
                                if m is not None:
                                    path.append(m)
                        if len(path) >= 2:
                            r["mkt_prob_delta_1d"] = path[-1] - path[0]
                            r["mkt_prob_range_1d"] = max(path) - min(path)
                            r["atm_strike_tracked"] = k0
                            r["n_prob_points"] = len(path)
                    # liquidity in the ATM band at the pick snapshot
                    sp = s[s.snapshot_ts == pd.Timestamp(pick_ts)]
                    center = pick_tot.loc[(tk, t), "implied_median"]
                    if len(sp) and pd.notna(center):
                        if p["liquidity_strikes"]:
                            band = sp.loc[(sp.strike - center).abs().sort_values(kind="stable").index[:p["liquidity_strikes"]]]
                        else:
                            band = sp[(sp.strike / center - 1).abs() <= p["atm_band"]]
                        traded = band[band.cum_volume > 0]
                        spreads = [a - b for b, a in zip(traded.yes_bid, traded.yes_ask)
                                   if pd.notna(b) and pd.notna(a) and a >= b and a > 0]
                        r["band_strikes"] = len(band)
                        r["band_traded"] = len(traded)
                        r["zero_trade_market_pct"] = 1 - len(traded) / len(band) if len(band) else None
                        r["avg_spread"] = float(np.mean(spreads)) if spreads else None
                        asof.append(int(sp.last_candle_ts.max()))
                asof.append(int(pick_ts.timestamp()))  # totals snapshot itself
            else:
                r["has_market_evidence"] = False
            # ---- Adanos (complete UTC days only) -----------------------------------
            if p["use_adanos"] and tk in ad_by:
                a = ad_by[tk]
                d1, d2 = t - dt.timedelta(days=1), t - dt.timedelta(days=2)
                if d1 in a.index and d2 in a.index:
                    x1, x2 = a.loc[d1], a.loc[d2]
                    r["buzz_score"] = x1.buzz_score
                    r["buzz_delta_1d"] = x1.buzz_score - x2.buzz_score
                    r["trade_count_pct_change_1d"] = (x1.mentions / x2.mentions - 1) * 100 if x2.mentions > 0 else None
                    r["sentiment_delta_1d"] = (x1.sentiment_score - x2.sentiment_score
                                               if pd.notna(x1.sentiment_score) and pd.notna(x2.sentiment_score) else None)
                    r["mentions"] = x1.mentions
                    # day d1 is complete at 00:00 UTC of day t
                    asof.append(int(dt.datetime(t.year, t.month, t.day, tzinfo=UTC).timestamp()))
            adanos_ok = any(_none(r.get(k)) is not None for k in ("buzz_delta_1d", "trade_count_pct_change_1d", "sentiment_delta_1d"))
            kalshi_ok = t in vols
            r["sources_available"] = int(kalshi_ok) + int(adanos_ok)
            r["feature_asof_ts"] = dt.datetime.fromtimestamp(max(asof), UTC).isoformat() if asof else None
            if kalshi_ok:  # no ladder that day (e.g. index on a weekend/holiday) -> not a candidate
                rows.append(r)
    df = pd.DataFrame(rows)
    # look-ahead guard: nothing used may be newer than the pick
    bad = df[pd.to_datetime(df.feature_asof_ts) > pd.to_datetime(df.pick_ts)]
    if len(bad):
        raise AssertionError(f"look-ahead in {len(bad)} feature rows, e.g. {bad.iloc[0].to_dict()}")
    return df
