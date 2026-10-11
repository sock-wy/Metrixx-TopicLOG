"""Daily closes from Yahoo Finance's chart endpoint (no key).

Used only to scale backtest labels by each ticker's trailing volatility; the
labels themselves use Kalshi settlement prices.
"""
from __future__ import annotations

import datetime as dt
import json

from ingestion.common import RAW, UTC, cache_json, http_get

DIR = RAW / "yahoo"
URL = "https://query2.finance.yahoo.com/v8/finance/chart/{}"


def daily(symbol: str, rng: str = "2y", refresh: bool = False):
    """[(date, close), ...] using adjusted closes, dates in the exchange's local time."""
    path = DIR / f"{symbol.replace('^', '_')}_{rng}.json"
    if not path.exists() or refresh:
        status, body, _ = http_get(URL.format(symbol), params={"range": rng, "interval": "1d"},
                                   headers={"User-Agent": "Mozilla/5.0"}, pause=1.0)
        if status != 200:
            raise RuntimeError(f"{symbol}: HTTP {status}")
        body["_pulled_at"] = dt.datetime.now(UTC).isoformat()
        cache_json(path, body)
    body = json.loads(path.read_text())
    res = body["chart"]["result"][0]
    off = res["meta"]["gmtoffset"]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") \
        or res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(res["timestamp"], adj):
        if c is not None:
            out.append((dt.datetime.fromtimestamp(t + off, UTC).date(), float(c)))
    return out


def chart(symbol: str, rng: str, interval: str, refresh: bool = False):
    """Raw chart response (cached). Returns (meta, rows) with rows as dicts of ts/open/high/low/close/volume."""
    path = DIR / f"{symbol.replace('^', '_')}_{rng}_{interval}.json"
    if not path.exists() or refresh:
        status, body, _ = http_get(URL.format(symbol), params={"range": rng, "interval": interval},
                                   headers={"User-Agent": "Mozilla/5.0"}, pause=1.0)
        cache_json(path, {"status": status, "body": body, "_pulled_at": dt.datetime.now(UTC).isoformat()})
    blob = json.loads(path.read_text())
    body = blob.get("body") or {}
    if blob.get("status") != 200 or not (body.get("chart") or {}).get("result"):
        return None, []
    res = body["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(res.get("timestamp") or []):
        if q["close"][i] is None:
            continue
        rows.append(dict(ts=t, open=q["open"][i], high=q["high"][i], low=q["low"][i], close=q["close"][i],
                         volume=q["volume"][i]))
    return res["meta"], rows


def daily_ohlc(symbol: str, rng: str = "1y"):
    """[(date, open, high, low, close, volume)] in exchange-local dates, unadjusted OHLC."""
    meta, rows = chart(symbol, rng, "1d")
    if meta is None:
        return None, []
    off = meta["gmtoffset"]
    out = [(dt.datetime.fromtimestamp(r["ts"] + off, UTC).date(), r["open"], r["high"], r["low"], r["close"],
            r["volume"]) for r in rows]
    return meta, out


def hourly(symbol: str, rng: str = "6mo"):
    """Hourly bars: [(bar_start_utc, open, high, low, close, volume)]."""
    meta, rows = chart(symbol, rng, "60m")
    if meta is None:
        return None, []
    return meta, [(dt.datetime.fromtimestamp(r["ts"], UTC), r["open"], r["high"], r["low"], r["close"], r["volume"])
                  for r in rows]
