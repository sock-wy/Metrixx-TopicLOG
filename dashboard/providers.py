"""New data sources replacing Yahoo and Nasdaq (agenda 11/20): Benzinga, Bigdata.com, SEC, Binance public data.

Each function returns the same shape as the source it replaces, so pipeline.py and sources.py can switch per pull:
  benzinga_hourly(symbols, key)       -> {sym: [(ts, close, volume)]}   like pipeline.yahoo_prices (hourly, ~1 month)
  benzinga_daily(symbol, start, key)  -> [{timestamp, open, hi, lo, close, volume}]  (DXcharts candles)
  benzinga_movers(key)                -> rows like sources.yahoo_movers
  benzinga_earnings(today, key)       -> rows like sources.nasdaq_earnings
  sec_tickers(contact_email)          -> rows like sources.nasdaq_screener (symbol, name only)
  bigdata_hourly(symbols, key)        -> like benzinga_hourly (RavenPack entity ids looked up by MIC:TICKER, cached)
  bigdata_daily(symbol, start, key)   -> candles
  binance_daily(pair, days)           -> candles from data-api.binance.vision (public market data, no key)
Benzinga covers US stocks and ETFs; index, FX and futures symbols (^GSPC, EURUSD=X, GC=F) stay on the old source
until a replacement is chosen (Bigdata.com FX, or ETF proxies such as SPY, QQQ, GLD, USO).
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "MetrixxTopicLog/1.2"
BZ = "https://api.benzinga.com/api"


def _get(url, headers=None, timeout=40, tries=2):
    err = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            err = RuntimeError(f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
            if e.code in (401, 403, 404):
                break
        except Exception as e:
            err = e
        time.sleep(1 + k)
    raise err


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def is_equity_symbol(sym: str) -> bool:
    """Plain US stock / ETF tickers (Benzinga covers these); not ^index, =X FX, =F futures or crypto pairs."""
    return bool(sym) and not any(c in sym for c in "^=") and not sym.endswith("-USD")


# ------------------------------------------------------------------ Benzinga
def _bz_bars(symbols, key, frm, interval):
    q = urllib.parse.urlencode({"token": key, "symbols": ",".join(symbols), "from": frm, "interval": interval})
    out = {}
    for item in _get(f"{BZ}/v2/bars?{q}") or []:
        pts = []
        for c in item.get("candles") or []:
            t = _f(c.get("time"))
            if t is None or c.get("close") is None:
                continue
            pts.append((int(t / 1000), _f(c.get("open")), _f(c.get("high")), _f(c.get("low")), _f(c["close"]), _f(c.get("volume")) or 0))
        if pts:
            out[item.get("symbol")] = sorted(pts)
    return out


def benzinga_hourly(symbols, key, batch=25):
    """Hourly bars for one month, as {sym: [(ts, close, volume)]} (the shape pipeline.price_stats / volume_abn use)."""
    syms = sorted({s for s in symbols if is_equity_symbol(s)})
    chunks = [syms[i:i + batch] for i in range(0, len(syms), batch)]
    out = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda ch: _safe(lambda: _bz_bars(ch, key, "1MONTH", "1h"), {}), chunks):
            for s, pts in res.items():
                if len(pts) >= 10:
                    out[s] = [(t, c, v) for t, o, h, lo, c, v in pts]
    return out


def benzinga_daily(symbol, start, key):
    pts = _bz_bars([symbol], key, start, "1d").get(symbol, [])
    return [{"timestamp": t * 1000, "open": o, "hi": h, "lo": lo, "close": c, "volume": int(v or 0)} for t, o, h, lo, c, v in pts]


def benzinga_movers(key, n=100):
    """Top gainers, losers and most active of today's regular session, like sources.yahoo_movers."""
    rows = []
    q = urllib.parse.urlencode({"token": key, "maxResults": n, "session": "REGULAR"})
    res = (_get(f"{BZ}/v1/market/movers?{q}") or {}).get("result") or {}
    for lst, label in (("gainers", "gainer"), ("losers", "loser"), ("mostActive", "most active"), ("most_active", "most active")):
        for i, m in enumerate(res.get(lst) or [], 1):
            vol, avg = _f(m.get("volume")), _f(m.get("averageVolume"))
            rows.append(dict(list=label, list_rank=i, symbol=m.get("symbol"), name=m.get("companyName"), price=_f(m.get("price")),
                             change_pct=_f(m.get("changePercent")), volume=vol, avg_volume_3m=avg, market_cap=_f(m.get("marketCap")),
                             exchange=None, week52_change_pct=None, rel_volume=round(vol / avg, 2) if vol and avg else None,
                             sector=m.get("gicsSectorName")))
    return rows


def benzinga_earnings(today: dt.date, key, days=14):
    """Earnings reports from today on, like sources.nasdaq_earnings."""
    q = urllib.parse.urlencode({"token": key, "parameters[date_from]": today.isoformat(),
                                "parameters[date_to]": (today + dt.timedelta(days=days)).isoformat(), "pagesize": 1000})
    rows = []
    for r in (_get(f"{BZ}/v2.1/calendar/earnings?{q}") or {}).get("earnings") or []:
        rows.append(dict(date=r.get("date"), symbol=(r.get("ticker") or "").strip(), name=r.get("name"),
                         time=r.get("time"), market_cap=None, fiscal_quarter=f"{r.get('period')} {r.get('period_year')}",
                         eps_forecast=_f(r.get("eps_est")), n_estimates=None, last_year_date=None, last_year_eps=_f(r.get("eps_prior")),
                         revenue_forecast=_f(r.get("revenue_est")), importance=r.get("importance")))
    return [r for r in rows if r["symbol"]]


# ------------------------------------------------------------------ SEC (names of every US-listed company; public data)
def sec_tickers(contact_email):
    """SEC asks automated clients to name themselves with a contact email in the User-Agent (otherwise HTTP 403)."""
    if not contact_email:
        raise RuntimeError("SEC needs a contact email (settings: sec_contact)")
    d = _get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": f"MetrixxTopicLog {contact_email}"})
    rows = [dict(symbol=v.get("ticker", "").upper(), name=v.get("title"), price=None, change=None, change_pct=None, volume=None,
                 market_cap=None, sector=None, industry=None, country="United States", ipo_year=None, cik=v.get("cik_str"))
            for v in (d or {}).values()]
    return [r for r in rows if r["symbol"]]


# ------------------------------------------------------------------ Bigdata.com (RavenPack): prices by RP entity id
BD = "https://api.bigdata.com"
MICS = ("XNAS", "XNGS", "XNMS", "XNCM", "XNYS", "ARCX", "XASE", "BATS")
US_MIC = ("XN", "ARCX", "XASE", "BATS")
_bd_ids = {}


def _bd(path, key, body, timeout=60):
    req = urllib.request.Request(BD + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"X-API-KEY": key, "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Bigdata.com HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None


def bigdata_entities(symbols, key, cache: dict | None = None):
    """US tickers -> RavenPack entity ids (knowledge graph, by MIC:TICKER listing). cache: {sym: id or ""} kept by the caller."""
    cache = cache if cache is not None else _bd_ids
    todo = [s for s in {s for s in symbols if is_equity_symbol(s)} if s not in cache]
    vals = [f"{m}:{s}" for s in todo for m in MICS]
    for i in range(0, len(vals), 1000):
        res = (_bd("/v1/knowledge-graph/companies/listing", key, {"values": vals[i:i + 1000]}).get("results") or {})
        for lv, comp in res.items():
            if comp and comp.get("id"):
                cache.setdefault(lv.split(":", 1)[1], comp["id"])
    # not found as a company listing (ETFs, renamed listings): search ETFs, then companies, by ticker
    for s in [s for s in todo if s not in cache][:120]:
        for kind in ("etfs", "companies"):
            try:
                res = _bd(f"/v1/knowledge-graph/{kind}", key, {"query": s}).get("results") or []
            except Exception:
                res = []
            hit = next((x for x in res if x.get("ticker") == s or any(
                lv.split(":", 1)[1] == s and lv.startswith(US_MIC) for lv in (x.get("listing_values") or []) if ":" in lv)), None)
            if hit and hit.get("id"):
                cache[s] = hit["id"]
                break
    for s in todo:
        cache.setdefault(s, "")
    return {s: cache[s] for s in symbols if cache.get(s)}


def _rows(res):
    r = res.get("results")
    r = r[0] if isinstance(r, list) and r else r
    if not r:
        return []
    f = [x.upper() for x in r.get("fields") or []]
    return [dict(zip(f, v)) for v in r.get("values") or []]


def bigdata_daily(symbol, start, key, cache=None):
    """Daily candles from `start` (YYYY-MM-DD) to today, oldest first."""
    eid = bigdata_entities([symbol], key, cache).get(symbol)
    if not eid:
        return []
    rows = _rows(_bd("/v1/price/daily/query", key, {"identifier": {"type": "rp_entity_id", "value": eid},
                                                    "date_range": {"start": start, "end": dt.date.today().isoformat()}}))
    out = []
    for x in rows:
        d = dt.date.fromisoformat(str(x["DATE"])[:10])
        out.append({"timestamp": int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000), "open": _f(x.get("OPEN")),
                    "hi": _f(x.get("HIGH")), "lo": _f(x.get("LOW")), "close": _f(x.get("CLOSE")), "volume": int(_f(x.get("VOLUME")) or 0)})
    return sorted(out, key=lambda c: c["timestamp"])


def bigdata_hourly(symbols, key, cache=None, days=31, workers=6):
    """Hourly bars for about a month as {sym: [(ts, close, volume)]} (the shape pipeline.price_stats / volume_abn use).
    Bigdata times are exchange-local (New York)."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    ids = bigdata_entities(symbols, key, cache)
    start, end = (dt.date.today() - dt.timedelta(days=days)).isoformat(), (dt.date.today() + dt.timedelta(days=1)).isoformat()

    def one(item):
        sym, eid = item
        try:
            rows = _rows(_bd("/v1/price/intraday/query", key, {"identifier": {"type": "rp_entity_id", "value": eid},
                                                               "timestamp": {"start": start, "end": end}, "interval": "1hour"}))
        except Exception:
            return sym, None
        pts = []
        for x in rows:
            try:
                t = dt.datetime.fromisoformat(str(x["TIMESTAMP"])).replace(tzinfo=ny).timestamp()
            except Exception:
                continue
            if x.get("CLOSE") is not None:
                pts.append((int(t), _f(x["CLOSE"]), _f(x.get("VOLUME")) or 0))
        return sym, sorted(pts) if len(pts) >= 10 else None
    out = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for sym, pts in ex.map(one, ids.items()):
            if pts:
                out[sym] = pts
    return out


# ------------------------------------------------------------------ Binance public market data (no key)
def binance_daily(pair="BTCUSDT", days=365):
    """Daily klines from data-api.binance.vision (Binance's public market-data host)."""
    q = urllib.parse.urlencode({"symbol": pair, "interval": "1d", "limit": min(days, 1000)})
    rows = _get(f"https://data-api.binance.vision/api/v3/klines?{q}") or []
    return [{"timestamp": int(r[0]), "open": _f(r[1]), "hi": _f(r[2]), "lo": _f(r[3]), "close": _f(r[4]), "volume": int(_f(r[5]) or 0)}
            for r in rows]


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
