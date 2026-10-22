"""Yahoo Finance history.

1. Every Topic Log topic with a price symbol: 1h bars for 2 years, 1m bars for the last ~30 days, 1d bars max.
2. Every US-listed stock from today's Nasdaq screener: 1d OHLCV for 2 years.
Output (data/yahoo/): topics_1h.parquet, topics_1m.parquet, topics_1d.parquet, us_stocks_1d_<n>.parquet
"""
import concurrent.futures as cf, json, sys, time
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from common import Limiter, get_json, log, OUT
from dashboard.symbols import TOPICS

N = "yahoo"
D = OUT / "yahoo"; D.mkdir(exist_ok=True)
LIM = Limiter(5)
C = "https://query1.finance.yahoo.com/v8/finance/chart/"


def chart(sym, interval, rng=None, p1=None, p2=None):
    q = f"interval={interval}&includePrePost=false" + (f"&range={rng}" if rng else f"&period1={p1}&period2={p2}")
    d = get_json(C + sym.replace("^", "%5E").replace("=", "%3D") + "?" + q, LIM)
    try:
        r = d["chart"]["result"][0]
    except Exception:
        return None
    ts = r.get("timestamp") or []
    if not ts:
        return None
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame(dict(ts=pd.to_datetime(ts, unit="s", utc=True), open=q.get("open"), high=q.get("high"),
                           low=q.get("low"), close=q.get("close"), volume=q.get("volume")))
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj:
        df["adjclose"] = adj
    df.insert(0, "symbol", sym)
    return df.dropna(subset=["close"])


topics = {}
for t, (name, ac, yh, ad) in TOPICS.items():
    if yh:
        topics[yh] = (t, ac)
syms = sorted(topics)
log(N, f"{len(syms)} topic symbols")
t0 = time.time()


def topic_all(sym):
    out = {}
    out["1h"] = chart(sym, "60m", rng="730d")
    out["1d"] = chart(sym, "1d", rng="max")
    now = int(time.time())
    parts = []
    for k in range(4):  # 1m is served 8 days per request, ~30 days back
        p2 = now - k * 7 * 86400
        x = chart(sym, "1m", p1=p2 - 7 * 86400, p2=p2)
        if x is not None:
            parts.append(x)
    out["1m"] = pd.concat(parts).drop_duplicates(["symbol", "ts"]) if parts else None
    for k, v in out.items():
        if v is not None:
            v.insert(1, "topic", topics[sym][0]); v.insert(2, "asset_class", topics[sym][1])
    return out


res = {"1h": [], "1d": [], "1m": []}
with cf.ThreadPoolExecutor(4) as ex:
    for i, out in enumerate(ex.map(topic_all, syms), 1):
        for k, v in out.items():
            if v is not None:
                res[k].append(v)
        if i % 25 == 0:
            log(N, f"topics {i}/{len(syms)} ({time.time()-t0:.0f}s)")
for k, v in res.items():
    if v:
        df = pd.concat(v); df.to_parquet(D / f"topics_{k}.parquet", index=False)
        log(N, f"topics_{k}: {len(df)} rows, {df.symbol.nunique()} symbols")

# all US stocks, daily 2y
us = json.load(open(sys.argv[1]))  # us_stocks.json from a dashboard pull
us = sorted(us, key=lambda r: -(r.get("market_cap") or 0))
stocks = [r["symbol"].replace("/", "-") for r in us if r.get("symbol")]
log(N, f"{len(stocks)} US stocks, daily 2y")
buf, part = [], 0
meta = {r["symbol"].replace("/", "-"): r for r in us}
with cf.ThreadPoolExecutor(4) as ex:
    for i, df in enumerate(ex.map(lambda s: chart(s, "1d", rng="2y"), stocks), 1):
        if df is not None:
            df["sector"] = meta[df.symbol.iloc[0]].get("sector")
            buf.append(df)
        if i % 500 == 0 or i == len(stocks):
            if buf:
                x = pd.concat(buf); x.to_parquet(D / f"us_stocks_1d_{part:02d}.parquet", index=False)
                log(N, f"us stocks {i}/{len(stocks)}, part {part}: {len(x)} rows ({time.time()-t0:.0f}s)")
                buf, part = [], part + 1
log(N, "DONE")
