"""Agenda items 3-5: venue appendix (incl. Kalshi perps), Adanos sector changes, Adanos financial news, briefing.

  kalshi_perps     one row per Kalshi perpetual future: price, open interest, 24h volume, latest funding, topic
  venue_appendix   one row per topic: on which venues it exists (Kalshi, perps, Polymarket, Adanos, Binance,
                   Coinbase, Kraken, Yahoo) and how active it is on each
  sectors          Adanos trending sectors per platform (reddit, x, news): buzz, mentions, sentiment, change vs
                   the day before and over the week, top tickers
  news             Adanos news for the day's top topics: headline, source, time, sentiment
  briefing         a short written read of sectors, news and the top picks. The pipeline writes a plain automatic
                   version; the cloud scheduled task replaces it with Claude's own reading.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request

ADANOS = "https://api.adanos.org"
PERP_TOPIC = {"US500": "SPX", "US TECH 100": "NDX", "US 2000": "RUT", "GOLD": "GOLD", "SILVER": "SILVER", "COPPER": "COPPER",
              "PLATINUM": "PLATINUM", "PALLADIUM": "PALLADIUM", "ALUMINUM": "ALUMINUM", "WTI CRUDE OIL": "WTI", "KPEPE": "PEPE",
              "KSHIB": "SHIB"}
PLATS = ("reddit", "x", "news")
PERP_CLASS = {"crypto": "crypto", "metals": "commodity", "energy": "commodity", "equities": "equity", "indices": "index"}
# fund-filing boilerplate (\"X LLC raised its stake in ...\") is not news
HOLDINGS = re.compile(r"\b(grew|raised|increased|lessened|reduced|trimmed|cut|lowered|boosted|acquired|bought|sold|purchased)\b[^.]{0,40}\b(stake|position|holdings|shares)\b", re.I)


def _get(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Metrixx TopicLog)", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ perps
def perp_topic(title: str) -> str:
    """'0.0001 BTC' -> BTC, 'US Tech 100' -> NDX, 'NVDA' -> NVDA."""
    t = (title or "").strip().upper()
    if t in PERP_TOPIC:
        return PERP_TOPIC[t]
    last = t.split()[-1] if t else ""
    return PERP_TOPIC.get(last, last)


def perps_rows(perps: dict, ensure):
    """perps = archive.kalshi_perps() output. ensure(topic, cls) registers unknown coins as topics."""
    if not perps or not perps.get("markets"):
        return []
    fund = {}
    for f in sorted(perps.get("funding_rates") or [], key=lambda f: f.get("funding_time") or ""):
        fund[f.get("market_ticker")] = f  # latest wins
    rows = []
    for m in perps["markets"]:
        topic = perp_topic(m.get("title"))
        cls = (m.get("asset_class") or "").lower()
        if cls == "crypto":
            ensure(topic, "crypto")
        fr = fund.get(m.get("ticker")) or {}
        rows.append(dict(ticker=m.get("ticker"), title=m.get("title"), topic=topic, asset_class=m.get("asset_class"),
                         price=_f(m.get("price")), reference_price=_f(m.get("reference_price")),
                         open_interest_usd=_f(m.get("open_interest_notional_value_dollars")),
                         volume_24h_usd=_f(m.get("volume_24h_notional_value_dollars")),
                         funding_rate=_f(fr.get("funding_rate")), funding_time=fr.get("funding_time"), status=m.get("status")))
    return sorted(rows, key=lambda r: -(r["volume_24h_usd"] or 0))


# ------------------------------------------------------------------ venue appendix
def venue_appendix(topic_rows, events, perps, coins, infos):
    by_ev = {}
    for e in events:
        d = by_ev.setdefault(e["topic"], {"kalshi": 0, "polymarket": 0, "movers": 0})
        key = "movers" if e["source"] == "yahoo_movers" else e["source"]
        if key in d:
            d[key] += 1
    perp_by = {}
    for p in perps:
        perp_by.setdefault(p["topic"], p)
    out = []
    seen = set()
    for r in topic_rows:
        t = r["topic"]
        seen.add(t)
        i = infos.get(t) or {}
        c = (coins.get(t) or {}) if r.get("asset_class") == "crypto" else {}  # CVX the stock is not CVX the coin
        p = perp_by.get(t)
        ev = by_ev.get(t, {})
        ad_pl = [pl for pl in PLATS if r.get(f"ad_mentions_{pl}") is not None]
        row = dict(topic=t, name=r.get("name"), asset_class=r.get("asset_class"),
                   kalshi_events=ev.get("kalshi", 0), kalshi_vol_24h=r.get("k_vol"), kalshi_oi=r.get("k_oi"),
                   perp=p["ticker"] if p else None, perp_oi_usd=p["open_interest_usd"] if p else None,
                   perp_vol_24h_usd=p["volume_24h_usd"] if p else None, perp_funding=p["funding_rate"] if p else None,
                   polymarket_events=ev.get("polymarket", 0), polymarket_vol_24h=r.get("p_vol"),
                   adanos=i.get("adanos_symbol") and f"{i.get('adanos_kind')}:{i.get('adanos_symbol')}",
                   adanos_platforms=",".join(ad_pl) or None,
                   binance=bool(c.get("on_binance")), coinbase=bool(c.get("on_coinbase")), kraken=bool(c.get("on_kraken")),
                   price_symbol=i.get("price_symbol"), price_source=r.get("price_source"))
        row["venues"] = sum([row["kalshi_events"] > 0, bool(row["perp"]), row["polymarket_events"] > 0, bool(ad_pl),
                             row["binance"], row["coinbase"], row["kraken"]])
        out.append(row)
    for t, p in perp_by.items():  # a perp whose underlying is not a topic in this pull still gets a row
        if t not in seen:
            cls = PERP_CLASS.get((p.get("asset_class") or "").lower())
            c = (coins.get(t) or {}) if cls == "crypto" else {}
            out.append(dict(topic=t, name=p["title"], asset_class=cls, kalshi_events=0,
                            perp=p["ticker"], perp_oi_usd=p["open_interest_usd"], perp_vol_24h_usd=p["volume_24h_usd"],
                            perp_funding=p["funding_rate"], polymarket_events=0, binance=bool(c.get("on_binance")),
                            coinbase=bool(c.get("on_coinbase")), kraken=bool(c.get("on_kraken")),
                            venues=1 + bool(c.get("on_binance")) + bool(c.get("on_coinbase")) + bool(c.get("on_kraken"))))
    return sorted(out, key=lambda r: (-(r.get("venues") or 0), r["topic"]))


# ------------------------------------------------------------------ sectors
def sectors(key, d1, d2, stat):
    """Adanos trending sectors per platform for day d1, with the change from d2."""
    rows = []
    for pl in PLATS:
        days = {}
        for d in (d1, d2):
            try:
                days[d] = _get(f"{ADANOS}/{pl}/stocks/v1/trending/sectors?from={d}&to={d}&limit=20", {"X-API-Key": key}) or []
                stat["calls"] = stat.get("calls", 0) + 1
            except Exception as e:
                stat["error"] = f"{type(e).__name__}: {e}"[:200]
                days[d] = []
            time.sleep(0.15)
        prev = {s.get("sector"): (i + 1, s) for i, s in enumerate(days[d2])}
        for i, s in enumerate(days[d1]):
            p_rank, p = prev.get(s.get("sector"), (None, {}))
            th = s.get("trend_history") or []
            rows.append(dict(date=d1, platform=pl, sector=s.get("sector"), rank=i + 1, rank_prev=p_rank,
                             buzz=_f(s.get("buzz_score")), buzz_prev=_f(p.get("buzz_score")),
                             buzz_chg=(_f(s.get("buzz_score")) - _f(p.get("buzz_score"))) if p.get("buzz_score") is not None else None,
                             buzz_7d_chg=(th[-1] - th[0]) if len(th) >= 2 else None, trend_history=th,
                             mentions=_f(s.get("mentions")), mentions_prev=_f(p.get("mentions")),
                             mentions_chg_pct=((_f(s.get("mentions")) / _f(p.get("mentions")) - 1) * 100) if p.get("mentions") else None,
                             sentiment=_f(s.get("sentiment_score")), sentiment_chg=(_f(s.get("sentiment_score")) - _f(p.get("sentiment_score")))
                             if p.get("sentiment_score") is not None else None,
                             bullish_pct=_f(s.get("bullish_pct")), bearish_pct=_f(s.get("bearish_pct")),
                             unique_tickers=s.get("unique_tickers"), top_tickers=", ".join(s.get("top_tickers") or []), trend=s.get("trend")))
    return rows


# ------------------------------------------------------------------ news
def _headline(snippet):
    """First line of the snippet (usually the headline or lead), cut at a word near 180 characters."""
    first = (snippet or "").strip().split("\n", 1)[0].strip()
    if len(first) <= 180:
        return first
    return first[:180].rsplit(" ", 1)[0] + "…"


def news(key, picks, stat, per_topic=4, days=2):
    """picks = [(topic, adanos_symbol, name)] for stock topics, best first. Keeps snippets that name the topic."""
    rows = []
    for topic, sym, name in picks:
        try:
            d = _get(f"{ADANOS}/news/stocks/v1/stock/{urllib.parse.quote(sym)}?days={days}", {"X-API-Key": key})
            stat["calls"] = stat.get("calls", 0) + 1
        except Exception as e:
            stat["error"] = f"{type(e).__name__}: {e}"[:200]
            continue
        time.sleep(0.15)
        if not d or d.get("found") is False:
            continue
        word = (name or d.get("company_name") or "").split()[0] if (name or d.get("company_name")) else ""
        pat = re.compile(r"\b(" + re.escape(sym) + (("|" + re.escape(word)) if len(word) >= 4 else "") + r")\b", re.I)
        kept = [m for m in (d.get("top_mentions") or []) if pat.search(m.get("text_snippet") or "")
                and not HOLDINGS.search(m.get("text_snippet") or "")]
        seen = set()
        for m in kept:
            h = _headline(m.get("text_snippet"))
            if h.lower() in seen:
                continue
            seen.add(h.lower())
            rows.append(dict(topic=topic, symbol=sym, headline=h, source=m.get("source"), time=m.get("created_utc"),
                             sentiment=_f(m.get("sentiment_score")), label=m.get("sentiment_label"),
                             topic_mentions=d.get("mentions"), topic_sentiment=_f(d.get("sentiment_score")),
                             positive=d.get("positive_count"), negative=d.get("negative_count"),
                             top_sources=", ".join(s.get("source", "") for s in (d.get("top_sources") or [])[:3])))
            if len(seen) >= per_topic:
                break
    return rows


# ------------------------------------------------------------------ automatic briefing (the cloud task replaces it with Claude's)
def auto_briefing(day, sector_rows, news_rows, top_rows):
    out = []
    ns = [s for s in sector_rows if s["platform"] == "news"] or sector_rows
    if ns:
        lead = ns[0]
        up = sorted([s for s in ns if s.get("buzz_chg") is not None], key=lambda s: -s["buzz_chg"])
        moves = "; ".join(f"{s['sector']} {s['buzz_chg']:+.1f}" for s in up[:2]) if up else "no change data"
        downs = "; ".join(f"{s['sector']} {s['buzz_chg']:+.1f}" for s in up[-2:][::-1]) if len(up) > 2 else ""
        out.append(dict(date=day, section="sectors", source="auto", title="Sectors",
                        text=f"{lead['sector']} leads {lead['platform']} buzz ({lead['buzz']:.1f}; top tickers {lead['top_tickers']}). "
                             f"Biggest gains in buzz vs the day before: {moves}." + (f" Biggest drops: {downs}." if downs else "")))
    if news_rows:
        tops = []
        for t in dict.fromkeys(r["topic"] for r in news_rows):
            r = next(x for x in news_rows if x["topic"] == t)
            tops.append(f"{t}: {r['headline']} ({r['source']})")
        out.append(dict(date=day, section="news", source="auto", title="News on today's top topics", text=" · ".join(tops[:6])))
    if top_rows:
        out.append(dict(date=day, section="picks", source="auto", title="Top picks",
                        text=", ".join(f"#{r['pick_rank']} {r['topic']} ({r['name']})" for r in top_rows[:5])))
    return out
