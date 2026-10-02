"""Shared helpers for collectors: paths, .env loading, HTTP with retry, ET time."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import time
from zoneinfo import ZoneInfo

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "ingestion" / "data" / "raw"   # git-ignored (matches .gitignore `data/`)
ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


def load_env(path=ROOT / ".env"):
    """Minimal .env reader (KEY=VALUE lines); existing environment wins."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def et(date: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    """A wall-clock time in New York on `date`, as an aware UTC datetime (DST-safe)."""
    return dt.datetime(date.year, date.month, date.day, hour, minute, tzinfo=ET).astimezone(UTC)


def fmt_event(pattern: str, d: dt.date) -> str:
    return pattern.format(yy=f"{d:%y}", MON=f"{d:%b}".upper(), dd=f"{d:%d}")


def http_get(url, params=None, headers=None, max_tries=6, ok404=False, pause=0.0):
    """GET with retry on 429/5xx. Returns (status, json_or_None, headers)."""
    for attempt in range(max_tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=60)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            time.sleep(2 + 2 * attempt)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 2)) + attempt)
            continue
        if pause:
            time.sleep(pause)
        if r.status_code == 404 and ok404:
            return 404, None, r.headers
        body = None
        try:
            body = r.json()
        except ValueError:
            pass
        return r.status_code, body, r.headers
    raise RuntimeError(f"gave up after {max_tries} tries: {url}")


def cache_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)  # atomic: a half-written file is never left behind
