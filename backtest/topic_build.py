"""Study `topic_stocks` — data build. Implements the data part of backtest/studies/topic_stocks/PREREG.md.

    python -m backtest.topic_build universe      # formation ranking -> universe.csv
    python -m backtest.topic_build adanos        # 4 platforms x universe -> adanos_daily.csv.gz
    python -m backtest.topic_build prices        # Yahoo daily OHLC + hourly -> prices_daily/hourly.csv.gz
    python -m backtest.topic_build kalshi        # Kalshi subset -> kalshi_hourly.csv.gz, kalshi_markets.csv

Raw responses are cached under ingestion/data/raw/ (git-ignored); outputs go to
backtest/snapshots/topic_stocks/ (committed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import pandas as pd

from ingestion import adanos, yahoo

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAP = ROOT / "backtest" / "snapshots" / "topic_stocks"
ET = ZoneInfo("America/New_York")

HIST = ("2026-07-14", "2026-10-10")
FORMATION = ("2026-07-14", "2026-08-12")
PRICE_FROM = dt.date(2026, 6, 1)          # 20+ sessions before the first label/feature need
CALENDAR_CHECK = (dt.date(2026, 6, 12), dt.date(2026, 10, 9))
INDEX_PROXIES = ["SPY", "QQQ"]
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "NAS", "NYS"}
N_STOCKS = 100
PLATFORMS = ["x", "reddit", "news", "polymarket"]


def universe():
    tot, per = {}, {}
    for p in ("x", "reddit", "news"):
        rows = []
        for off in (0, 100, 200):
            rows += adanos.trending(p, "stocks", *FORMATION, limit=100, offset=off) or []
        per[p] = {r["ticker"]: (r.get("mentions") or 0) for r in rows}
        for t, m in per[p].items():
            tot[t] = tot.get(t, 0) + m
    ranked = sorted(tot, key=lambda t: -tot[t])
    _, spy = yahoo.daily_ohlc("SPY")
    sessions = [d for d, *_ in spy if CALENDAR_CHECK[0] <= d <= CALENDAR_CHECK[1]]
    rows, n_eq = [], 0
    for rank, t in enumerate(ranked, 1):
        meta, bars = yahoo.daily_ohlc(t.replace(".", "-"))
        itype = meta.get("instrumentType") if meta else None
        exch = meta.get("exchangeName") if meta else None
        have = {d for d, *_ in bars}
        complete = all(d in have for d in sessions)
        is_proxy = t in INDEX_PROXIES
        ok_type = itype == "EQUITY" and exch in US_EXCHANGES
        reason = ("selected" if (is_proxy or (ok_type and complete and n_eq < N_STOCKS)) else
                  "no Yahoo data" if meta is None else
                  f"type {itype}" if itype != "EQUITY" and not is_proxy else
                  f"exchange {exch}" if not ok_type and not is_proxy else
                  "incomplete prices" if not complete else "beyond top 100")
        if reason == "selected" and not is_proxy:
            n_eq += 1
        rows.append(dict(ticker=t, formation_rank=rank, formation_mentions=tot[t],
                         x=per["x"].get(t, 0), reddit=per["reddit"].get(t, 0), news=per["news"].get(t, 0),
                         yahoo_type=itype, exchange=exch, complete_prices=complete,
                         index_proxy=is_proxy, status=reason))
        if n_eq >= N_STOCKS and all(p in {r["ticker"] for r in rows} for p in INDEX_PROXIES):
            break
    df = pd.DataFrame(rows)
    SNAP.mkdir(parents=True, exist_ok=True)
    df.to_csv(SNAP / "universe_selection.csv", index=False)
    sel = df[df.status == "selected"]
    print(f"selected {len(sel)} ({(~sel.index_proxy).sum()} stocks + {sel.index_proxy.sum()} proxies) "
          f"from {len(df)} candidates checked")
    print(df.status.value_counts().to_dict())


def selected():
    df = pd.read_csv(SNAP / "universe_selection.csv")
    return df[df.status == "selected"].ticker.tolist()


def adanos_pull():
    rows = []
    for i, t in enumerate(selected()):
        for p in PLATFORMS:
            body = adanos.detail(p, "stocks", t, *HIST) or {}
            for x in body.get("daily_trend") or []:
                rows.append(dict(ticker=t, platform=p, **x))   # every daily field kept
        if i % 10 == 0:
            print(i, t, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(SNAP / "adanos_daily.csv.gz", index=False)
    print("adanos rows", len(df), "quota left", adanos.quota_left("polymarket", "stocks"))


def prices():
    drows, hrows = [], []
    for i, t in enumerate(selected()):
        sym = t.replace(".", "-")
        _, d = yahoo.daily_ohlc(sym)
        for day, o, h, lo, c, v in d:
            if day >= PRICE_FROM:
                drows.append(dict(ticker=t, date=day, open=o, high=h, low=lo, close=c, volume=v))
        _, hb = yahoo.hourly(sym)
        for ts, o, h, lo, c, v in hb:
            if ts.date() >= PRICE_FROM:
                hrows.append(dict(ticker=t, bar_start_utc=ts.isoformat(),
                                  bar_start_et=ts.astimezone(ET).strftime("%Y-%m-%d %H:%M"), close=c, volume=v))
        if i % 10 == 0:
            print(i, t, len(d), len(hb), flush=True)
    pd.DataFrame(drows).to_csv(SNAP / "prices_daily.csv.gz", index=False)
    pd.DataFrame(hrows).to_csv(SNAP / "prices_hourly.csv.gz", index=False)
    print("daily rows", len(drows), "hourly rows", len(hrows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["universe", "adanos", "prices", "kalshi"])
    a = ap.parse_args()
    if a.step == "kalshi":
        from backtest import topic_kalshi
        topic_kalshi.build(selected())
    else:
        {"universe": universe, "adanos": adanos_pull, "prices": prices}[a.step]()
    sys.exit(0)
