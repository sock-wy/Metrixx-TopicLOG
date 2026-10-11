"""Study `topic_stocks` — Kalshi subset build.

Series mapping: backtest/universes/topic_stocks_kalshi.csv (series -> stock ticker, built from the
2026-10-11 scan of every Kalshi Financials series, with manual fixes to the name search).

Output backtest/snapshots/topic_stocks/kalshi_state.csv.gz: one row per (market, calendar day) while
the market is open at 15:00 ET that day, with its state at 15:00 ET built only from candles that
closed by then:
    mid_now, mid_24h_ago        last quoted (yes_bid+yes_ask)/2 at or before T and T-24h
    vol_24h                     contracts traded in (T-24h, T]
Company markets: only markets that ever traded (volume > 0). S&P 500 / Nasdaq-100: the daily 16:00 ET
above/below ladder of day t, every strike.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import pandas as pd

from ingestion import kalshi
from ingestion.common import UTC, et, fmt_event

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAP = ROOT / "backtest" / "universes" / "topic_stocks_kalshi.csv"
SNAP = ROOT / "backtest" / "snapshots" / "topic_stocks"
START, END = dt.date(2026, 7, 14), dt.date(2026, 10, 8)
LADDERS = {"SPY": ("KXINXU", "KXINXU-{yy}{MON}{dd}H1600"), "QQQ": ("KXNASDAQ100U", "KXNASDAQ100U-{yy}{MON}{dd}H1600")}


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def _quote(c):
    b = _f((c.get("yes_bid") or {}).get("close_dollars") or (c.get("yes_bid") or {}).get("close"))
    a = _f((c.get("yes_ask") or {}).get("close_dollars") or (c.get("yes_ask") or {}).get("close"))
    if b is None or a is None or a < b or a <= 0:
        return None
    return (a + b) / 2


def _vol(c):
    return _f(c.get("volume_fp")) or _f(c.get("volume")) or 0.0


def states(candles, days, open_t=None, close_t=None):
    """Market state at 15:00 ET for each day in `days` while open."""
    cs = sorted(candles, key=lambda c: c["end_period_ts"])
    out = []
    for d in days:
        T = et(d, 15)
        if open_t and T < open_t or close_t and T >= close_t:
            continue
        t1, t0 = T.timestamp(), (T - dt.timedelta(hours=24)).timestamp()
        mid_now = mid_prev = None
        vol = 0.0
        last_ts = None
        for c in cs:
            e = c["end_period_ts"]
            if e > t1:
                break
            q = _quote(c)
            if q is not None:
                mid_now = q
                if e <= t0:
                    mid_prev = q
            if e > t0:
                vol += _vol(c)
            last_ts = e
        out.append(dict(date=d, mid_now=mid_now, mid_24h_ago=mid_prev, vol_24h=vol, last_candle_ts=last_ts))
    return out


def build(universe):
    days = [START + dt.timedelta(days=i) for i in range((END - START).days + 1)]
    mp = pd.read_csv(MAP)
    mp = mp[mp.ticker.isin(universe)]
    since = int(dt.datetime(START.year, START.month, START.day, tzinfo=UTC).timestamp())
    rows, mkts = [], []
    for j, (series, ticker) in enumerate(mp[["series", "ticker"]].itertuples(index=False)):
        for hist in (False, True):
            for m in kalshi.series_markets(series, since, historical=hist):
                if (_f(m.get("volume_fp")) or _f(m.get("volume")) or 0) <= 0:
                    continue
                o, c = _ts(m.get("open_time")), _ts(m.get("close_time"))
                if not o or o >= et(END, 15):
                    continue
                w0 = max(o, et(START - dt.timedelta(days=2), 0))
                w1 = min(c or et(END, 16), et(END, 16))
                if w1 <= w0:
                    continue
                cs = kalshi.market_candles(m["ticker"], w0, w1, historical=hist, series=series)
                mkts.append(dict(ticker=ticker, series=series, event=m.get("event_ticker"), market=m["ticker"],
                                 title=m.get("title"), open_time=m.get("open_time"), close_time=m.get("close_time"),
                                 volume_life=_f(m.get("volume_fp")) or _f(m.get("volume")), historical=hist,
                                 n_candles=len(cs)))
                for s in states(cs, days, o, c):
                    rows.append(dict(ticker=ticker, kind="event", series=series, event=m.get("event_ticker"),
                                     market=m["ticker"], strike=None, **s))
        print(j, series, ticker, len(rows), flush=True)
    for ticker, (series, pat) in LADDERS.items():
        if ticker not in universe:
            continue
        for d in days:
            if d.weekday() >= 5:
                continue
            ev = fmt_event(pat, d)
            data = kalshi.event_candles(series, ev, et(d - dt.timedelta(days=1), 12), et(d, 18))
            if not data:
                continue
            for mt, cs in zip(data["market_tickers"], data["market_candlesticks"]):
                k = float(mt.rsplit("-", 1)[1].lstrip("TB"))
                for s in states(cs, [d]):
                    rows.append(dict(ticker=ticker, kind="ladder", series=series, event=ev, market=mt, strike=k, **s))
        print("ladder", ticker, len(rows), flush=True)
    SNAP.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(SNAP / "kalshi_state.csv.gz", index=False)
    pd.DataFrame(mkts).to_csv(SNAP / "kalshi_markets.csv", index=False)
    print("kalshi state rows", len(rows), "markets", len(mkts))
