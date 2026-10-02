"""Binance spot daily klines (public market data, no key).

Uses data-api.binance.vision, Binance's public market-data host; api.binance.com refuses
some regions. Days are UTC. Raw responses are cached whole under ingestion/data/raw/binance/.
"""
from __future__ import annotations

import datetime as dt
import json

from ingestion.common import RAW, UTC, cache_json, http_get

BASE = "https://data-api.binance.vision/api/v3"
DIR = RAW / "binance"
KLINE_FIELDS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def usdt_symbols(refresh=False):
    path = DIR / "exchange_info.json"
    if not path.exists() or refresh:
        status, body, _ = http_get(f"{BASE}/exchangeInfo", pause=0.2)
        if status != 200:
            raise RuntimeError(f"exchangeInfo HTTP {status}")
        cache_json(path, body)
    body = json.loads(path.read_text())
    return {s["baseAsset"] for s in body["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"}


def daily_klines(base_asset: str, start: dt.date, end: dt.date, refresh=False):
    """Daily klines for <base_asset>USDT, start..end inclusive (UTC). Returns list of dicts."""
    sym = f"{base_asset}USDT"
    path = DIR / f"{sym}_{start}_{end}.json"
    if not path.exists() or refresh:
        t0 = int(dt.datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000)
        t1 = int(dt.datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
        status, body, _ = http_get(f"{BASE}/klines", params={"symbol": sym, "interval": "1d",
                                                              "startTime": t0, "endTime": t1, "limit": 1000}, pause=0.15)
        cache_json(path, {"status": status, "body": body, "_pulled_at": dt.datetime.now(UTC).isoformat()})
    blob = json.loads(path.read_text())
    if blob["status"] != 200 or not isinstance(blob["body"], list):
        return []
    out = []
    for k in blob["body"]:
        row = dict(zip(KLINE_FIELDS, k))
        row["date"] = dt.datetime.fromtimestamp(row["open_time"] / 1000, UTC).date()
        for f in ("open", "high", "low", "close", "volume", "quote_volume"):
            row[f] = float(row[f])
        out.append(row)
    return out
