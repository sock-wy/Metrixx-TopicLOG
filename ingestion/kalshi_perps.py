"""Kalshi perpetual futures ("perps") public market data. No API key needed.

The perps API is separate from the event-contract API in `kalshi.py`:
    base  https://external-api.kalshi.com/trade-api/v2/margin

Endpoints used:
  /markets                                  every perp market (price, volume_24h, open_interest, ...)
  /funding_rates/historical?ticker=&start_ts=&end_ts=
                                            settled funding rates, newest first
  /markets/{ticker}/candlesticks?period_interval=1|60|1440
                                            candles with end-of-period open_interest

Funding schedule (Kalshi help centre): crypto settles three times a day (00:00, 08:00,
16:00 ET); metals once a day (10:00 ET). Rates inside the deadband are paid as 0, so a
quiet market shows long runs of exact zeros.

Raw responses are stored whole under ingestion/data/raw/kalshi_perps/ (git-ignored).
"""
from __future__ import annotations

import datetime as dt

from ingestion.common import RAW, UTC, cache_json, http_get

BASE = "https://external-api.kalshi.com/trade-api/v2/margin"
DIR = RAW / "kalshi_perps"


def _stamp(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%d/%H%M%S")


def markets(save: bool = True):
    """Every perp market with its live stats. One call."""
    status, body, _ = http_get(f"{BASE}/markets")
    if status != 200 or not body:
        raise RuntimeError(f"perps /markets: HTTP {status} {body}")
    ms = body.get("markets") or []
    if save:
        now = dt.datetime.now(UTC)
        cache_json(DIR / "markets" / f"{_stamp(now)}.json", {"pulled_at": now.isoformat(), "markets": ms})
    return ms


def funding_history(ticker: str, start: dt.datetime, end: dt.datetime, save: bool = True):
    """Settled funding rates for one perp in [start, end], oldest first.

    Each row: market_ticker, funding_time (ISO, UTC), funding_rate (fraction per period), mark_price.
    """
    status, body, _ = http_get(f"{BASE}/funding_rates/historical",
                               params={"ticker": ticker, "start_ts": int(start.timestamp()),
                                       "end_ts": int(end.timestamp())}, pause=0.2)
    if status != 200 or body is None:
        raise RuntimeError(f"{ticker} funding: HTTP {status} {body}")
    rows = sorted(body.get("funding_rates") or [], key=lambda r: r["funding_time"])
    if save:
        now = dt.datetime.now(UTC)
        cache_json(DIR / "funding" / ticker / f"{_stamp(now)}.json",
                   {"pulled_at": now.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                    "funding_rates": rows})
    return rows


def candles(ticker: str, start: dt.datetime, end: dt.datetime, period_minutes: int = 60, save: bool = True):
    """Candles for one perp (1, 60 or 1440 minutes), oldest first. Each has end_period_ts and open_interest."""
    status, body, _ = http_get(f"{BASE}/markets/{ticker}/candlesticks",
                               params={"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()),
                                       "period_interval": period_minutes}, pause=0.2)
    if status != 200 or body is None:
        raise RuntimeError(f"{ticker} candles: HTTP {status} {body}")
    cs = sorted(body.get("candlesticks") or [], key=lambda c: c["end_period_ts"])
    if save:
        now = dt.datetime.now(UTC)
        cache_json(DIR / "candles" / ticker / f"{_stamp(now)}_{period_minutes}m.json",
                   {"pulled_at": now.isoformat(), "candlesticks": cs})
    return cs
