"""Kalshi hourly candles for every event in Financials / Crypto / Commodities / Companies
settled since the historical cutoff, plus currently open events.

For series that list several events per day (hourly / 15-minute ladders) only the
event with the most volume per series per ET day is kept; 15-minute series are skipped.
Output (data/kalshi/): events.parquet, candles_<n>.parquet (hourly, markets with volume only).
"""
import collections, concurrent.futures as cf, datetime as dt, json, sys, time, zoneinfo
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from common import Limiter, get_json, log, f, OUT
from dashboard.symbols import CATEGORIES, map_series, topic_info

B = "https://api.elections.kalshi.com/trade-api/v2"
ET = zoneinfo.ZoneInfo("America/New_York")
LIM = Limiter(9)
D = OUT / "kalshi"; D.mkdir(exist_ok=True)
N = "kalshi"

cut = get_json(f"{B}/historical/cutoff", LIM) or {}
cutoff = dt.datetime.fromisoformat((cut.get("market_settled_ts") or "2026-08-23T00:00:00Z").replace("Z", "+00:00"))
log(N, f"cutoff {cutoff}")
series = {s["ticker"]: s for s in get_json(f"{B}/series", LIM)["series"] if s.get("category") in CATEGORIES}
series = {k: v for k, v in series.items() if "15M" not in k}
log(N, f"{len(series)} series in categories")


def list_events(s):
    out = []
    for status in ("settled", "open", "closed"):
        cur = ""
        while True:
            q = f"{B}/events?series_ticker={s}&status={status}&with_nested_markets=true&limit=200" + (f"&cursor={cur}" if cur else "")
            d = get_json(q, LIM)
            if not d:
                break
            for e in d.get("events", []):
                ms = e.get("markets") or []
                closes = [m.get("close_time") for m in ms if m.get("close_time")]
                close = max(closes) if closes else None
                if status != "open" and close and dt.datetime.fromisoformat(close.replace("Z", "+00:00")) < cutoff:
                    continue
                opens = [m.get("open_time") for m in ms if m.get("open_time")]
                out.append(dict(series=s, event=e["event_ticker"], status=status, title=e.get("title"),
                                strike_date=e.get("strike_date"), open_time=min(opens) if opens else None, close_time=close,
                                n_markets=len(ms), volume=sum(f(m.get("volume_fp")) or 0 for m in ms),
                                open_interest=sum(f(m.get("open_interest_fp")) or 0 for m in ms),
                                results=json.dumps({m["ticker"]: m.get("result") for m in ms if m.get("result")})))
            cur = d.get("cursor")
            # settled pages come newest first: stop once a whole page is older than the cutoff
            if not cur or not d.get("events"):
                break
            last = d["events"][-1].get("markets") or [{}]
            lc = max((m.get("close_time") or "" for m in last), default="")
            if status != "open" and lc and dt.datetime.fromisoformat(lc.replace("Z", "+00:00")) < cutoff:
                break
    return out


t0 = time.time()
events = []
with cf.ThreadPoolExecutor(6) as ex:
    for i, rows in enumerate(ex.map(list_events, list(series))):
        events += rows
        if i % 50 == 0:
            log(N, f"listed {i}/{len(series)} series, {len(events)} events")
ev = pd.DataFrame(events).drop_duplicates("event")
ev["frequency"] = ev.series.map(lambda s: series[s].get("frequency"))
ev["topic"] = ev.series.map(lambda s: map_series(s, series[s].get("title", ""), series[s].get("tags"))["topic"])
ev["asset_class"] = ev.topic.map(lambda t: topic_info(t)["asset_class"])
ev["close_dt"] = pd.to_datetime(ev.close_time, utc=True)
ev["et_day"] = ev.close_dt.dt.tz_convert(ET).dt.date.astype(str)
# several events per series per day -> keep the most traded one
multi = ev.groupby(["series", "et_day"]).event.transform("count") > 1
keep = ev[~multi]
best = ev[multi].sort_values("volume", ascending=False).drop_duplicates(["series", "et_day"])
sel = pd.concat([keep, best])
sel = sel[sel.volume > 0]
ev["selected"] = ev.event.isin(sel.event)
ev.drop(columns=["close_dt"]).to_parquet(D / "events.parquet", index=False)
log(N, f"{len(ev)} events since cutoff, {len(sel)} selected for candles ({time.time()-t0:.0f}s)")


def candles(row):
    end = min(int(time.time()), int(pd.Timestamp(row.close_time).timestamp()) + 3600) if row.close_time else int(time.time())
    start = int(pd.Timestamp(row.open_time).timestamp()) if row.open_time else end - 7 * 86400
    start = max(start, end - 30 * 86400)  # cap long-lived events at 30 days of hourly bars per request
    d = get_json(f"{B}/series/{row.series}/events/{row.event}/candlesticks?start_ts={start}&end_ts={end}&period_interval=60", LIM)
    out = []
    if not d:
        return out
    for mt, cs in zip(d.get("market_tickers") or [], d.get("market_candlesticks") or []):
        if not cs or not any((f(c.get("volume_fp")) or 0) > 0 for c in cs):
            continue
        for c in cs:
            yb, ya, p = c.get("yes_bid") or {}, c.get("yes_ask") or {}, c.get("price") or {}
            out.append((row.topic, row.series, row.event, mt, c["end_period_ts"], f(c.get("volume_fp")), f(c.get("open_interest_fp")),
                        f(yb.get("close_dollars")), f(ya.get("close_dollars")), f(p.get("close_dollars")),
                        f(p.get("high_dollars")), f(p.get("low_dollars"))))
    return out


cols = ["topic", "series", "event", "market", "ts", "volume", "open_interest", "yes_bid", "yes_ask", "price", "price_high", "price_low"]
buf, part, done = [], 0, 0
rows = list(sel.sort_values("volume", ascending=False).itertuples())
with cf.ThreadPoolExecutor(6) as ex:
    for res in ex.map(candles, rows):
        buf += res
        done += 1
        if len(buf) > 400_000 or done == len(rows):
            df = pd.DataFrame(buf, columns=cols)
            df["ts"] = pd.to_datetime(df.ts, unit="s", utc=True)
            df.to_parquet(D / f"candles_{part:03d}.parquet", index=False)
            log(N, f"candles {done}/{len(rows)} events, wrote part {part} ({len(df)} rows, {time.time()-t0:.0f}s)")
            buf, part = [], part + 1
log(N, "DONE")
