"""Adanos sentiment API (needs ADANOS_API_KEY in the environment or a local .env).

Free keys: 250 requests / month, 100 / minute, 30 days of history. Every response
is cached whole under ingestion/data/raw/adanos/, so re-runs cost nothing and no
field is dropped.

Endpoints used:
  /{platform}/crypto/v1/token/{symbol}?from&to   per-token detail incl. daily_trend
  /{platform}/stocks/v1/stock/{ticker}?from&to   per-ticker detail incl. daily_trend
  /{platform}/crypto/v1/compare?symbols=...       live: many tokens, one request
"""
from __future__ import annotations

import datetime as dt
import json
import os

from ingestion.common import RAW, UTC, cache_json, http_get, load_env

BASE = "https://api.adanos.org"
DIR = RAW / "adanos"


def _key():
    load_env()
    key = os.environ.get("ADANOS_API_KEY")
    if not key:
        raise SystemExit("ADANOS_API_KEY is not set (export it or put it in .env)")
    return key


def detail(platform: str, kind: str, symbol: str, frm: str, to: str, refresh=False):
    """Detail response for one token/ticker over [frm, to]. Returns the parsed body or None."""
    path = DIR / f"{platform}_{kind}_{symbol}_{frm}_{to}.json"
    if path.exists() and not refresh:
        blob = json.loads(path.read_text())
        return blob["body"] if blob.get("status") == 200 else None
    noun = "token" if kind == "crypto" else "stock"
    status, body, headers = http_get(
        f"{BASE}/{platform}/{kind}/v1/{noun}/{symbol}",
        params={"from": frm, "to": to},
        headers={"X-API-Key": _key()},
        pause=0.7,
    )
    quota = {k: v for k, v in headers.items() if k.lower().startswith("x-ratelimit")}
    cache_json(path, {"status": status, "body": body, "quota": quota,
                      "_pulled_at": dt.datetime.now(UTC).isoformat()})
    return body if status == 200 else None


def quota_left(platform="reddit", kind="crypto"):
    """Remaining monthly quota as reported by the last cached response, if any."""
    files = sorted(DIR.glob(f"{platform}_{kind}_*.json"), key=lambda p: p.stat().st_mtime)
    for p in reversed(files):
        q = json.loads(p.read_text()).get("quota") or {}
        for k, v in q.items():
            if "month" in k.lower() and "remaining" in k.lower():
                return v
    return None


def trending(platform: str, kind: str, frm: str, to: str, limit: int = 100, offset: int = 0, refresh=False):
    """Trending list over [frm, to] (aggregate per token, API order). Cached whole."""
    path = DIR / f"trending_{platform}_{kind}_{frm}_{to}_{limit}_{offset}.json"
    if not path.exists() or refresh:
        status, body, headers = http_get(f"{BASE}/{platform}/{kind}/v1/trending",
                                         params={"from": frm, "to": to, "limit": limit, "offset": offset},
                                         headers={"X-API-Key": _key()}, pause=0.7)
        cache_json(path, {"status": status, "body": body,
                          "quota": {k: v for k, v in headers.items() if k.lower().startswith("x-ratelimit")},
                          "_pulled_at": dt.datetime.now(UTC).isoformat()})
    blob = json.loads(path.read_text())
    return blob["body"] if blob.get("status") == 200 else None
