import concurrent.futures as cf, sys, time
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import Limiter, get_json, log, OUT
L = Limiter(6); t0 = time.time()
m = pd.read_parquet(OUT / "polymarket/markets.parquet")
def h(r):
    d = get_json(f"https://clob.polymarket.com/prices-history?market={r.token}&interval=max&fidelity=1440", L)
    return [(r.market_id, r.event_id, pd.Timestamp(p["t"], unit="s", tz="UTC"), float(p["p"])) for p in ((d or {}).get("history") or [])]
rows = []
with cf.ThreadPoolExecutor(4) as ex:
    for i, x in enumerate(ex.map(h, list(m.itertuples())), 1):
        rows += x
        if i % 500 == 0: log("polymarket", f"daily {i}/{len(m)} ({time.time()-t0:.0f}s)")
x = pd.DataFrame(rows, columns=["market_id", "event_id", "ts", "price"]); x.to_parquet(OUT / "polymarket/prices_1d.parquet", index=False)
log("polymarket", f"prices_1d: {len(x)} rows, {x.market_id.nunique()} markets DONE")
