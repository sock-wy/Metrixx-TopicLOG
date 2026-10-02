"""Raw API responses -> compact snapshot tables committed under backtest/snapshots/<universe>/.

The tables replay the live collection cadence: the state of every daily ladder at
four snapshot times a day (15:00, 21:00, 03:00, 09:00 ET), reconstructed from
hourly candles. A snapshot at time T only uses candles that closed at or before T.

Outputs (csv.gz, one row per ...):
  ladder_strikes   ticker, event_date, snapshot_ts, strike  (strikes within +/-10% of the
                   snapshot's implied median; wide enough for every ATM-band variant)
  ladder_totals    ticker, event_date, snapshot_ts           (whole-ladder volume, OI, counts)
  prices           ticker, date                              (15:00 ET Kalshi settlement value)
  vol_scale        ticker, date                              (Yahoo daily close, for trailing vol)
  adanos_daily     ticker, date                              (every daily_trend field, used or not)

    python -m backtest.build_snapshots --universe backtest/universes/crypto_indices.yaml \
        --start 2026-08-03 --end 2026-10-01 --adanos-from 2026-07-20 --adanos-to 2026-10-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

import pandas as pd
import yaml

from ingestion import kalshi, yahoo
from ingestion.common import RAW, et, fmt_event

SNAPSHOT_HOURS_ET = [(-1, 21), (0, 3), (0, 9), (0, 15)]  # (day offset vs event date, hour)
STORE_BAND = 0.10


def _f(x):
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def strike_of(market_ticker: str) -> float:
    return float(market_ticker.rsplit("-", 1)[1].lstrip("TB"))


def ladder_states(candles: dict, snapshot_ts: list[dt.datetime]):
    """Per snapshot time: list of strike states built only from candles closed by then."""
    out = {ts: [] for ts in snapshot_ts}
    for mt, cs in zip(candles["market_tickers"], candles["market_candlesticks"]):
        k = strike_of(mt)
        cs = sorted(cs, key=lambda c: c["end_period_ts"])
        for ts in snapshot_ts:
            cut = int(ts.timestamp())
            upto = [c for c in cs if c["end_period_ts"] <= cut]
            if not upto:
                continue
            last = upto[-1]
            out[ts].append(dict(
                market_ticker=mt, strike=k,
                cum_volume=sum(_f(c.get("volume_fp")) or 0.0 for c in upto),
                open_interest=_f(last.get("open_interest_fp")),
                yes_bid=_f((last.get("yes_bid") or {}).get("close_dollars")),
                yes_ask=_f((last.get("yes_ask") or {}).get("close_dollars")),
                last_price=_f((last.get("price") or {}).get("close_dollars")),
                last_candle_ts=last["end_period_ts"],
            ))
    return out


def mid(s):
    b, a = s["yes_bid"], s["yes_ask"]
    if b is None or a is None or a < b or a <= 0:
        return None
    return (a + b) / 2


def implied_median(states):
    """Strike whose mid is closest to 0.5 (the ladder's implied median)."""
    best = None
    for s in states:
        m = mid(s)
        if m is not None and (best is None or abs(m - 0.5) < abs(best[1] - 0.5)):
            best = (s["strike"], m)
    return best[0] if best else None


def build_kalshi(uni, start, end):
    strikes_rows, totals_rows, price_rows = [], [], []
    for tk, spec in uni["tickers"].items():
        d = start
        while d <= end:
            if not (spec["calendar"] == "nyse" and d.weekday() >= 5):
                ev = fmt_event(spec["daily_event"], d)
                path = RAW / "kalshi" / "candles" / f"{ev}.json"
                candles = json.loads(path.read_text()) if path.exists() else {}
                if candles.get("market_tickers"):
                    snaps = [et(d + dt.timedelta(days=off), h) for off, h in SNAPSHOT_HOURS_ET]
                    states = ladder_states(candles, snaps)
                    for ts, st in states.items():
                        if not st:
                            continue
                        center = implied_median(st)
                        totals_rows.append(dict(
                            ticker=tk, event_date=d, event=ev, snapshot_ts=ts,
                            total_cum_volume=sum(s["cum_volume"] for s in st),
                            total_open_interest=sum(s["open_interest"] or 0 for s in st),
                            n_strikes=len(st), n_strikes_traded=sum(s["cum_volume"] > 0 for s in st),
                            implied_median=center,
                        ))
                        if center is None:
                            continue
                        for s in st:
                            if abs(s["strike"] / center - 1) <= STORE_BAND:
                                strikes_rows.append(dict(ticker=tk, event_date=d, snapshot_ts=ts, **s))
                p = kalshi.settlement_value(fmt_event(spec["price_event"], d))
                if p is not None:
                    price_rows.append(dict(ticker=tk, date=d, price_1500_et=p,
                                           price_event=fmt_event(spec["price_event"], d)))
            d += dt.timedelta(days=1)
    return pd.DataFrame(strikes_rows), pd.DataFrame(totals_rows), pd.DataFrame(price_rows)


def build_vol_scale(uni):
    rows = []
    for tk, spec in uni["tickers"].items():
        for d, c in yahoo.daily(spec["yahoo"]):
            rows.append(dict(ticker=tk, date=d, close=c))
    return pd.DataFrame(rows)


def build_adanos(uni, frm, to):
    rows = []
    for tk, spec in uni["tickers"].items():
        a = spec["adanos"]
        p = RAW / "adanos" / f"{a['platform']}_{a['kind']}_{a['symbol']}_{frm}_{to}.json"
        blob = json.loads(p.read_text())
        body = blob.get("body") or {}
        for x in body.get("daily_trend") or []:
            rows.append(dict(ticker=tk, adanos_symbol=a["symbol"], **x))  # every field kept
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", required=True)
    ap.add_argument("--start", type=dt.date.fromisoformat, required=True)
    ap.add_argument("--end", type=dt.date.fromisoformat, required=True)
    ap.add_argument("--adanos-from", required=True)
    ap.add_argument("--adanos-to", required=True)
    a = ap.parse_args(argv)
    uni = yaml.safe_load(open(a.universe))
    out = pathlib.Path(__file__).parent / "snapshots" / uni["name"]
    out.mkdir(parents=True, exist_ok=True)
    strikes, totals, prices = build_kalshi(uni, a.start, a.end)
    tables = {
        "ladder_strikes": strikes, "ladder_totals": totals, "prices": prices,
        "vol_scale": build_vol_scale(uni), "adanos_daily": build_adanos(uni, a.adanos_from, a.adanos_to),
    }
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv.gz", index=False)
        print(f"{name:15s} {len(df):>8,} rows")
    meta = dict(universe=uni["name"], kalshi_start=str(a.start), kalshi_end=str(a.end),
                adanos_from=a.adanos_from, adanos_to=a.adanos_to,
                snapshot_hours_et=SNAPSHOT_HOURS_ET, store_band=STORE_BAND,
                built_at=dt.datetime.now(dt.timezone.utc).isoformat())
    (out / "meta.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
