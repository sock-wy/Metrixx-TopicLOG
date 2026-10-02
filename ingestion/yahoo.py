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
