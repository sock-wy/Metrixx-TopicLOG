"""Collector entry point.

Backfill (history for backtests; idempotent, cached):
    python -m ingestion.pull kalshi --universe backtest/universes/crypto_indices.yaml \
        --start 2026-08-03 --end 2026-10-01
    python -m ingestion.pull adanos --universe ... --start 2026-09-02 --end 2026-10-01
    python -m ingestion.pull yahoo  --universe ...

Live (for the VPS cron; one call per series + one Adanos compare per platform):
    python -m ingestion.pull snapshot --universe ...

Every response is stored whole under ingestion/data/raw/ (git-ignored).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import yaml

from ingestion import adanos, kalshi, yahoo
from ingestion.common import RAW, UTC, cache_json, et, fmt_event


def load_universe(path):
    with open(path) as f:
        return yaml.safe_load(f)


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def pull_kalshi(uni, start, end, log=print):
    """Daily ladder candles + the 15:00 ET hourly event (for the reference price)."""
    missing = []
    for tk, spec in uni["tickers"].items():
        for d in days(start, end):
            if spec["calendar"] == "nyse" and d.weekday() >= 5:
                continue
            ev = fmt_event(spec["daily_event"], d)
            c = kalshi.event_candles(spec["kalshi_series"], ev, et(d - dt.timedelta(days=1), 12), et(d, 18))
            pe = fmt_event(spec["price_event"], d)
            p = kalshi.settlement_value(pe)
            if c is None or p is None:
                missing.append((tk, d.isoformat(), "ladder" if c is None else "", "price" if p is None else ""))
        log(f"kalshi {tk}: done")
    return missing


def pull_adanos(uni, start, end, log=print):
    out = {}
    for tk, spec in uni["tickers"].items():
        a = spec.get("adanos")
        if not a:
            continue
        body = adanos.detail(a["platform"], a["kind"], a["symbol"], start.isoformat(), end.isoformat())
        n = len((body or {}).get("daily_trend") or [])
        out[tk] = n
        log(f"adanos {tk} ({a['symbol']}): found={bool(body and body.get('found'))} days={n}")
    left = adanos.quota_left()
    if left:
        log(f"adanos monthly quota left: {left}")
    return out


def pull_yahoo(uni, log=print):
    for tk, spec in uni["tickers"].items():
        rows = yahoo.daily(spec["yahoo"])
        log(f"yahoo {tk} ({spec['yahoo']}): {len(rows)} days, last {rows[-1][0]}")


def snapshot(uni, log=print):
    """Live snapshot of every open market in each series; appended as one file per pull."""
    now = dt.datetime.now(UTC)
    for tk, spec in uni["tickers"].items():
        ms = kalshi.open_markets_snapshot(spec["kalshi_series"])
        path = RAW / "kalshi" / "snapshots" / now.strftime("%Y-%m-%d") / f"{now:%H%M}_{spec['kalshi_series']}.json"
        cache_json(path, {"pulled_at": now.isoformat(), "markets": ms})
        log(f"snapshot {tk}: {len(ms)} open markets")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["kalshi", "adanos", "yahoo", "snapshot"])
    ap.add_argument("--universe", required=True)
    ap.add_argument("--start", type=dt.date.fromisoformat)
    ap.add_argument("--end", type=dt.date.fromisoformat)
    a = ap.parse_args(argv)
    uni = load_universe(a.universe)
    if a.what == "kalshi":
        missing = pull_kalshi(uni, a.start, a.end)
        print(f"{len(missing)} ticker-days missing a ladder or price:")
        for m in missing:
            print("  ", *m)
        cache_json(RAW / "kalshi" / "missing.json", missing)
    elif a.what == "adanos":
        pull_adanos(uni, a.start, a.end)
    elif a.what == "yahoo":
        pull_yahoo(uni)
    else:
        snapshot(uni)


if __name__ == "__main__":
    sys.exit(main())
