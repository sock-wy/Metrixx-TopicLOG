"""Topic Log dashboard pipeline: one run = one of the eight daily pulls.

    python -m dashboard.pipeline --state DIR --out DIR [--adanos-key KEY]      (from the repo root)

Reads the previous run's files from --state (any may be missing on the first run):
    score_history.json  adanos_daily.json  daily_log.json  runs.json
Writes every dashboard dataset to --out:
    topic_log.json      latest ranking, one row per topic (Sheet 2 for this pull)
    score_history.json  per pull per topic, last 10 days (feeds deltas and charts)
    daily_log.json      the 15:00 ET pull of each day, last 45 days (the daily pick record)
    runs.json           one row per pull with the status of each step
    adanos_daily.json   Adanos Reddit metrics per UTC day, last 21 days
    symbol_appendix.json  every open Kalshi series -> topic
    market_data.json    price, 24h / 5d change and abnormal move per priced topic
  raw tables from the free sources (dashboard/sources.py), not scored yet:
    us_stocks.json  earnings_calendar.json  us_movers.json  polymarket.json  crypto_spot.json

Scoring is scoring/scoring.py with config/weights_w0.yaml, unchanged. Momentum is reported next to it, never inside it.
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
from . import sources
from .symbols import CATEGORIES, map_series, topic_info

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ET = zoneinfo.ZoneInfo("America/New_York")
UTC = dt.timezone.utc
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
ADANOS = "https://api.adanos.org"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/spark"
UA = {"User-Agent": "Mozilla/5.0 (Metrixx TopicLog dashboard)"}
PULL_HOURS_ET = [15, 18, 21, 0, 3, 6, 9, 12]
HISTORY_DAYS, DAILY_DAYS, ADANOS_DAYS = 10, 45, 21


# ------------------------------------------------------------------ http
def get_json(url, headers=None, tries=4, timeout=40):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r), dict(r.headers)
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (401, 403, 404, 422):
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 2 * (i + 1)
            time.sleep(min(wait, 30))
        except Exception as e:  # network hiccup
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
        return json.loads(pathlib.Path(path).read_text())
    except Exception:
        return default


# ------------------------------------------------------------------ kalshi
def kalshi_pull():
    series, cur = [], ""
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


def market_rows(events, series, now):
    rows = []
    day_ago = now - dt.timedelta(hours=24)
    for e in events:
        s = series.get(e["series_ticker"], {})
        m_s = map_series(e["series_ticker"], s.get("title", ""), s.get("tags"))
        for m in e.get("markets", []):
            if m.get("status") not in ("active", "open"):
                continue
            b, a = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
            pb, pa = f(m.get("previous_yes_bid_dollars")), f(m.get("previous_yes_ask_dollars"))
            opened = m.get("open_time")
            try:
                opened = dt.datetime.fromisoformat(opened.replace("Z", "+00:00"))
            except Exception:
                opened = None
            close = m.get("close_time") or m.get("expected_expiration_time")
            try:
                close_dt = dt.datetime.fromisoformat(close.replace("Z", "+00:00"))
            except Exception:
                close_dt = None
            rows.append(dict(
                topic=m_s["topic"], series=e["series_ticker"], event=e["event_ticker"], market=m["ticker"],
                category=e.get("category"), frequency=s.get("frequency"), tags=s.get("tags") or [],
                bid=b, ask=a, mid=mid(b, a), prev_mid=mid(pb, pa),
                vol24=f(m.get("volume_24h_fp")) or 0.0, oi=f(m.get("open_interest_fp")) or 0.0,
                old=bool(opened and opened <= day_ago), close=close, close_dt=close_dt,
            ))
    return rows


def trading_days_until(d0: dt.date, d1: dt.date) -> int:
    n, d = 0, d0
    while d < d1:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def topic_features(rows, now, catalysts):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["topic"]].append(r)
    today = now.astimezone(ET).date()
    out = {}
    for t, ms in by.items():
        info = topic_info(t)
        vol = sum(m["vol24"] for m in ms)
        oi = sum(m["oi"] for m in ms)
        live = [m for m in ms if m["mid"] is not None and 0.01 <= m["mid"] <= 0.99]  # G5
        # primary ladder: the event with most 24h volume
        ev = collections.defaultdict(list)
        for m in live:
            ev[m["event"]].append(m)
        prim = max(ev.values(), key=lambda g: (sum(x["vol24"] for x in g), len(g))) if ev else []
        # v2 / proposed w1: the 3 strikes nearest the implied median. A one-sided 0.01/0.99 quote
        # also has a mid of 0.50, so look for the median among two-sided quotes first.
        quoted = [m for m in prim if m["ask"] - m["bid"] <= 0.5] or prim
        near = sorted(quoted, key=lambda m: abs(m["mid"] - 0.5))[:3]
        traded = [m for m in near if m["vol24"] > 0]
        spreads = [m["ask"] - m["bid"] for m in traded]
        # market_move: volume-weighted |mid change over 24h| on traded, two-sided markets that existed
        # 24h ago. Markets closing within 24h are used only when nothing longer exists, because their
        # prices drift to 0/1 as expiry nears (time decay, not a change of mind).
        def ok(m):
            return (m["old"] and m["prev_mid"] is not None and m["vol24"] > 0
                    and m["ask"] - m["bid"] <= 0.30 and 0.02 <= m["prev_mid"] <= 0.98)
        horizon = now + dt.timedelta(hours=24)
        cand = [m for m in live if ok(m)]
        longer = [m for m in cand if m["close_dt"] and m["close_dt"] > horizon]
        mv = [(abs(m["mid"] - m["prev_mid"]), m["vol24"]) for m in (longer or cand)]
        wsum = sum(w for _, w in mv)
        move = sum(x * w for x, w in mv) / wsum if wsum else None
        # catalyst: macro calendar (index/rates/fx) or a company KPI market resolving soon
        cat = None
        if info["asset_class"] in catalysts["applies_to"]:
            ds = [trading_days_until(today, d) for d in catalysts["dates"] if d >= today]
            cat = min(ds) if ds else None
        kpi = [m for m in ms if "KPIs" in m["tags"] and m["vol24"] > 0 and m["close"]]
        for m in kpi:
            try:
                cd = dt.datetime.fromisoformat(m["close"].replace("Z", "+00:00")).astimezone(ET).date()
            except Exception:
                continue
            if cd >= today:
                n = trading_days_until(today, cd)
                cat = n if cat is None else min(cat, n)
        top_ev = max(ev.items(), key=lambda kv: sum(x["vol24"] for x in kv[1]))[0] if ev else None
        out[t] = dict(
            **info,
            n_series=len({m["series"] for m in ms}), n_markets=len(ms), n_live=len(live),
            mkt_volume_24h=round(vol, 2), mkt_open_interest=round(oi, 2),
            has_market_evidence=any(m["vol24"] > 0 for m in ms),
            mkt_ladder_depth=len(prim), primary_event=top_ev,
            zero_trade_market_pct=(1 - len(traded) / len(near)) if near else None,
            avg_spread=(sum(spreads) / len(spreads)) if spreads else None,
            mkt_prob_delta_1d=move, mkt_prob_range_1d=None,
            catalyst_in_trading_days=cat,
        )
    return out


# ------------------------------------------------------------------ prices / momentum
def prices(symbols):
    out = {}
    syms = sorted({s for s in symbols if s})
    for i in range(0, len(syms), 20):
        chunk = syms[i:i + 20]
        q = urllib.parse.urlencode({"symbols": ",".join(chunk), "range": "1mo", "interval": "1h"})
        try:
            d, _ = get_json(f"{YAHOO}?{q}")
        except Exception:
            continue
        for s, v in d.items():
            ts, cl = v.get("timestamp") or [], v.get("close") or []
            pts = [(t, c) for t, c in zip(ts, cl) if c is not None]
            if len(pts) < 10:
                continue
            out[s] = pts
    return out


def price_stats(pts, now):
    """Last price, 24h and 5d change, and the abnormal 24h move (z vs the month's daily moves)."""
    t_last, p_last = pts[-1]
    if now.timestamp() - t_last > 4 * 86400:
        return None

    def at(sec_ago):
        cut = t_last - sec_ago
        older = [p for t, p in pts if t <= cut]
        return older[-1] if older else None

    p1, p5 = at(86400), at(5 * 86400)
    r1 = (p_last / p1 - 1) if p1 else None
    # daily closes (last point per UTC day) -> daily returns -> stdev
    daily = {}
    for t, p in pts:
        daily[dt.datetime.fromtimestamp(t, UTC).date()] = p
    closes = [daily[k] for k in sorted(daily)]
    rets = [b / a - 1 for a, b in zip(closes, closes[1:]) if a]
    sd = statistics.pstdev(rets[:-1]) if len(rets) >= 8 else None
    z = (r1 / sd) if (r1 is not None and sd) else None
    return dict(price=p_last, price_ts=dt.datetime.fromtimestamp(t_last, UTC).isoformat(),
                chg_24h=r1, chg_5d=(p_last / p5 - 1) if p5 else None, vol_daily=sd, abnormal_move=z)


# ------------------------------------------------------------------ adanos
def adanos_day(key, kind, day, symbols):
    """Adanos Reddit metrics for one complete UTC day, 10 symbols per /compare call.
    Unsupported symbols come back without a name and are dropped (missing, not zero)."""
    path = "/reddit/stocks/v1/compare" if kind == "stocks" else "/reddit/crypto/v1/compare"
    arg = "tickers" if kind == "stocks" else "symbols"
    rows, calls, hdr = [], 0, {}
    syms = sorted(set(symbols))
    for i in range(0, len(syms), 10):
        q = urllib.parse.urlencode({"from": day, "to": day, arg: ",".join(syms[i:i + 10])})
        d, hdr = get_json(f"{ADANOS}{path}?{q}", headers={"X-API-Key": key})
        calls += 1
        items = d.get("stocks") if kind == "stocks" else d.get("tokens")
        for x in items or []:
            sym = x.get("ticker") or x.get("symbol")
            if not sym or not (x.get("company_name") or x.get("name")):
                continue
            rows.append(dict(date=day, kind=kind, symbol=sym.upper(), buzz_score=f(x.get("buzz_score")),
                             mentions=f(x.get("mentions")), sentiment_score=f(x.get("sentiment_score")),
                             trend=x.get("trend")))
        time.sleep(0.7)
    hl = {k.lower(): v for k, v in hdr.items()}
    left = hl.get("x-ratelimit-remaining-monthly") or hl.get("x-ratelimit-remaining")
    return rows, calls, left


def adanos_update(key, cache, now, symbols):
    """Make sure days t-1 and t-2 (UTC) are cached for every mapped symbol. Returns (cache, status)."""
    t = now.astimezone(UTC).date()
    need = [(t - dt.timedelta(days=k)).isoformat() for k in (1, 2)]
    have = {(r["date"], r["kind"]) for r in cache}
    if not key:
        return cache, dict(status="no key", calls=0)
    calls, left, err = 0, None, None
    for day in need:
        for kind in ("stocks", "crypto"):
            if (day, kind) in have or not symbols.get(kind):
                continue
            try:
                rows, c, left = adanos_day(key, kind, day, symbols[kind])
                cache += rows
                calls += c
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:200]
    keep = (t - dt.timedelta(days=ADANOS_DAYS)).isoformat()
    cache = [r for r in cache if r["date"] >= keep]
    st = "error" if err else ("fetched" if calls else "cached")
    return cache, dict(status=st, calls=calls, quota_left=left, error=err)


def adanos_features(cache, info, now):
    if not info.get("adanos_symbol"):
        return {}
    t = now.astimezone(UTC).date()
    d1, d2 = (t - dt.timedelta(days=1)).isoformat(), (t - dt.timedelta(days=2)).isoformat()
    kind, sym = info["adanos_kind"], info["adanos_symbol"].upper()
    x = {r["date"]: r for r in cache if r["kind"] == kind and r["symbol"] == sym and r["date"] in (d1, d2)}
    if d1 not in x or d2 not in x:
        out = {}
        if d1 in x:
            out.update(buzz_score=x[d1]["buzz_score"], mentions=x[d1]["mentions"], sentiment_score=x[d1]["sentiment_score"])
        return out
    a, b = x[d1], x[d2]
    sd = (a["sentiment_score"] - b["sentiment_score"]) if a["sentiment_score"] is not None and b["sentiment_score"] is not None else None
    return dict(
        buzz_score=a["buzz_score"], mentions=a["mentions"], sentiment_score=a["sentiment_score"],
        buzz_delta_1d=(a["buzz_score"] - b["buzz_score"]) if a["buzz_score"] is not None and b["buzz_score"] is not None else None,
        trade_count_pct_change_1d=((a["mentions"] / b["mentions"] - 1) * 100) if a["mentions"] and b["mentions"] else None,
        sentiment_delta_1d=sd,
    )


# ------------------------------------------------------------------ deltas from history
def prior_pull(history, now, hours=24, tol=3.5):
    """The stored pull nearest to `hours` ago (within tol hours)."""
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


def pct(a, b):
    return (a / b - 1) * 100 if (a is not None and b) else None


# ------------------------------------------------------------------ run
def run(state: pathlib.Path, out: pathlib.Path, adanos_key=None, now=None):
    t0 = time.time()
    now = now or dt.datetime.now(UTC)
    now_et = now.astimezone(ET)
    run_ts = now.replace(microsecond=0).isoformat()
    cfg = scoring.load_config(ROOT / "config" / "weights_w0.yaml")
    cat_cfg = yaml.safe_load((HERE / "catalysts.yaml").read_text())
    catalysts = dict(dates=[e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(e["date"])
                            for e in cat_cfg["events"]], applies_to=cat_cfg["applies_to"])

    history = load(state / "score_history.json", [])
    daily = load(state / "daily_log.json", [])
    runs = load(state / "runs.json", [])
    ad_cache = load(state / "adanos_daily.json", [])
    steps = {}

    # 1 · Pull
    series, events = kalshi_pull()
    mrows = market_rows(events, series, now)
    feats = topic_features(mrows, now, catalysts)
    steps["kalshi"] = dict(status="ok", events=len(events), markets=len(mrows), topics=len(feats))

    ad_syms = collections.defaultdict(list)
    for v in feats.values():
        if v["adanos_symbol"]:
            ad_syms[v["adanos_kind"]].append(v["adanos_symbol"])
    ad_cache, steps["adanos"] = adanos_update(adanos_key, ad_cache, now, ad_syms)

    raw, raw_status = sources.pull_all(now_et.date())  # free sources, shown as raw tables, not scored yet

    px = prices([v["price_symbol"] for v in feats.values()])
    steps["prices"] = dict(status="ok" if px else "error", symbols=len(px))

    prev_ts, prev = prior_pull(history, now)
    # trailing daily volumes per topic for the money_flow floor (playbook v2)
    vol_hist = collections.defaultdict(list)
    for r in sorted(daily, key=lambda r: r["date"]):
        if r.get("mkt_volume_24h") is not None:
            vol_hist[r["topic"]].append(r["mkt_volume_24h"])

    rows = []
    for t, x in feats.items():
        r = dict(x)
        r["ticker"] = t
        p = prev.get(t)
        r["prev_volume_24h"] = p["mkt_volume_24h"] if p else None
        r["mkt_volume_delta_1d"] = pct(x["mkt_volume_24h"], p["mkt_volume_24h"]) if p else None
        r["mkt_oi_delta_1d"] = pct(x["mkt_open_interest"], p["mkt_open_interest"]) if p else None
        hist = vol_hist[t][-30:]
        if p and len(hist) >= 10:
            floor = sorted(hist)[max(0, int(math.ceil(0.10 * len(hist))) - 1)]
            if p["mkt_volume_24h"] < floor:
                r["mkt_volume_delta_1d"], r["money_flow_floored"] = None, True
        r.update(adanos_features(ad_cache, x, now))
        adanos_ok = any(r.get(k) is not None for k in ("buzz_delta_1d", "trade_count_pct_change_1d", "sentiment_delta_1d"))
        r["sources_available"] = 1 + int(adanos_ok)
        r["days_since_covered"] = None  # filled once the episode log exists
        ps = price_stats(px[x["price_symbol"]], now) if x["price_symbol"] in px else None
        if ps:
            r.update(ps)
        rows.append(r)

    ranked, gated = scoring.score_day(rows, cfg)
    # momentum reference: percentile of |abnormal move| within the surviving pool
    mom = scoring.pctrank([abs(r["abnormal_move"]) if r.get("abnormal_move") is not None else None for r in ranked])
    order = sorted([i for i, v in enumerate(mom) if v is not None], key=lambda i: -abs(ranked[i]["abnormal_move"]))
    for k, i in enumerate(order, 1):
        ranked[i]["momentum_rank"] = k
    for r, m in zip(ranked, mom):
        r["momentum_pct"] = m
    steps["score"] = dict(status="ok", scored=len(ranked), gated=len(gated),
                          prior_pull=prev_ts, weights=cfg["version"])

    comp = scoring.COMPONENTS
    out_rows = []
    for r in ranked + gated:
        pctl = r.get("pct") or {}
        out_rows.append({
            "run_ts": run_ts, "rank": r.get("rank"), "topic": r["topic"], "name": r["name"],
            "asset_class": r["asset_class"], "tier": r.get("tier"), "gate": r.get("data_quality_flag"),
            "demand_score": rnd(r.get("demand_score")), "raw_score": rnd(r.get("raw_score")),
            "quality": rnd(r.get("quality")), "momentum_pct": rnd(r.get("momentum_pct")),
            "momentum_rank": r.get("momentum_rank"),
            **{f"p_{c}": rnd(pctl.get(c)) for c in comp},
            "buzz_delta_1d": rnd(r.get("buzz_delta_1d"), 6), "mentions_chg_pct": rnd(r.get("trade_count_pct_change_1d"), 6),
            "sentiment_delta_1d": rnd(r.get("sentiment_delta_1d"), 6), "buzz_score": rnd(r.get("buzz_score")),
            "mkt_volume_24h": rnd(r.get("mkt_volume_24h"), 0), "mkt_volume_delta_1d": rnd(r.get("mkt_volume_delta_1d"), 6),
            "mkt_open_interest": rnd(r.get("mkt_open_interest"), 0), "mkt_oi_delta_1d": rnd(r.get("mkt_oi_delta_1d"), 6),
            "mkt_prob_delta_1d": rnd(r.get("mkt_prob_delta_1d"), 8), "avg_spread": rnd(r.get("avg_spread"), 8),
            "zero_trade_market_pct": rnd(r.get("zero_trade_market_pct"), 8),
            "sources_available": r.get("sources_available"), "catalyst_in_trading_days": r.get("catalyst_in_trading_days"),
            "has_market_evidence": r.get("has_market_evidence"), "mkt_prob_range_1d": rnd(r.get("mkt_prob_range_1d")),
            "days_since_covered": r.get("days_since_covered"),
            "n_series": r["n_series"], "n_markets": r["n_markets"], "mkt_ladder_depth": r["mkt_ladder_depth"],
            "primary_event": r.get("primary_event"),
            "price": rnd(r.get("price"), 6), "chg_24h": rnd(r.get("chg_24h")), "abnormal_move": rnd(r.get("abnormal_move"), 6),
            "weights_version": cfg["version"],
        })
    out_rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -(r["mkt_volume_24h"] or 0)))

    # history (per pull) and daily log (15:00 ET pull)
    keep_ts = (now - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    history = [h for h in history if h["run_ts"] >= keep_ts and h["run_ts"] != run_ts]
    history += [dict(run_ts=run_ts, topic=r["topic"], rank=r["rank"], tier=r["tier"], demand_score=r["demand_score"],
                     momentum_pct=r["momentum_pct"], mkt_volume_24h=r["mkt_volume_24h"],
                     mkt_open_interest=r["mkt_open_interest"], gate=r["gate"]) for r in out_rows]
    pull_hour = min(PULL_HOURS_ET, key=lambda h: min(abs(now_et.hour + now_et.minute / 60 - h), 24 - abs(now_et.hour + now_et.minute / 60 - h)))
    d = now_et.date().isoformat()
    if now_et.hour >= 15 and not any(r["date"] == d for r in daily):  # first pull at or after the 15:00 ET pick
        daily = [r for r in daily if r["date"] != d]
        daily += [dict(date=d, **{k: r[k] for k in ("rank", "topic", "name", "asset_class", "tier", "gate", "demand_score",
                                                     "momentum_pct", "momentum_rank", "mkt_volume_24h", "mkt_open_interest",
                                                     "abnormal_move", "chg_24h")}) for r in out_rows]
        keep_d = (now_et.date() - dt.timedelta(days=DAILY_DAYS)).isoformat()
        daily = [r for r in daily if r["date"] >= keep_d]

    # symbol appendix
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
        ms = map_series(sname, s.get("title", ""), s.get("tags"))
        info = topic_info(ms["topic"])
        appendix.append(dict(series=sname, title=s.get("title"), category=s.get("category"),
                             frequency=s.get("frequency"), tags=", ".join(s.get("tags") or []),
                             topic=ms["topic"], topic_name=info["name"], asset_class=info["asset_class"],
                             mapped=ms["mapped"], rule=ms["rule"], price_symbol=info["price_symbol"],
                             adanos=f'{info["adanos_kind"]}:{info["adanos_symbol"]}' if info["adanos_symbol"] else None,
                             open_events=len(b["events"]), open_markets=b["markets"],
                             volume_24h=round(b["vol24"]), open_interest=round(b["oi"])))
    appendix.sort(key=lambda r: -r["volume_24h"])

    # market data
    mkt = []
    for t, x in feats.items():
        if x["price_symbol"] in px:
            ps = price_stats(px[x["price_symbol"]], now)
            if ps:
                mkt.append(dict(topic=t, name=x["name"], asset_class=x["asset_class"], symbol=x["price_symbol"],
                                price=rnd(ps["price"], 6), price_ts=ps["price_ts"], chg_24h=rnd(ps["chg_24h"]),
                                chg_5d=rnd(ps["chg_5d"]), vol_daily=rnd(ps["vol_daily"]),
                                abnormal_move=rnd(ps["abnormal_move"], 2), kalshi_volume_24h=round(x["mkt_volume_24h"])))
    mkt.sort(key=lambda r: -abs(r["abnormal_move"] or 0))

    top = next((r for r in out_rows if r["rank"] == 1), None)
    mtop = next((r for r in out_rows if r.get("momentum_rank") == 1), None)
    runs = [r for r in runs if r["run_ts"] != run_ts]
    runs.append(dict(
        run_ts=run_ts, run_et=now_et.strftime("%Y-%m-%d %H:%M"), pull_hour_et=pull_hour,
        kalshi=steps["kalshi"]["status"], kalshi_markets=steps["kalshi"]["markets"], topics=steps["kalshi"]["topics"],
        adanos=steps["adanos"]["status"], adanos_calls=steps["adanos"]["calls"],
        adanos_quota_left=steps["adanos"].get("quota_left"), adanos_error=steps["adanos"].get("error"),
        prices=steps["prices"]["status"], priced=steps["prices"]["symbols"],
        scored=steps["score"]["scored"], gated=steps["score"]["gated"], prior_pull=prev_ts,
        top_topic=top["topic"] if top else None, top_tier=top["tier"] if top else None,
        top_score=top["demand_score"] if top else None, momentum_top=mtop["topic"] if mtop else None,
        **{f"{st['dataset']}_status": st["status"] for st in raw_status},
        **{f"{st['dataset']}_rows": st["rows"] for st in raw_status},
        **{f"{st['dataset']}_error": st["error"] for st in raw_status if st["error"]},
        coinbase_usd_pairs=next((st.get("coinbase_usd_pairs") for st in raw_status if st["dataset"] == "crypto_spot"), None),
        seconds=round(time.time() - t0, 1),
    ))
    runs = runs[-240:]

    out.mkdir(parents=True, exist_ok=True)
    files = dict(topic_log=out_rows, score_history=history, daily_log=daily, runs=runs,
                 adanos_daily=ad_cache, symbol_appendix=appendix, market_data=mkt, **raw)
    for k, v in files.items():
        (out / f"{k}.json").write_text(json.dumps(v, separators=(",", ":"), default=str))
    return runs[-1]


def rnd(x, n=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--adanos-key", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.state, a.out, a.adanos_key), indent=1))
