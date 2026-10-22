"""Free data sources pulled on every run and shown on the dashboard as raw tables.

None of these feed demand_score yet: they are collected so the universe and the
algorithm can be widened later (see dashboard/README.md, "Raw data").

Every fetcher returns (rows, status) and never raises: a failing source shows as
an error on the dashboard and the run carries on.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Metrixx TopicLog dashboard)"}


def _get(url, headers=None, timeout=40, tries=3):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    raise err


def _num(x):
    if x in (None, "", "NA", "N/A"):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _status(name, rows, t0, err=None):
    return dict(source=name, status="error" if err else ("ok" if rows else "empty"), rows=len(rows),
                seconds=round(time.time() - t0, 1), error=(f"{type(err).__name__}: {err}"[:200] if err else None))


# ------------------------------------------------------------------ US equities: Nasdaq screener
def nasdaq_screener():
    """Every US-listed stock: last price, change, volume, market cap, sector (one request)."""
    t0, rows, err = time.time(), [], None
    try:
        d = _get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true")
        for r in (d.get("data") or {}).get("rows") or []:
            rows.append(dict(
                symbol=r.get("symbol", "").strip(), name=(r.get("name") or "").strip(),
                price=_num(r.get("lastsale")), change=_num(r.get("netchange")), change_pct=_num(r.get("pctchange")),
                volume=_num(r.get("volume")), market_cap=_num(r.get("marketCap")),
                sector=r.get("sector") or None, industry=r.get("industry") or None,
                country=r.get("country") or None, ipo_year=r.get("ipoyear") or None,
            ))
        rows = [r for r in rows if r["symbol"]]
    except Exception as e:
        err = e
    return rows, _status("nasdaq_screener", rows, t0, err)


# ------------------------------------------------------------------ US equities: earnings calendar
def nasdaq_earnings(today: dt.date, days=10):
    """Earnings reports for the next `days` weekdays, with consensus EPS."""
    t0, rows, err = time.time(), [], None
    d, n = today, 0
    try:
        while n < days:
            if d.weekday() < 5:
                body = _get(f"https://api.nasdaq.com/api/calendar/earnings?date={d.isoformat()}")
                for r in ((body.get("data") or {}).get("rows") or []):
                    rows.append(dict(
                        date=d.isoformat(), symbol=(r.get("symbol") or "").strip(), name=r.get("name"),
                        time=r.get("time"), market_cap=_num(r.get("marketCap")),
                        fiscal_quarter=r.get("fiscalQuarterEnding"), eps_forecast=_num(r.get("epsForecast")),
                        n_estimates=_num(r.get("noOfEsts")), last_year_date=r.get("lastYearRptDt"),
                        last_year_eps=_num(r.get("lastYearEPS")),
                    ))
                n += 1
                time.sleep(0.3)
            d += dt.timedelta(days=1)
    except Exception as e:
        err = e
    return rows, _status("nasdaq_earnings", rows, t0, err)


# ------------------------------------------------------------------ US equities: Yahoo movers
def yahoo_movers():
    """Yahoo's predefined screeners: top 100 gainers, losers and most active, today."""
    t0, rows, err = time.time(), [], None
    try:
        for scr, label in (("day_gainers", "gainer"), ("day_losers", "loser"), ("most_actives", "most active")):
            body = _get(f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={scr}&count=100")
            for i, q in enumerate(((body.get("finance") or {}).get("result") or [{}])[0].get("quotes") or [], 1):
                rows.append(dict(
                    list=label, list_rank=i, symbol=q.get("symbol"), name=q.get("shortName") or q.get("longName"),
                    price=_num(q.get("regularMarketPrice")), change_pct=_num(q.get("regularMarketChangePercent")),
                    volume=_num(q.get("regularMarketVolume")), avg_volume_3m=_num(q.get("averageDailyVolume3Month")),
                    market_cap=_num(q.get("marketCap")), exchange=q.get("fullExchangeName"),
                    week52_change_pct=_num(q.get("fiftyTwoWeekChangePercent")),
                ))
                r = rows[-1]
                r["rel_volume"] = round(r["volume"] / r["avg_volume_3m"], 2) if r["volume"] and r["avg_volume_3m"] else None
    except Exception as e:
        err = e
    return rows, _status("yahoo_movers", rows, t0, err)


# ------------------------------------------------------------------ Polymarket
PM_TAGS = ["finance", "economy", "stocks", "earnings", "fed-rates", "commodities", "ipos", "business", "crypto"]


def polymarket(per_tag=200):
    """Active Polymarket events in the money tags, most 24h volume first (top `per_tag` per tag)."""
    t0, seen, err = time.time(), {}, None
    try:
        for tag in PM_TAGS:
            off = 0
            while off < per_tag:
                q = urllib.parse.urlencode(dict(active="true", closed="false", limit=100, offset=off, tag_slug=tag,
                                                order="volume24hr", ascending="false"))
                page = _get(f"https://gamma-api.polymarket.com/events?{q}")
                for e in page:
                    if e["id"] in seen:
                        seen[e["id"]]["matched_tags"].add(tag)
                        continue
                    ms = e.get("markets") or []
                    top = max(ms, key=lambda m: _num(m.get("volume24hr")) or _num(m.get("volumeNum")) or 0) if ms else {}
                    seen[e["id"]] = dict(
                        event_id=e["id"], title=e.get("title"), slug=e.get("slug"),
                        tags=", ".join(t.get("label") for t in (e.get("tags") or []) if t.get("label")),
                        matched_tags={tag}, end_date=(e.get("endDate") or "")[:10] or None,
                        volume_24h=_num(e.get("volume24hr")), volume_1wk=_num(e.get("volume1wk")),
                        volume_total=_num(e.get("volume")), liquidity=_num(e.get("liquidity")),
                        open_interest=_num(e.get("openInterest")), n_markets=len(ms), comments=e.get("commentCount"),
                        top_market=top.get("question"), top_price=_num(top.get("lastTradePrice")),
                        top_change_1d=_num(top.get("oneDayPriceChange")), top_spread=_num(top.get("spread")),
                    )
                off += 100
                if len(page) < 100:
                    break
                time.sleep(0.2)
    except Exception as e:
        err = e
    rows = []
    for r in seen.values():
        r["matched_tags"] = ", ".join(sorted(r["matched_tags"]))
        rows.append(r)
    rows.sort(key=lambda r: -(r["volume_24h"] or 0))
    return rows, _status("polymarket", rows, t0, err)


# ------------------------------------------------------------------ crypto: Binance + Coinbase
def crypto_spot():
    """Binance 24h stats for every USDT pair, flagged with whether Coinbase lists the coin against USD."""
    t0, rows, err = time.time(), [], None
    cb = set()
    cb_err = None
    try:
        for p in _get("https://api.exchange.coinbase.com/products"):
            if p.get("quote_currency") == "USD" and not p.get("trading_disabled"):
                cb.add(p["base_currency"].upper())
    except Exception as e:
        cb_err = e
    try:
        for x in _get("https://data-api.binance.vision/api/v3/ticker/24hr"):
            s = x.get("symbol", "")
            if not s.endswith("USDT") or _num(x.get("quoteVolume")) in (None, 0.0):
                continue
            base = s[:-4]
            rows.append(dict(
                symbol=base, pair=s, price=_num(x.get("lastPrice")), change_pct=_num(x.get("priceChangePercent")),
                high=_num(x.get("highPrice")), low=_num(x.get("lowPrice")),
                range_pct=round((_num(x.get("highPrice")) / _num(x.get("lowPrice")) - 1) * 100, 3) if _num(x.get("lowPrice")) else None,
                quote_volume=_num(x.get("quoteVolume")), trades=_num(x.get("count")),
                on_coinbase=(base in cb) if cb else None,
            ))
        rows.sort(key=lambda r: -(r["quote_volume"] or 0))
    except Exception as e:
        err = e
    st = _status("crypto_spot", rows, t0, err)
    st["coinbase_usd_pairs"] = len(cb)
    if cb_err and not err:
        st["error"] = f"Coinbase: {type(cb_err).__name__}"
    return rows, st


def pull_all(today: dt.date):
    out, statuses = {}, []
    for name, fn in (("us_stocks", nasdaq_screener), ("earnings_calendar", lambda: nasdaq_earnings(today)),
                     ("us_movers", yahoo_movers), ("polymarket", polymarket), ("crypto_spot", crypto_spot)):
        rows, st = fn()
        st["dataset"] = name
        out[name] = rows
        statuses.append(st)
    return out, statuses
