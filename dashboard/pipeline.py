"""Topic Log dashboard pipeline (v2): one run = one pull.

    python -m dashboard.pipeline --state DIR --out DIR [--adanos-key KEY]      (from the repo root)

Topics and events
  A topic is what an episode is about (a company, coin, index, commodity, rate, FX pair, macro theme,
  private company or theme). An event is one concrete market or list entry under it: a Kalshi event,
  a Polymarket event, an Adanos trending entry, a Yahoo mover. Every item from every source is assigned
  to a topic automatically (dashboard/registry.py); items that match nothing become their own topic.

Universe = topics from Kalshi (Financials, Crypto, Commodities, Companies, Economics) + Polymarket
(money tags) + Adanos trending lists (Reddit, X, news; Reddit crypto) + Yahoo movers.

Source of record per signal (others only fill gaps or add to totals):
  money_flow   Kalshi 24h volume vs the pull 24h earlier; Polymarket 24h volume vs its 1-week daily average;
               combined weighted by each venue's 24h volume
  money_stock  open interest change vs the pull 24h earlier, Kalshi + Polymarket, weighted by open interest
  market_move  Kalshi |mid change 24h|, Polymarket |1-day price change|, weighted by 24h volume
  attention / activity / sentiment   Adanos Reddit, X and news (stocks) or Reddit (crypto): mean over platforms
  momentum     |24h price change| / daily volatility: Yahoo (stocks, indices, FX, commodities, rates),
               Binance > Coinbase > Kraken (crypto). Reported next to the score; weight 0 in w0.

Scoring is scoring/scoring.py with config/weights_w0.yaml, unchanged; G2 uses prediction-market evidence.
Every per-source input is written to topic_log so the page can recombine them with sources switched off.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import pathlib
import statistics
import time
import urllib.parse
import urllib.request
import zoneinfo

import yaml

from scoring import scoring
from . import archive, briefing, sources
from .registry import Registry, ensure
from .symbols import CATEGORIES, EXTRA, TOPICS, map_series, topic_info

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ET = zoneinfo.ZoneInfo("America/New_York")
UTC = dt.timezone.utc
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
ADANOS = "https://api.adanos.org"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/spark"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
UA = {"User-Agent": "Mozilla/5.0 (Metrixx TopicLog dashboard)"}
PULL_HOURS_ET = [7, 15, 23]  # cloud schedule since Oct 26 (was every 3 h)
HISTORY_DAYS, DAILY_DAYS, ADANOS_DAYS = 10, 45, 10
STOCK_PLATFORMS = ("reddit", "x", "news")
TICKER_ALIAS = {"GOOG": "GOOGL", "BRK/B": "BRK.B", "BRK-B": "BRK.B"}


# ------------------------------------------------------------------ helpers
def get_json(url, headers=None, tries=7, timeout=40):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r), dict(r.headers)
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (400, 401, 403, 404, 422):
                raise
            wait = int(e.headers.get("Retry-After") or 0) or min(30, 2 ** (i + 1))  # 429: back off 2, 4, 8, 16, 30 s
            time.sleep(min(wait, 30))
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    raise err


def f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def mid(b, a):
    if b is None or a is None or a <= 0 or a < b:
        return None
    return (a + b) / 2


def load(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def rnd(x, n=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


def pct(a, b):
    return (a / b - 1) * 100 if (a is not None and b) else None


def wmean(pairs):
    """Weighted mean of (value, weight) pairs with a value and a positive weight."""
    p = [(v, w) for v, w in pairs if v is not None and w and w > 0]
    s = sum(w for _, w in p)
    return sum(v * w for v, w in p) / s if s else None


def mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def trading_days_until(d0: dt.date, d1: dt.date) -> int:
    n, d = 0, d0
    while d < d1:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


# ------------------------------------------------------------------ Kalshi
def kalshi_pull():
    d, _ = get_json(f"{KALSHI}/series?limit=10000")
    series = {s["ticker"]: s for s in d.get("series", [])}
    events, cur = [], ""
    while True:
        u = f"{KALSHI}/events?status=open&with_nested_markets=true&limit=200" + (f"&cursor={cur}" if cur else "")
        d, _ = get_json(u)
        events += [e for e in d.get("events", []) if e.get("category") in CATEGORIES]
        cur = d.get("cursor")
        if not cur or not d.get("events"):
            break
    return series, events


def kalshi_topic(series_ticker, s, reg):
    """Topic for a Kalshi series: rules first, then free-text matching on its title, else its own ticker."""
    m = map_series(series_ticker, s.get("title", ""), s.get("tags"), s.get("category"))
    if m["mapped"]:
        return m["topic"], m["rule"]
    t, how, cls = reg.match(s.get("title", ""))
    if t:
        ensure(t, cls, reg.names.get(t))
        return t, "name"
    EXTRA.setdefault(m["topic"], (s.get("title") or m["topic"], m.get("fallback_class", "theme"), None, None))
    return m["topic"], "new"


def market_rows(events, series, now, reg):
    rows, smap = [], {}
    day_ago = now - dt.timedelta(hours=24)
    for e in events:
        st = e["series_ticker"]
        s = {**series.get(st, {}), "category": e.get("category") or series.get(st, {}).get("category")}
        if st not in smap:
            smap[st] = kalshi_topic(st, s, reg)
        topic, rule = smap[st]
        for m in e.get("markets", []):
            if m.get("status") not in ("active", "open"):
                continue
            b, a = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
            pb, pa = f(m.get("previous_yes_bid_dollars")), f(m.get("previous_yes_ask_dollars"))
            try:
                opened = dt.datetime.fromisoformat(m.get("open_time").replace("Z", "+00:00"))
            except Exception:
                opened = None
            close = m.get("close_time") or m.get("expected_expiration_time")
            try:
                close_dt = dt.datetime.fromisoformat(close.replace("Z", "+00:00"))
            except Exception:
                close_dt = None
            rows.append(dict(
                topic=topic, rule=rule, series=st, event=e["event_ticker"], event_title=e.get("title"),
                market=m["ticker"], category=e.get("category"), frequency=s.get("frequency"), tags=s.get("tags") or [],
                bid=b, ask=a, mid=mid(b, a), prev_mid=mid(pb, pa), last=f(m.get("last_price_dollars")),
                vol24=f(m.get("volume_24h_fp")) or 0.0, oi=f(m.get("open_interest_fp")) or 0.0,
                old=bool(opened and opened <= day_ago), close=close, close_dt=close_dt,
            ))
    return rows, smap


def kalshi_features(rows, now):
    """Per topic: 24h volume, open interest, market_move, G3 liquidity on the primary ladder, KPI catalysts."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["topic"]].append(r)
    today = now.astimezone(ET).date()
    out, events = {}, []
    for t, ms in by.items():
        live = [m for m in ms if m["mid"] is not None and 0.01 <= m["mid"] <= 0.99]  # G5
        ev = collections.defaultdict(list)
        for m in live:
            ev[m["event"]].append(m)
        prim = max(ev.values(), key=lambda g: (sum(x["vol24"] for x in g), len(g))) if ev else []
        quoted = [m for m in prim if m["ask"] - m["bid"] <= 0.5] or prim  # a 0.01/0.99 quote also has a 0.50 mid
        near = sorted(quoted, key=lambda m: abs(m["mid"] - 0.5))[:3]
        traded = [m for m in near if m["vol24"] > 0]
        spreads = [m["ask"] - m["bid"] for m in traded]

        def ok(m):
            return (m["old"] and m["prev_mid"] is not None and m["vol24"] > 0
                    and m["ask"] - m["bid"] <= 0.30 and 0.02 <= m["prev_mid"] <= 0.98)
        horizon = now + dt.timedelta(hours=24)
        cand = [m for m in live if ok(m)]
        longer = [m for m in cand if m["close_dt"] and m["close_dt"] > horizon]
        move = wmean([(abs(m["mid"] - m["prev_mid"]), m["vol24"]) for m in (longer or cand)])
        kpi = None
        for m in ms:
            if "KPIs" in m["tags"] and m["vol24"] > 0 and m["close_dt"]:
                cd = m["close_dt"].astimezone(ET).date()
                if cd >= today:
                    n = trading_days_until(today, cd)
                    kpi = n if kpi is None else min(kpi, n)
        out[t] = dict(
            k_vol=sum(m["vol24"] for m in ms), k_oi=sum(m["oi"] for m in ms), k_move=move,
            k_spread=(sum(spreads) / len(spreads)) if spreads else None,
            k_zero=(1 - len(traded) / len(near)) if near else None,
            k_evidence=any(m["vol24"] > 0 for m in ms), k_ladder=len(prim),
            n_series=len({m["series"] for m in ms}), n_markets=len(ms), kpi_days=kpi,
        )
        allev = collections.defaultdict(list)
        for m in ms:
            allev[m["event"]].append(m)
        for e, g in allev.items():
            q = [m for m in g if m["mid"] is not None]
            top = max(q, key=lambda m: m["vol24"]) if q else None
            cands = [m for m in g if ok(m)]
            events.append(dict(
                source="kalshi", event_id=e, title=g[0]["event_title"], topic=t, match=g[0]["rule"], series=g[0]["series"],
                volume_24h=round(sum(m["vol24"] for m in g), 2), open_interest=round(sum(m["oi"] for m in g), 2),
                n_markets=len(g), top_price=rnd(top["mid"]) if top else None,
                move_1d=rnd(wmean([(abs(m["mid"] - m["prev_mid"]), m["vol24"]) for m in cands])),
                end_date=(max((m["close"] or "") for m in g) or "")[:10] or None,
            ))
    return out, events


# ------------------------------------------------------------------ prices / momentum
def yahoo_prices(symbols):
    """Hourly bars for one month per symbol (Yahoo chart API): [(ts, close, volume)]."""
    import concurrent.futures as cf

    def one(sym):
        q = urllib.parse.urlencode({"range": "1mo", "interval": "1h", "includePrePost": "false"})
        try:
            d, _ = get_json(f"{YAHOO_CHART}{urllib.parse.quote(sym)}?{q}")
            r = d["chart"]["result"][0]
            qq = r["indicators"]["quote"][0]
            pts = [(t, c, v or 0) for t, c, v in zip(r.get("timestamp") or [], qq.get("close") or [], qq.get("volume") or []) if c is not None]
            return sym, pts if len(pts) >= 10 else None
        except Exception:
            return sym, None
    out = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for sym, pts in ex.map(one, sorted({s for s in symbols if s})):
            if pts:
                out[sym] = pts
    return out


def volume_abn(pts, now):
    """Volume traded so far in the latest session vs the same hours of the previous (up to 20) sessions, log ratio."""
    by = collections.defaultdict(list)
    for t, c, v in pts:
        if t + 3600 <= now.timestamp():  # completed bars only
            d = dt.datetime.fromtimestamp(t, ET)
            by[d.date()].append((d.hour + d.minute / 60, v))
    if len(by) < 6:
        return None
    days = sorted(by)
    last = days[-1]
    cut = max(h for h, _ in by[last])
    today = sum(v for h, v in by[last])
    base = [sum(v for h, v in by[d] if h <= cut) for d in days[-21:-1]]
    base = [b for b in base if b > 0]
    if today <= 0 or len(base) < 5:
        return None
    return math.log1p(today) - math.log1p(sum(base) / len(base))


def price_stats(pts, now):
    """Last price, 24h and 5d change, and the abnormal 24h move (z vs the month's daily moves)."""
    t_last, p_last = pts[-1][0], pts[-1][1]
    if now.timestamp() - t_last > 4 * 86400:
        return None

    def at(sec_ago):
        older = [p for t, p, *_ in pts if t <= t_last - sec_ago]
        return older[-1] if older else None
    p1, p5 = at(86400), at(5 * 86400)
    r1 = (p_last / p1 - 1) if p1 else None
    daily = {}
    for t, p, *_ in pts:
        daily[dt.datetime.fromtimestamp(t, UTC).date()] = p
    closes = [daily[k] for k in sorted(daily)]
    rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a]
    sd = statistics.pstdev(rets[:-1]) if len(rets) >= 8 else None
    return dict(price=p_last, price_ts=dt.datetime.fromtimestamp(t_last, UTC).isoformat(), chg_24h=r1,
                chg_5d=(p_last / p5 - 1) if p5 else None, vol_daily=sd, abnormal_move=(r1 / sd) if (r1 is not None and sd) else None)


def crypto_stats(row, closes, now):
    """Momentum for a coin from its source-of-record venue: 24h change over the daily volatility of the month."""
    if not row or not closes or len(closes) < 10:
        return None
    rets = [b[1] / a[1] - 1 for a, b in zip(closes, closes[1:]) if a[1]]
    sd = statistics.pstdev(rets[:-1]) if len(rets) >= 8 else None
    r1 = (row.get("change_pct") or 0) / 100 if row.get("change_pct") is not None else None
    p5 = closes[-6][1] if len(closes) >= 6 else None
    vols = [c[2] for c in closes[:-1] if len(c) > 2 and c[2]][-20:]
    v24 = row.get(f"{row.get('primary')}_vol")
    vab = (math.log1p(v24) - math.log1p(sum(vols) / len(vols))) if (v24 and len(vols) >= 5) else None
    return dict(price=row["price"], price_ts=now.isoformat(), chg_24h=r1, chg_5d=(row["price"] / p5 - 1) if p5 else None,
                vol_daily=sd, abnormal_move=(r1 / sd) if (r1 is not None and sd) else None, vol_abn=vab)


# ------------------------------------------------------------------ Adanos
def _adanos_get(key, path):
    d, hdr = get_json(f"{ADANOS}{path}", headers={"X-API-Key": key})
    hl = {k.lower(): v for k, v in hdr.items()}
    return d, hl.get("x-ratelimit-remaining-monthly")


def adanos_trending(key, cache, day, stat):
    """Top 100 per platform for one complete UTC day (stocks: Reddit, X, news; crypto: Reddit)."""
    have = {(r["date"], r["kind"], r.get("platform", "reddit")) for r in cache if r.get("trend_rank")}
    jobs = [("stocks", p) for p in STOCK_PLATFORMS] + [("crypto", "reddit")]
    for kind, plat in jobs:
        if (day, kind, plat) in have:
            continue
        try:
            d, left = _adanos_get(key, f"/{plat}/{kind}/v1/trending?from={day}&to={day}&limit=100")
            stat["calls"] += 1
            stat["quota_left"] = left or stat["quota_left"]
            items = d if isinstance(d, list) else d.get("stocks") or d.get("tokens") or []
            for rank, x in enumerate(items, 1):
                sym = (x.get("ticker") or x.get("symbol") or "").upper()
                if sym:
                    cache.append(dict(date=day, kind=kind, platform=plat, symbol=sym, trend_rank=rank,
                                      name=x.get("company_name") or x.get("name"), buzz_score=f(x.get("buzz_score")),
                                      mentions=f(x.get("mentions")), sentiment_score=f(x.get("sentiment_score"))))
        except Exception as e:
            stat["error"] = f"{type(e).__name__}: {e}"[:200]


def adanos_fill(key, cache, days, wanted, stat):
    """Make sure every (day, kind, platform, symbol) we need is cached, 10 symbols per /compare call."""
    have = {(r["date"], r["kind"], r.get("platform", "reddit"), r["symbol"]) for r in cache}
    for day in days:
        for kind, syms in wanted.items():
            plats = STOCK_PLATFORMS if kind == "stocks" else ("reddit",)
            for plat in plats:
                need = sorted({s for s in syms if (day, kind, plat, s) not in have})
                for i in range(0, len(need), 10):
                    chunk = need[i:i + 10]
                    arg = "tickers" if kind == "stocks" else "symbols"
                    try:
                        d, left = _adanos_get(key, f"/{plat}/{kind}/v1/compare?from={day}&to={day}&{arg}={urllib.parse.quote(','.join(chunk))}")
                        stat["calls"] += 1
                        stat["quota_left"] = left or stat["quota_left"]
                    except urllib.error.HTTPError as e:
                        if e.code == 422 and len(chunk) > 1:  # one symbol it cannot parse: ask one at a time
                            d = {"stocks": [], "tokens": []}
                            for sym1 in chunk:
                                try:
                                    d1_, _ = _adanos_get(key, f"/{plat}/{kind}/v1/compare?from={day}&to={day}&{arg}={urllib.parse.quote(sym1)}")
                                    stat["calls"] += 1
                                    d["stocks"] += d1_.get("stocks") or []
                                    d["tokens"] += d1_.get("tokens") or []
                                except Exception:
                                    pass
                        else:
                            stat["error"] = f"{type(e).__name__}: {e}"[:200]
                            continue
                    except Exception as e:
                        stat["error"] = f"{type(e).__name__}: {e}"[:200]
                        continue
                    got = set()
                    for x in d.get("stocks") or d.get("tokens") or []:
                        sym = (x.get("ticker") or x.get("symbol") or "").upper()
                        supported = bool(x.get("company_name") or x.get("name"))
                        got.add(sym)
                        cache.append(dict(date=day, kind=kind, platform=plat, symbol=sym, unsupported=not supported,
                                          buzz_score=f(x.get("buzz_score")) if supported else None,
                                          mentions=f(x.get("mentions")) if supported else None,
                                          sentiment_score=f(x.get("sentiment_score")) if supported else None))
                    for sym in set(chunk) - got:
                        cache.append(dict(date=day, kind=kind, platform=plat, symbol=sym, unsupported=True))
                    time.sleep(0.15)


RANGES = {  # window name -> (first day, last day) as offsets from d1 = t-1 (complete UTC days)
    "base": (-19, -1),   # t-20 .. t-2: the topic's normal level (attention, w1)
    "r3a": (-2, 0),      # t-3 .. t-1  (activity, w1: 3-day mentions vs the 3 days before)
    "r3b": (-5, -3),     # t-6 .. t-4
}


def adanos_ranges(key, cache, d1, wanted, stat):
    """Mentions totals over the RANGES windows, one /compare call per 10 symbols per window (cached per d1)."""
    have = {(r["date"], r.get("win"), r["kind"], r.get("platform"), r["symbol"]) for r in cache if r.get("win")}
    day = dt.date.fromisoformat(d1)
    for win, (a, b) in RANGES.items():
        lo, hi = (day + dt.timedelta(days=a)).isoformat(), (day + dt.timedelta(days=b)).isoformat()
        for kind, syms in wanted.items():
            for plat in (STOCK_PLATFORMS if kind == "stocks" else ("reddit",)):
                need = sorted({s_ for s_ in syms if (d1, win, kind, plat, s_) not in have})
                arg = "tickers" if kind == "stocks" else "symbols"
                for i in range(0, len(need), 10):
                    chunk = need[i:i + 10]
                    got = {}
                    for part in ([chunk] if len(chunk) else []):
                        try:
                            d, left = _adanos_get(key, f"/{plat}/{kind}/v1/compare?from={lo}&to={hi}&{arg}={urllib.parse.quote(','.join(part))}")
                            stat["calls"] += 1
                            stat["quota_left"] = left or stat["quota_left"]
                        except urllib.error.HTTPError as e:
                            if e.code != 422:
                                stat["error"] = f"{type(e).__name__}: {e}"[:200]
                                continue
                            d = {"stocks": [], "tokens": []}
                            for one in part:
                                try:
                                    d1_, _ = _adanos_get(key, f"/{plat}/{kind}/v1/compare?from={lo}&to={hi}&{arg}={urllib.parse.quote(one)}")
                                    stat["calls"] += 1
                                    d["stocks"] += d1_.get("stocks") or []
                                    d["tokens"] += d1_.get("tokens") or []
                                except Exception:
                                    pass
                        except Exception as e:
                            stat["error"] = f"{type(e).__name__}: {e}"[:200]
                            continue
                        days_n = d.get("period_days") or (b - a + 1)
                        for x in d.get("stocks") or d.get("tokens") or []:
                            if x.get("company_name") or x.get("name"):
                                got[(x.get("ticker") or x.get("symbol") or "").upper()] = (f(x.get("mentions")), days_n)
                    for sym in chunk:
                        m, n = got.get(sym, (None, None))
                        cache.append(dict(date=d1, win=win, kind=kind, platform=plat, symbol=sym, mentions=m, days=n))
                    time.sleep(0.15)


def adanos_platform_features(index, kind, sym, d1, d2, rindex=None):
    """Per platform: buzz Δ, mentions Δ%, sentiment Δ, and day t-1 levels."""
    out = {}
    plats = STOCK_PLATFORMS if kind == "stocks" else ("reddit",)
    for p in plats:
        a, b = index.get((d1, kind, p, sym)), index.get((d2, kind, p, sym))
        if not a or a.get("unsupported"):
            continue
        out[f"ad_buzz_{p}"] = a.get("buzz_score")
        out[f"ad_mentions_{p}"] = a.get("mentions")
        if b and not b.get("unsupported"):
            if a.get("buzz_score") is not None and b.get("buzz_score") is not None:
                out[f"ad_buzz_d_{p}"] = a["buzz_score"] - b["buzz_score"]
            if a.get("mentions") is not None and b.get("mentions"):
                out[f"ad_ment_chg_{p}"] = (a["mentions"] / b["mentions"] - 1) * 100
            if a.get("sentiment_score") is not None and b.get("sentiment_score") is not None:
                out[f"ad_sent_d_{p}"] = a["sentiment_score"] - b["sentiment_score"]
        if rindex is not None:
            base, ra, rb = (rindex.get((d1, w, kind, p, sym)) for w in ("base", "r3a", "r3b"))
            if base and base.get("mentions") is not None and base.get("days"):
                out[f"ad_base_{p}"] = base["mentions"] / base["days"]
            if ra and rb and ra.get("mentions") is not None and rb.get("mentions"):
                out[f"ad_ment3_chg_{p}"] = (ra["mentions"] / rb["mentions"] - 1) * 100
    return out


# ------------------------------------------------------------------ combine (mirrored in the page's JS)
def combine(r, on=None):
    """Per-component raw inputs from the per-source columns. `on` switches sources off (default: all on)."""
    on = on or {}
    k, p = on.get("kalshi", True), on.get("polymarket", True)
    plats = [x for x in STOCK_PLATFORMS if on.get(x, True)]
    flow = wmean([(r.get("k_flow"), r.get("k_vol")) if k else (None, 0), (r.get("p_flow"), r.get("p_vol")) if p else (None, 0)])
    stock = wmean([(r.get("k_oi_chg"), r.get("k_oi")) if k else (None, 0), (r.get("p_oi_chg"), r.get("p_oi")) if p else (None, 0)])
    move = wmean([(r.get("k_move"), r.get("k_vol")) if k else (None, 0), (r.get("p_move"), r.get("p_vol")) if p else (None, 0)])
    if on.get("attn_mode", "level") == "level":
        # w1: mentions on t-1 against the topic's own mean over t-20..t-2, all platforms switched on (log ratio)
        have = [x for x in plats if r.get(f"ad_base_{x}") is not None and r.get(f"ad_mentions_{x}") is not None]
        attn = (math.log1p(sum(r[f"ad_mentions_{x}"] for x in have)) - math.log1p(sum(r[f"ad_base_{x}"] for x in have))) if have else None
    else:  # w0: 1-day buzz change
        attn = mean([r.get(f"ad_buzz_d_{x}") for x in plats])
    if on.get("act_mode", "3d") == "3d":
        act = mean([r.get(f"ad_ment3_chg_{x}") for x in plats])
    else:
        act = mean([r.get(f"ad_ment_chg_{x}") for x in plats])
    sent = mean([abs(r[f"ad_sent_d_{x}"]) if r.get(f"ad_sent_d_{x}") is not None else None for x in plats])
    mom = abs(r["abnormal_move"]) if (on.get("momentum", True) and r.get("abnormal_move") is not None) else None
    # w2: mentions on X vs X's own 20-day normal; trading volume so far vs normal; open interest vs its 10-day normal
    attn_x = (math.log1p(r["ad_mentions_x"]) - math.log1p(r["ad_base_x"])) if (
        "x" in plats and r.get("ad_mentions_x") is not None and r.get("ad_base_x") is not None) else None
    vol_abn = r.get("vol_abn") if on.get("momentum", True) else None
    if on.get("stock_mode", "abn") == "abn":
        def _abn(v, b):
            return (math.log1p(v) - math.log1p(b)) if (v is not None and b is not None) else None
        stock = wmean([(_abn(r.get("k_oi"), r.get("k_oi_base")), r.get("k_oi")) if k else (None, 0),
                       (_abn(r.get("p_oi"), r.get("p_oi_base")), r.get("p_oi")) if p else (None, 0)])
    pm_ev = (k and r.get("k_evidence")) or (p and (r.get("p_vol") or 0) > 0)
    if (r.get("k_vol") or 0) >= (r.get("p_vol") or 0) and k and r.get("k_evidence") is not None:
        spread, zero = r.get("k_spread"), r.get("k_zero")
    elif p and r.get("p_vol"):
        spread, zero = r.get("p_spread"), None
    else:
        spread, zero = None, None
    fam = int(any(v is not None for v in (flow, stock, move))) + int(any(v is not None for v in (attn, act, sent)))
    return dict(money_flow=flow, money_stock=stock, market_move=move, attention_shift=attn, activity_shift=act,
                sentiment_shift=sent, momentum=mom, attention_x=attn_x, volume_abn=vol_abn, pm_evidence=bool(pm_ev), avg_spread=spread, zero_trade=zero, families=fam)


# ------------------------------------------------------------------ default ranking (w2; mirrors the page's recompute with the w2 preset)
WD = dict(version="w2",
          weights=dict(attention_shift=.35, attention_x=.35, volume_abn=.125, momentum=.125, money_stock=.05,
                       activity_shift=0, money_flow=0, market_move=0, sentiment_shift=0),
          g3_zero=.80, g3_spread=.30, t1_days=2, t1_pct=.70, t2_flow=.70, t2_attn=.50, t3_attn=.80)


def rank_default(rows):
    """w2 = backtest study v3: attention level (all platforms and X), abnormal trading volume, momentum, Kalshi/Polymarket
    open interest vs normal; missing inputs at the median; no quality multiplier; tiers as labels only.
    Same gates as the dashboard (G2 prediction-market volume, G3)."""
    live = []
    for r in rows:
        g = None
        if not r.get("pm_evidence"):
            g = "G2"
        elif r.get("zero_trade") is not None and r["zero_trade"] > WD["g3_zero"]:
            g = "G3"
        elif r.get("avg_spread") is not None and r["avg_spread"] > WD["g3_spread"]:
            g = "G3"
        r["pick_gate"], r["pick_score"], r["pick_rank"], r["pick_tier"] = g, None, None, None
        if not g:
            live.append(r)
    w = WD["weights"]
    pct = {c_: scoring.pctrank([r.get(c_) for r in live]) for c_ in set(w) | {"market_move", "money_flow", "attention_shift"}}
    for i, r in enumerate(live):
        # a missing input counts as the pool median (0.5), so a topic with one strong input and nothing else cannot top the list
        num = sum(w[c_] * (pct[c_][i] if pct[c_][i] is not None else 0.5) for c_ in w if w[c_] > 0)
        den = sum(w[c_] for c_ in w if w[c_] > 0)
        r["pick_score"] = num / den if den else 0.0
        pm, pf, pa = (pct[c_][i] or 0 for c_ in ("market_move", "money_flow", "attention_shift"))
        cat = r.get("catalyst_in_trading_days")
        r["pick_tier"] = ("T1" if cat is not None and cat <= WD["t1_days"] and (pm >= WD["t1_pct"] or pf >= WD["t1_pct"]) else
                          "T2" if pf >= WD["t2_flow"] and pa >= WD["t2_attn"] else "T3" if pa >= WD["t3_attn"] else "T4")
    live.sort(key=lambda r: (-r["pick_score"], -(r.get("families") or 0), -(r.get("k_ladder") or 0)))
    for k_, r in enumerate(live, 1):
        r["pick_rank"] = k_


# ------------------------------------------------------------------ history
def prior_pull(history, now, hours=24, tol=3.5):
    target = now - dt.timedelta(hours=hours)
    runs = sorted({h["run_ts"] for h in history})
    best = None
    for r in runs:
        gap = abs((dt.datetime.fromisoformat(r) - target).total_seconds()) / 3600
        if gap <= tol and (best is None or gap < best[0]):
            best = (gap, r)
    if not best:
        return None, {}
    return best[1], {h["topic"]: h for h in history if h["run_ts"] == best[1]}


# ------------------------------------------------------------------ run
def run(state: pathlib.Path, out: pathlib.Path, adanos_key=None, now=None):
    t0 = time.time()
    now = now or dt.datetime.now(UTC)
    now_et = now.astimezone(ET)
    today = now_et.date()
    run_ts = now.replace(microsecond=0).isoformat()
    cfg = scoring.load_config(ROOT / "config" / "weights_w0.yaml")
    cat_cfg = yaml.safe_load((HERE / "catalysts.yaml").read_text(encoding="utf-8"))
    macro_dates = sorted([(e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(e["date"]), e.get("type", "macro"))
                          for e in cat_cfg["events"]])
    macro_classes = set(cat_cfg["applies_to"]) | {"macro"}
    history = load(state / "score_history.json", [])
    daily = load(state / "daily_log.json", [])
    runs = load(state / "runs.json", [])
    ad_cache = load(state / "adanos_daily.json", [])
    for r in ad_cache:
        r.setdefault("platform", "reddit")
    steps = {}
    EXTRA.clear()

    # 1 · raw sources (registry first needs the stock and coin lists)
    raw, raw_status = sources.pull_all(today)
    coins = {c["symbol"]: c for c in raw["crypto_spot"]}
    us = {r["symbol"].strip().upper(): r for r in raw["us_stocks"] if r.get("symbol")}
    reg = Registry(raw["us_stocks"], list(coins))
    origins = collections.defaultdict(set)
    match_how = {}

    # 2 · Kalshi
    series, kevents = kalshi_pull()
    mrows, smap = market_rows(kevents, series, now, reg)
    kfeat, ev_rows = kalshi_features(mrows, now)
    for t in kfeat:
        origins[t].add("kalshi")
    for st, (t, how) in smap.items():
        match_how.setdefault(t, how)
    steps["kalshi"] = dict(status="ok", events=len(kevents), markets=len(mrows), topics=len(kfeat))

    # 3 · Polymarket events -> topics
    pfeat = collections.defaultdict(lambda: dict(p_vol=0.0, p_vol1wk=0.0, p_oi=0.0, moves=[], top=None, n=0))
    for e in raw["polymarket"]:
        tags = [x.strip() for x in (e.get("tags") or "").split(",") if x.strip()]
        t, how = reg.assign(e.get("title") or "", tags, new_id=f"PM{e['event_id']}")
        e["topic"], e["match"] = t, how
        origins[t].add("polymarket")
        match_how.setdefault(t, how)
        a = pfeat[t]
        a["p_vol"] += e.get("volume_24h") or 0
        a["p_vol1wk"] += e.get("volume_1wk") or 0
        a["p_oi"] += e.get("open_interest") or 0
        a["moves"].append((e.get("move_1d"), e.get("volume_24h") or 0))
        a["n"] += 1
        if a["top"] is None or (e.get("volume_24h") or 0) > (a["top"].get("volume_24h") or 0):
            a["top"] = e
        ev_rows.append(dict(source="polymarket", event_id=e["event_id"], title=e.get("title"), topic=t, match=how,
                            series=None, volume_24h=rnd(e.get("volume_24h"), 2), open_interest=rnd(e.get("open_interest"), 2),
                            n_markets=e.get("n_markets"), top_price=e.get("top_price"), move_1d=e.get("move_1d"),
                            end_date=e.get("end_date"), slug=e.get("slug")))

    # 4 · Adanos trending + movers add topics; then fill Adanos metrics for every topic that has a symbol
    d1 = (now.astimezone(UTC).date() - dt.timedelta(days=1)).isoformat()
    d2 = (now.astimezone(UTC).date() - dt.timedelta(days=2)).isoformat()
    ad_stat = dict(status="no key", calls=0, quota_left=None, error=None)
    ad_rev = {}
    for t, (n, ac, yh, ad) in TOPICS.items():
        if ad and ac != "equity" and (ad[0], ad[1]) not in ad_rev:
            ad_rev[(ad[0], ad[1])] = t
    if adanos_key:
        adanos_trending(adanos_key, ad_cache, d1, ad_stat)
    for r in ad_cache:
        if r.get("trend_rank") and r["date"] == d1:
            sym = TICKER_ALIAS.get(r["symbol"], r["symbol"])
            t = ad_rev.get((r["kind"], sym))
            if not t:
                if r["kind"] == "crypto":
                    t = sym
                    ensure(t, "crypto", r.get("name"))
                else:
                    t = reg.tickers.get(sym, sym)
                    ensure(t, "equity", reg.names.get(sym) or r.get("name"))
            origins[t].add("adanos")
            match_how.setdefault(t, "ticker")
    for m in raw["us_movers"]:
        sym = TICKER_ALIAS.get((m.get("symbol") or "").upper(), (m.get("symbol") or "").upper())
        if sym:
            sym = reg.tickers.get(sym, sym)
            ensure(sym, "equity", reg.names.get(sym) or m.get("name"))
            origins[sym].add("movers")
            match_how.setdefault(sym, "ticker")
            ev_rows.append(dict(source="yahoo_movers", event_id=f"{m['list']}:{sym}", title=f"{m.get('name')} · {m['list']} #{m['list_rank']}",
                                topic=sym, match="ticker", volume_24h=None, open_interest=None, n_markets=None,
                                top_price=m.get("price"), move_1d=rnd((m.get("change_pct") or 0) / 100), end_date=None))
    topics = sorted(origins)
    infos = {t: topic_info(t) for t in topics}
    wanted = collections.defaultdict(set)
    for t, i in infos.items():
        if i["adanos_symbol"]:
            wanted[i["adanos_kind"]].add(i["adanos_symbol"].upper())
    if adanos_key:
        before = ad_stat["calls"]
        adanos_fill(adanos_key, ad_cache, [d1, d2], wanted, ad_stat)
        adanos_ranges(adanos_key, ad_cache, d1, wanted, ad_stat)
        ad_stat["status"] = "error" if ad_stat["error"] and ad_stat["calls"] == before else ("fetched" if ad_stat["calls"] else "cached")
    keep = (now.astimezone(UTC).date() - dt.timedelta(days=ADANOS_DAYS)).isoformat()
    ad_cache = [r for r in ad_cache if r["date"] >= keep]
    ad_index = {(r["date"], r["kind"], r.get("platform", "reddit"), r["symbol"]): r for r in ad_cache if not r.get("trend_rank") and not r.get("win")}
    ad_rindex = {(r["date"], r["win"], r["kind"], r["platform"], r["symbol"]): r for r in ad_cache if r.get("win")}
    for r in ad_cache:  # trending rows also carry the metrics
        if r.get("trend_rank"):
            ad_index.setdefault((r["date"], r["kind"], r["platform"], r["symbol"]), r)
    steps["adanos"] = ad_stat

    # 5 · prices: Yahoo for listed non-crypto, source-of-record venue for crypto
    ysyms = {i["price_symbol"] for i in infos.values() if i["price_symbol"] and i["asset_class"] != "crypto"}
    px = yahoo_prices(ysyms)
    pstats = {}
    for t, i in infos.items():
        if i["asset_class"] == "crypto":
            c = coins.get(t)
            if c:
                closes = sources.crypto_daily(t, c["primary"], c.get("kraken_pair"))
                pstats[t] = crypto_stats(c, closes, now)
                if pstats[t]:
                    pstats[t]["price_source"] = c["primary"]
                time.sleep(0.05)
        elif i["price_symbol"] in px:
            pstats[t] = price_stats(px[i["price_symbol"]], now)
            if pstats[t]:
                pstats[t]["price_source"] = "yahoo"
                pstats[t]["vol_abn"] = volume_abn(px[i["price_symbol"]], now)
    steps["prices"] = dict(status="ok" if pstats else "error", symbols=sum(1 for v in pstats.values() if v))

    # 6 · catalysts: macro calendar, Kalshi KPI markets, Nasdaq earnings
    earn = {}
    for e in raw["earnings_calendar"]:
        dd = dt.date.fromisoformat(e["date"])
        if dd >= today:
            n = trading_days_until(today, dd)
            s = (e.get("symbol") or "").upper()
            if s and (s not in earn or n < earn[s][0]):
                earn[s] = (n, e["date"])

    # 7 · assemble one row per topic
    prev_ts, prev = prior_pull(history, now)
    vol_hist = collections.defaultdict(list)
    for r in sorted(daily, key=lambda r: r["date"]):
        if r.get("k_vol") is not None:
            vol_hist[r["topic"]].append(r["k_vol"])
    # open-interest baseline: mean over earlier pulls (at least 20h old, up to the 10 days kept), per day first
    oi_base = collections.defaultdict(lambda: {"k": {}, "p": {}})
    cutoff_ts = (now - dt.timedelta(hours=20)).isoformat()
    for h in history:
        if h["run_ts"] < cutoff_ts:
            day_ = h["run_ts"][:10]
            for src, key in (("k", "k_oi"), ("p", "p_oi")):
                if h.get(key) is not None:
                    oi_base[h["topic"]][src].setdefault(day_, h[key])
    rows = []
    for t in topics:
        i = infos[t]
        ob = oi_base.get(t)
        r = dict(i, ticker=t, origin=",".join(sorted(origins[t])), match=match_how.get(t),
                 is_new=match_how.get(t) == "new")
        k = kfeat.get(t)
        if k:
            r.update(k)
        pf = pfeat.get(t)
        if pf:
            r.update(p_vol=pf["p_vol"], p_vol1wk=pf["p_vol1wk"], p_oi=pf["p_oi"], p_move=wmean(pf["moves"]),
                     p_spread=(pf["top"] or {}).get("top_spread"), n_pm_events=pf["n"],
                     p_flow=((pf["p_vol"] / (pf["p_vol1wk"] / 7) - 1) * 100) if pf["p_vol1wk"] > 0 else None)
        if ob:
            for src, key in (("k", "k_oi_base"), ("p", "p_oi_base")):
                vals = list(ob[src].values())
                if len(vals) >= 3:
                    r[key] = sum(vals) / len(vals)
        pv = prev.get(t)
        if pv:
            pk_vol = pv.get("k_vol", pv.get("mkt_volume_24h"))
            pk_oi = pv.get("k_oi", pv.get("mkt_open_interest"))
            if k and pk_vol is not None:
                r["k_flow"] = pct(k["k_vol"], pk_vol)
                hist = vol_hist[t][-30:]
                if len(hist) >= 10:  # playbook v2 volume floor
                    floor = sorted(hist)[max(0, int(math.ceil(0.10 * len(hist))) - 1)]
                    if pk_vol < floor:
                        r["k_flow"], r["money_flow_floored"] = None, True
            if k and pk_oi is not None:
                r["k_oi_chg"] = pct(k["k_oi"], pk_oi)
            if pf and pv.get("p_oi") is not None:
                r["p_oi_chg"] = pct(pf["p_oi"], pv["p_oi"])
        if i["adanos_symbol"]:
            r.update(adanos_platform_features(ad_index, i["adanos_kind"], i["adanos_symbol"].upper(), d1, d2, ad_rindex))
        ps = pstats.get(t)
        if ps:
            r.update(ps)
        if t in us:
            r["exchange_volume_usd"] = (us[t].get("volume") or 0) * (us[t].get("price") or 0)
        elif t in coins:
            r["exchange_volume_usd"] = coins[t].get("usd_volume")
            r["on_coinbase"], r["on_kraken"] = coins[t].get("on_coinbase"), coins[t].get("on_kraken")
        cats = []
        if i["asset_class"] in macro_classes:
            nxt = next(((d, typ) for d, typ in macro_dates if d >= today), None)
            if nxt:
                cats.append((trading_days_until(today, nxt[0]), f"{nxt[1]} {nxt[0]:%b %-d}"))
        if k and k.get("kpi_days") is not None:
            cats.append((k["kpi_days"], "KPI market resolves"))
        if t in earn and i["asset_class"] == "equity":
            cats.append((earn[t][0], f"earnings {earn[t][1][5:]}"))
        if cats:
            n, kind = min(cats)
            r["catalyst_in_trading_days"], r["catalyst"] = n, kind
        c = combine(r)  # w1 inputs (shown in the topic log)
        r.update(c)
        c = combine(r, {"attn_mode": "change", "act_mode": "1d", "stock_mode": "chg"})
        r["w0_money_stock"] = c["money_stock"]
        r["w0_attention_shift"], r["w0_activity_shift"] = c["attention_shift"], c["activity_shift"]
        # inputs for scoring.score_day (w0)
        r["buzz_delta_1d"], r["trade_count_pct_change_1d"] = c["attention_shift"], c["activity_shift"]
        r["mkt_volume_delta_1d"], r["mkt_oi_delta_1d"] = c["money_flow"], c["money_stock"]
        r["mkt_prob_delta_1d"], r["mkt_prob_range_1d"] = c["market_move"], None
        r["sentiment_delta_1d"] = c["sentiment_shift"]
        r["has_market_evidence"] = c["pm_evidence"]
        r["zero_trade_market_pct"] = c["zero_trade"]
        r["sources_available"] = max(1, c["families"])
        r["days_since_covered"] = None
        r["mkt_ladder_depth"] = r.get("k_ladder") or 0
        rows.append(r)

    ranked, gated = scoring.score_day(rows, cfg)
    mom = scoring.pctrank([r.get("momentum") for r in ranked])
    order = sorted([i for i, v in enumerate(mom) if v is not None], key=lambda i: -ranked[i]["momentum"])
    for kk, i in enumerate(order, 1):
        ranked[i]["momentum_rank"] = kk
    for r, m in zip(ranked, mom):
        r["momentum_pct"] = m
    rank_default(ranked + gated)
    steps["score"] = dict(scored=len(ranked), gated=len(gated), prior_pull=prev_ts,
                          scored_pick=sum(1 for r in ranked + gated if r.get("pick_rank")))

    # 8 · outputs
    comp = scoring.COMPONENTS
    keep_cols = ["k_vol", "k_flow", "k_oi", "k_oi_chg", "k_move", "k_spread", "k_zero", "k_evidence", "k_ladder",
                 "p_vol", "p_vol1wk", "p_flow", "p_oi", "p_oi_chg", "p_move", "p_spread", "n_pm_events",
                 *[f"ad_{m}_{p}" for p in STOCK_PLATFORMS for m in ("buzz", "mentions", "buzz_d", "ment_chg", "sent_d", "base", "ment3_chg")],
                 "w0_attention_shift", "w0_activity_shift", "pick_score", "pick_rank", "pick_tier", "pick_gate",
                 "attention_x", "volume_abn", "vol_abn", "k_oi_base", "p_oi_base",
                 "abnormal_move", "price", "chg_24h", "chg_5d", "price_source", "exchange_volume_usd", "on_coinbase", "on_kraken",
                 "money_flow", "money_stock", "market_move", "attention_shift", "activity_shift", "sentiment_shift", "momentum",
                 "pm_evidence", "avg_spread", "zero_trade", "families", "catalyst_in_trading_days", "catalyst",
                 "n_series", "n_markets", "days_since_covered", "money_flow_floored"]
    out_rows = []
    for r in ranked + gated:
        pctl = r.get("pct") or {}
        row = {"run_ts": run_ts, "rank": r.get("rank"), "topic": r["topic"], "name": r["name"], "asset_class": r["asset_class"],
               "origin": r["origin"], "match": r["match"], "is_new": r["is_new"], "tier": r.get("tier"),
               "gate": r.get("data_quality_flag"), "demand_score": rnd(r.get("demand_score")), "raw_score": rnd(r.get("raw_score")),
               "quality": rnd(r.get("quality")), "momentum_pct": rnd(r.get("momentum_pct")), "momentum_rank": r.get("momentum_rank"),
               **{f"p_{c_}": rnd(pctl.get(c_)) for c_ in comp}, "weights_version": cfg["version"]}
        for c_ in keep_cols:
            v = r.get(c_)
            row[c_] = rnd(v, 6) if isinstance(v, float) else v
        out_rows.append(row)
    out_rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -(r.get("k_vol") or 0) - (r.get("p_vol") or 0)))
    n_events = collections.Counter(e["topic"] for e in ev_rows)
    for r in out_rows:
        r["n_events"] = n_events.get(r["topic"], 0)

    keep_ts = (now - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    history = [h for h in history if h["run_ts"] >= keep_ts and h["run_ts"] != run_ts]
    history += [dict(run_ts=run_ts, topic=r["topic"], rank=r["rank"], tier=r["tier"], demand_score=r["demand_score"],
                     pick_rank=r.get("pick_rank"), pick_score=r.get("pick_score"),
                     momentum_pct=r["momentum_pct"], k_vol=r["k_vol"], k_oi=r["k_oi"], p_vol=r["p_vol"], p_oi=r["p_oi"],
                     gate=r["gate"]) for r in out_rows]
    d = today.isoformat()
    if now_et.hour >= 15 and not any(r["date"] == d for r in daily):  # first pull at or after the 15:00 ET pick
        daily += [dict(date=d, **{k_: r.get(k_) for k_ in ("rank", "pick_rank", "pick_score", "pick_tier", "topic", "name", "asset_class", "tier", "gate", "demand_score",
                                                          "momentum_pct", "momentum_rank", "k_vol", "p_vol", "abnormal_move", "chg_24h")})
                  for r in out_rows]
        keep_d = (today - dt.timedelta(days=DAILY_DAYS)).isoformat()
        daily = [r for r in daily if r["date"] >= keep_d]

    by_series = collections.defaultdict(lambda: dict(markets=0, vol24=0.0, oi=0.0, events=set()))
    for m in mrows:
        b = by_series[m["series"]]
        b["markets"] += 1
        b["vol24"] += m["vol24"]
        b["oi"] += m["oi"]
        b["events"].add(m["event"])
    appendix = []
    for sname, b in by_series.items():
        s = series.get(sname, {})
        t, how = smap.get(sname, (sname, "?"))
        info = topic_info(t)
        appendix.append(dict(series=sname, title=s.get("title"), category=s.get("category"), frequency=s.get("frequency"),
                             tags=", ".join(s.get("tags") or []), topic=t, topic_name=info["name"], asset_class=info["asset_class"],
                             mapped=how != "new", rule=how, price_symbol=info["price_symbol"],
                             adanos=f'{info["adanos_kind"]}:{info["adanos_symbol"]}' if info["adanos_symbol"] else None,
                             open_events=len(b["events"]), open_markets=b["markets"], volume_24h=round(b["vol24"]), open_interest=round(b["oi"])))
    appendix.sort(key=lambda r: -r["volume_24h"])

    mkt = []
    for t, ps in pstats.items():
        if ps:
            i = infos[t]
            mkt.append(dict(topic=t, name=i["name"], asset_class=i["asset_class"],
                            symbol=i["price_symbol"] if ps.get("price_source") == "yahoo" else f"{t} ({ps.get('price_source')})",
                            price=rnd(ps["price"], 6), price_ts=ps["price_ts"], chg_24h=rnd(ps["chg_24h"]), chg_5d=rnd(ps["chg_5d"]),
                            vol_daily=rnd(ps["vol_daily"]), abnormal_move=rnd(ps["abnormal_move"], 2),
                            kalshi_volume_24h=round((kfeat.get(t) or {}).get("k_vol") or 0),
                            polymarket_volume_24h=round((pfeat.get(t) or {}).get("p_vol") or 0) if t in pfeat else 0))
    mkt.sort(key=lambda r: -abs(r["abnormal_move"] or 0))

    for e in raw["polymarket"]:  # the raw table shows where each event went
        e.setdefault("topic", None)
    top = next((r for r in out_rows if r["rank"] == 1), None)
    mtop = next((r for r in out_rows if r.get("momentum_rank") == 1), None)
    oc = collections.Counter(o for r in out_rows for o in r["origin"].split(","))
    runs = [r for r in runs if r["run_ts"] != run_ts]
    runs.append(dict(
        run_ts=run_ts, run_et=now_et.strftime("%Y-%m-%d %H:%M"),
        pull_hour_et=min(PULL_HOURS_ET, key=lambda h: min(abs(now_et.hour + now_et.minute / 60 - h), 24 - abs(now_et.hour + now_et.minute / 60 - h))),
        kalshi="ok", kalshi_markets=steps["kalshi"]["markets"], topics=len(out_rows),
        topics_kalshi=oc.get("kalshi", 0), topics_polymarket=oc.get("polymarket", 0), topics_adanos=oc.get("adanos", 0),
        topics_movers=oc.get("movers", 0), topics_new=sum(1 for r in out_rows if r["is_new"]),
        adanos=ad_stat["status"], adanos_calls=ad_stat["calls"], adanos_quota_left=ad_stat.get("quota_left"), adanos_error=ad_stat.get("error"),
        prices=steps["prices"]["status"], priced=steps["prices"]["symbols"],
        scored=len(ranked), gated=len(gated), prior_pull=prev_ts,
        top_topic=top["topic"] if top else None, top_tier=top["tier"] if top else None, top_score=top["demand_score"] if top else None,
        momentum_top=mtop["topic"] if mtop else None,
        pick_top=next((r["topic"] for r in out_rows if r.get("pick_rank") == 1), None), pick_version=WD["version"],
        **{f"{st['dataset']}_status": st["status"] for st in raw_status},
        **{f"{st['dataset']}_rows": st["rows"] for st in raw_status},
        **{f"{st['dataset']}_error": st["error"] for st in raw_status if st["error"]},
        coinbase_usd_pairs=next((st.get("coinbase_usd_pairs") for st in raw_status if st["dataset"] == "crypto_spot"), None),
        kraken_usd_pairs=next((st.get("kraken_usd_pairs") for st in raw_status if st["dataset"] == "crypto_spot"), None),
        seconds=round(time.time() - t0, 1),
    ))
    runs = runs[-240:]

    out.mkdir(parents=True, exist_ok=True)
    # agenda 3-5: Kalshi perps, venue appendix, Adanos sectors and news, briefing (never fails the pull)
    extra = {"kalshi_perps": [], "venue_appendix": [], "sectors": [], "news": [], "briefing": []}
    perps_raw, perps_st = archive.kalshi_perps(now)
    br_stat = {}
    try:
        extra["kalshi_perps"] = briefing.perps_rows(perps_raw if perps_st == "ok" else None, lambda t, c: ensure(t, c))
        extra["venue_appendix"] = briefing.venue_appendix(out_rows, ev_rows, extra["kalshi_perps"], coins, infos)
        if adanos_key:
            extra["sectors"] = briefing.sectors(adanos_key, d1, d2, br_stat)
            picks = [(r["topic"], (infos.get(r["topic"]) or {}).get("adanos_symbol"), r.get("name"))
                     for r in sorted((x for x in out_rows if x.get("pick_rank")), key=lambda x: x["pick_rank"])
                     if (infos.get(r["topic"]) or {}).get("adanos_kind") == "stocks"][:15]
            extra["news"] = briefing.news(adanos_key, [p_ for p_ in picks if p_[1]], br_stat)
        top = sorted((x for x in out_rows if x.get("pick_rank")), key=lambda x: x["pick_rank"])
        extra["briefing"] = briefing.auto_briefing(today.isoformat(), extra["sectors"], extra["news"], top)
    except Exception as e:
        br_stat["error"] = f"{type(e).__name__}: {e}"[:200]
    runs[-1].update(perps=perps_st, perps_rows=len(extra["kalshi_perps"]), sectors_rows=len(extra["sectors"]),
                    news_rows=len(extra["news"]), briefing_calls=br_stat.get("calls", 0), briefing_error=br_stat.get("error"))
    try:  # permanent archive (never fails the pull)
        arc = archive.write(out, state, now, now_et, run_ts, mrows=mrows, raw=raw, topic_log=out_rows, events=ev_rows,
                            adanos_key=adanos_key, ad_stat=ad_stat, runs=runs[:-1], perps=perps_raw if perps_st == "ok" else None)
    except Exception as e:
        arc = {"archive_files": 0, "archive_error": f"{type(e).__name__}: {e}"[:200]}
    runs[-1].update(arc)
    files = dict(topic_log=out_rows, events=ev_rows, score_history=history, daily_log=daily, runs=runs, adanos_daily=ad_cache,
                 symbol_appendix=appendix, market_data=mkt, **raw, **extra)
    for k_, v in files.items():
        (out / f"{k_}.json").write_text(json.dumps(v, separators=(",", ":"), default=str))
    return runs[-1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--adanos-key", default=None)
    a = ap.parse_args()
    import os
    print(json.dumps(run(a.state, a.out, a.adanos_key or os.environ.get("ADANOS_KEY")), indent=1))
