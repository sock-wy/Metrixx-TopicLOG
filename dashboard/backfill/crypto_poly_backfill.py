"""Binance klines for the top USDT pairs and Polymarket price history for money-tagged events.

Binance (data-api.binance.vision): top 50 USDT pairs by 24h quote volume, stablecoins excluded:
  1h klines since 2 years ago, 1m klines for the last 30 days.
Polymarket (gamma + clob): every event from the dashboard's polymarket pull; for each, up to
  5 most traded markets, YES-token price history at 1-hour fidelity over the market's life.
Output: data/binance/klines_1h.parquet, klines_1m.parquet; data/polymarket/markets.parquet, prices_1h.parquet
"""
import concurrent.futures as cf, json, sys, time, urllib.parse
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import Limiter, get_json, log, OUT, f

t0 = time.time()
# ---------------------------------------------------------------- Binance
N = "binance"; D = OUT / "binance"; D.mkdir(exist_ok=True)
LB = Limiter(8)
STABLE = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "USDE", "EUR", "BUSD", "USD1", "XUSD", "RLUSD", "PYUSD", "EURI", "AEUR", "BFUSD", "USDS"}
tick = get_json("https://data-api.binance.vision/api/v3/ticker/24hr", LB)
pairs = [x for x in tick if x["symbol"].endswith("USDT") and x["symbol"][:-4] not in STABLE]
pairs = [x["symbol"] for x in sorted(pairs, key=lambda x: -float(x["quoteVolume"]))[:50]]
log(N, f"pairs: {pairs}")
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]


def klines(sym, interval, start_ms):
    rows, s = [], start_ms
    end = int(time.time() * 1000)
    while s < end:
        d = get_json(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={interval}&startTime={s}&limit=1000", LB)
        if not d:
            break
        rows += d
        s = d[-1][0] + 1
        if len(d) < 1000:
            break
    df = pd.DataFrame(rows, columns=COLS).drop(columns=["ignore"])
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df.open_time, unit="ms", utc=True)
    df.insert(0, "symbol", sym)
    return df.drop(columns=["open_time", "close_time"])


now_ms = int(time.time() * 1000)
for interval, back_days in (("1h", 730), ("1m", 30)):
    out = []
    with cf.ThreadPoolExecutor(3) as ex:
        for i, df in enumerate(ex.map(lambda s: klines(s, interval, now_ms - back_days * 86400_000), pairs), 1):
            out.append(df)
            if i % 10 == 0:
                log(N, f"{interval} {i}/{len(pairs)} ({time.time()-t0:.0f}s)")
    x = pd.concat(out); x.to_parquet(D / f"klines_{interval}.parquet", index=False)
    log(N, f"klines_{interval}: {len(x)} rows")
log(N, "DONE")

# ---------------------------------------------------------------- Polymarket
N = "polymarket"; D = OUT / "polymarket"; D.mkdir(exist_ok=True)
LP = Limiter(6)
TAGS = ["finance", "economy", "stocks", "earnings", "fed-rates", "commodities", "ipos", "business", "crypto"]
events = {}
for tag in TAGS:
    off = 0
    while off < 200:
        q = urllib.parse.urlencode(dict(active="true", closed="false", limit=100, offset=off, tag_slug=tag, order="volume24hr", ascending="false"))
        page = get_json(f"https://gamma-api.polymarket.com/events?{q}", LP) or []
        for e in page:
            events.setdefault(e["id"], (e, set()))[1].add(tag)
        off += 100
        if len(page) < 100:
            break
mk = []
for eid, (e, tags) in events.items():
    ms = sorted(e.get("markets") or [], key=lambda m: -(f(m.get("volumeNum")) or 0))[:5]
    for m in ms:
        try:
            tok = json.loads(m.get("clobTokenIds") or "[]")
            outc = json.loads(m.get("outcomes") or "[]")
        except Exception:
            continue
        if not tok:
            continue
        mk.append(dict(event_id=eid, event_title=e.get("title"), tags=", ".join(sorted(tags)), market_id=m.get("id"),
                       question=m.get("question"), outcome=(outc[0] if outc else "Yes"), token=tok[0],
                       volume=f(m.get("volumeNum")), volume_24h=f(m.get("volume24hr")), liquidity=f(m.get("liquidityNum")),
                       start=m.get("startDate"), end=m.get("endDate"), last_price=f(m.get("lastTradePrice"))))
mkt = pd.DataFrame(mk); mkt.to_parquet(D / "markets.parquet", index=False)
log(N, f"{len(events)} events, {len(mkt)} markets")


def hist(row):
    d = get_json(f"https://clob.polymarket.com/prices-history?market={row.token}&interval=max&fidelity=60", LP)
    h = (d or {}).get("history") or []
    return [(row.market_id, row.event_id, pd.Timestamp(p["t"], unit="s", tz="UTC"), float(p["p"])) for p in h]


rows = []
with cf.ThreadPoolExecutor(4) as ex:
    for i, r in enumerate(ex.map(hist, list(mkt.itertuples())), 1):
        rows += r
        if i % 200 == 0:
            log(N, f"history {i}/{len(mkt)} ({time.time()-t0:.0f}s)")
x = pd.DataFrame(rows, columns=["market_id", "event_id", "ts", "price"])
x.to_parquet(D / "prices_1h.parquet", index=False)
log(N, f"prices_1h: {len(x)} rows, {x.market_id.nunique()} markets")
log(N, "DONE")
