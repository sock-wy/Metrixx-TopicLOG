"""Step 3: prices for the price scenes, the facts the chart shows, and checks of the plan's numbers against the script."""
from __future__ import annotations

import datetime as dt
import re
import statistics
import sys
import urllib.parse

from .util import http

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[1].as_posix())


def _yahoo_daily(sym, start):
    p1 = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp())
    q = urllib.parse.urlencode({"period1": p1, "period2": int(dt.datetime.now(dt.timezone.utc).timestamp()), "interval": "1d"})
    d = http("GET", f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?{q}")
    r = d["chart"]["result"][0]
    q0 = r["indicators"]["quote"][0]
    off = r.get("meta", {}).get("gmtoffset", 0)
    out = []
    for t, o, h, lo, c, v in zip(r.get("timestamp") or [], q0["open"], q0["high"], q0["low"], q0["close"], q0["volume"]):
        if c is None:
            continue
        day = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date()
        ts = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
        out.append({"timestamp": ts, "open": round(o, 4), "hi": round(h, 4), "lo": round(lo, 4), "close": round(c, 4), "volume": int(v or 0)})
    return out


def candles(sym, start, keys):
    """Daily candles: Benzinga (US stocks / ETFs, with a key), Binance public data (crypto pairs), else Yahoo."""
    from dashboard import providers
    tried = []
    if sym.upper().endswith("-USD"):
        try:
            c = providers.binance_daily(sym.upper().replace("-USD", "USDT"), 1000)
            c = [x for x in c if x["timestamp"] >= _ms(start)]
            if c:
                return c, "Binance"
        except Exception as e:
            tried.append(f"Binance: {e}")
    if keys.get("bigdata_key") and providers.is_equity_symbol(sym):
        try:
            c = providers.bigdata_daily(sym, start, keys["bigdata_key"])
            if c:
                return c, "Bigdata.com"
        except Exception as e:
            tried.append(f"Bigdata.com: {e}")
    if keys.get("benzinga_key") and providers.is_equity_symbol(sym):
        try:
            c = providers.benzinga_daily(sym, start, keys["benzinga_key"])
            if c:
                return c, "Benzinga"
        except Exception as e:
            tried.append(f"Benzinga: {e}")
    try:
        return _yahoo_daily(sym, start), "Yahoo Finance"
    except Exception as e:
        tried.append(f"Yahoo: {e}")
    raise RuntimeError("; ".join(tried))


def _ms(day):
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def facts(cs, event_date):
    days = [dt.datetime.fromtimestamp(c["timestamp"] / 1000, dt.timezone.utc).date().isoformat() for c in cs]
    i = max([k for k, d in enumerate(days) if d <= event_date] or [len(cs) - 1])
    closes = [c["close"] for c in cs]
    rets = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
    f = {"date": days[i], "close": round(closes[i], 2)}
    if i >= 1:
        f["move_pct"] = round(rets[i - 1] * 100, 2)
    if i >= 22:
        sd = statistics.stdev(rets[i - 21:i - 1])
        f["sigma"] = round(abs(rets[i - 1]) / sd, 1) if sd else None
        vols = [c["volume"] for c in cs[i - 20:i] if c["volume"]]
        f["volume_vs_20d"] = round(cs[i]["volume"] / statistics.mean(vols), 1) if vols and cs[i]["volume"] else None
    prev_year = [c for c, d in zip(closes, days) if d[:4] < days[i][:4]]
    if prev_year:
        f["ytd_pct"] = round((closes[i] / prev_year[-1] - 1) * 100, 1)
    return f, cs[: i + 1 + 3]  # the chart ends a few days after the event


NUM = re.compile(r"[-+−]?\$?\d[\d,]*(?:\.\d+)?")


def _digits(s):
    return {re.sub(r"[^\d.]", "", m).strip(".") for m in NUM.findall(str(s).replace("−", "-")) if re.sub(r"[^\d]", "", m)}


def run(plan: dict, script: str, keys: dict, digest: dict | None = None) -> tuple[dict, list]:
    data, checks = {"prices": {}}, []
    for s in plan["scenes"]:
        if s["type"] != "price" or not s.get("ticker"):
            continue
        ev = s.get("event_date") or plan.get("date") or dt.date.today().isoformat()
        start = (dt.date.fromisoformat(ev) - dt.timedelta(days=int(s.get("days") or 130) * 1.6 + 45)).isoformat()
        try:
            cs, src = candles(s["ticker"], start, keys)
        except Exception as e:
            checks.append({"level": "error", "scene": s.get("kicker") or "price", "msg": f"No prices for {s['ticker']}: {e}"})
            continue
        f, cs = facts(cs, ev)
        f["source"] = src
        data["prices"][s["ticker"]] = {"candles": cs, "facts": f}
        s.setdefault("source", f"{src} daily prices, to {f['date']}")
        said = {abs(float(x)) for x in _digits(script) if x.replace(".", "").isdigit() and "." in x}
        if "move_pct" in f and not any(abs(abs(f["move_pct"]) - v) < 0.06 for v in said):
            near = [v for v in said if abs(abs(f["move_pct"]) - v) < 3]
            if near:
                checks.append({"level": "warn", "scene": "price", "msg": f"{s['ticker']} moved {f['move_pct']}% on {f['date']} (data); the script says {sorted(near)[0]}%."})
    # every number on screen should be in the script or the digest
    pool = _digits(script) | (_digits(__import__("json").dumps(digest)) if digest else set())
    for n in plan.get("numbers", []):
        ds = _digits(n.get("value"))
        if ds and not ds & pool:
            checks.append({"level": "warn", "scene": n.get("what", ""), "msg": f"{n.get('value')} ({n.get('what')}) is not in the script or the digest."})
    return data, checks
