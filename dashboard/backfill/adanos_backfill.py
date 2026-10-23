"""Adanos history (hobby key: ~90 days back).

Per-symbol daily_trend on every platform for (a) every Topic Log topic with an Adanos symbol
and (b) the 1,000 largest US stocks by market cap; plus each day's trending lists (stocks per
platform, crypto) and trending sectors. Output: data/adanos/*.parquet
"""
import pathlib, concurrent.futures as cf, datetime as dt, json, os, sys, time, urllib.parse
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent)); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from common import Limiter, get_json, log, OUT
from dashboard.symbols import TOPICS

N = "adanos"; D = OUT / "adanos"; D.mkdir(exist_ok=True)
KEY = os.environ["ADANOS_API_KEY"]
H = {"X-API-Key": KEY}
L = Limiter(10)
B = "https://api.adanos.org"
today = dt.datetime.utcnow().date()
t1 = (today - dt.timedelta(days=1)).isoformat()
t0d = (today - dt.timedelta(days=89)).isoformat()
STOCK_PLATFORMS = ["reddit", "x", "news", "polymarket"]
t0 = time.time()

stocks = {ad[1] for t, (n, ac, yh, ad) in TOPICS.items() if ad and ad[0] == "stocks"}
crypto = {ad[1] for t, (n, ac, yh, ad) in TOPICS.items() if ad and ad[0] == "crypto"}
us = json.load(open(sys.argv[1]))  # us_stocks.json from a dashboard pull
us = [r["symbol"] for r in sorted(us, key=lambda r: -(r.get("market_cap") or 0)) if r.get("symbol") and "/" not in r["symbol"] and "^" not in r["symbol"]][:1000]
stocks |= set(us)
log(N, f"{len(stocks)} stock symbols x {len(STOCK_PLATFORMS)} platforms, {len(crypto)} crypto")


def detail(job):
    plat, kind, sym = job
    noun = "token" if kind == "crypto" else "stock"
    d = get_json(f"{B}/{plat}/{kind}/v1/{noun}/{urllib.parse.quote(sym)}?from={t0d}&to={t1}", L, H)
    if not d or d.get("found") is False:
        return []
    return [dict(platform=plat, kind=kind, symbol=sym, **x) for x in (d.get("daily_trend") or [])]


jobs = [(p, "stocks", s) for p in STOCK_PLATFORMS for s in sorted(stocks)] + [("reddit", "crypto", s) for s in sorted(crypto)]
rows = []
with cf.ThreadPoolExecutor(6) as ex:
    for i, r in enumerate(ex.map(detail, jobs), 1):
        rows += r
        if i % 500 == 0:
            log(N, f"daily_trend {i}/{len(jobs)}, {len(rows)} rows ({time.time()-t0:.0f}s)")
df = pd.DataFrame(rows); df.to_parquet(D / "daily_by_symbol.parquet", index=False)
log(N, f"daily_by_symbol: {len(df)} rows, {df.groupby('platform').symbol.nunique().to_dict()}")

# trending lists and sectors, one call per day per platform
days = [(today - dt.timedelta(days=k)).isoformat() for k in range(1, 90)]


def trending(job):
    plat, kind, what, day = job
    path = f"{B}/{plat}/{kind}/v1/trending" + ("/sectors" if what == "sectors" else "")
    d = get_json(f"{path}?from={day}&to={day}&limit=100", L, H)
    items = d if isinstance(d, list) else (d or {}).get("stocks") or (d or {}).get("tokens") or (d or {}).get("sectors") or []
    out = []
    for rank, x in enumerate(items, 1):
        x = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in x.items()}
        out.append(dict(date=day, platform=plat, kind=kind, list=what, rank=rank, **x))
    return out


tj = [(p, "stocks", w, d) for p in STOCK_PLATFORMS for w in ("stocks", "sectors") for d in days] + [("reddit", "crypto", "tokens", d) for d in days]
rows = []
with cf.ThreadPoolExecutor(6) as ex:
    for i, r in enumerate(ex.map(trending, tj), 1):
        rows += r
        if i % 200 == 0:
            log(N, f"trending {i}/{len(tj)} ({time.time()-t0:.0f}s)")
tr = pd.DataFrame(rows)
for w, g in tr.groupby("list"):
    g.dropna(axis=1, how="all").to_parquet(D / f"trending_{w}.parquet", index=False)
    log(N, f"trending_{w}: {len(g)} rows")
log(N, "DONE")
