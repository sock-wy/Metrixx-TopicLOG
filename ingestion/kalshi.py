"""Kalshi public market data (no API key needed).

Raw responses are stored whole, every field kept, under
ingestion/data/raw/kalshi/. Downstream code decides which fields to use.

Endpoints:
  /series/{series}/events/{event}/candlesticks   hourly candles for every strike in a ladder
  /markets?event_ticker=...                      market objects (settlement value, strikes, status)
  /markets?series_ticker=...&status=open         live snapshot (used by `pull.py snapshot`)

Kalshi moves events settled before its historical cutoff (2026-08-02 at time of writing)
to /historical/*, where event-level candles are not served. Backfills therefore start
after the cutoff.
"""
from __future__ import annotations

import datetime as dt
import json

from ingestion.common import RAW, UTC, cache_json, http_get

BASE = "https://api.elections.kalshi.com/trade-api/v2"
DIR = RAW / "kalshi"


def event_candles(series: str, event: str, start: dt.datetime, end: dt.datetime,
                  period_minutes: int = 60, refresh: bool = False):
    """Hourly candles for every market in `event`. None if the event does not exist."""
    path = DIR / "candles" / f"{event}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text()) or None
    status, body, _ = http_get(
        f"{BASE}/series/{series}/events/{event}/candlesticks",
        params={"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()),
                "period_interval": period_minutes},
        ok404=True, pause=0.4,
    )
    if status == 404 or not body or not body.get("market_tickers"):
        cache_json(path, {})  # remember "no event" so re-runs stay cheap
        return None
    if status != 200:
        raise RuntimeError(f"{event}: HTTP {status} {body}")
    body["_pulled_at"] = dt.datetime.now(UTC).isoformat()
    body["_request"] = {"series": series, "start": start.isoformat(), "end": end.isoformat()}
    cache_json(path, body)
    return body


def event_markets(event: str, refresh: bool = False):
    """All market objects of an event (paginated), every field kept. None if absent."""
    path = DIR / "markets" / f"{event}.json"
    if path.exists() and not refresh:
        data = json.loads(path.read_text())
        return data.get("markets") or None
    markets, cursor = [], None
    while True:
        params = {"event_ticker": event, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        status, body, _ = http_get(f"{BASE}/markets", params=params, pause=0.3)
        if status != 200:
            raise RuntimeError(f"{event}: HTTP {status} {body}")
        markets += body.get("markets") or []
        cursor = body.get("cursor")
        if not cursor or not body.get("markets"):
            break
    cache_json(path, {"markets": markets, "_pulled_at": dt.datetime.now(UTC).isoformat()})
    return markets or None


def settlement_value(event: str):
    """Underlying value the event settled on (`expiration_value`), or None."""
    ms = event_markets(event)
    if not ms:
        return None
    vals = {m.get("expiration_value") for m in ms if m.get("expiration_value") not in (None, "")}
    if len(vals) != 1:
        return None  # not settled yet, or inconsistent -> treat as missing
    try:
        return float(vals.pop())
    except ValueError:
        return None  # malformed at source (seen: expiration_value "No") -> missing, never guessed


def open_markets_snapshot(series: str):
    """Live: every open market in a series right now (for scheduled snapshots)."""
    markets, cursor = [], None
    while True:
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        status, body, _ = http_get(f"{BASE}/markets", params=params, pause=0.3)
        if status != 200:
            raise RuntimeError(f"{series}: HTTP {status} {body}")
        markets += body.get("markets") or []
        cursor = body.get("cursor")
        if not cursor or not body.get("markets"):
            break
    return markets
