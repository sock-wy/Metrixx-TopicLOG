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
    """Active Polymarket events in the money tags, most 24h volume first (top `per_tag` per tag).

    Per event: volume (24h, 1 week, total), liquidity, open interest, the most traded market, and
    move_1d = 24h-volume-weighted |1-day price change| over its traded, tightly quoted markets.
    """
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
                    ms = [m for m in (e.get("markets") or []) if not m.get("closed")]
                    top = max(ms, key=lambda m: _num(m.get("volume24hr")) or _num(m.get("volumeNum")) or 0) if ms else {}
                    mv = [(abs(_num(m.get("oneDayPriceChange")) or 0.0), _num(m.get("volume24hr")) or 0.0) for m in ms
                          if (_num(m.get("volume24hr")) or 0) > 0 and m.get("oneDayPriceChange") is not None
                          and (_num(m.get("spread")) is None or _num(m.get("spread")) <= 0.30)]
                    w = sum(x[1] for x in mv)
                    seen[e["id"]] = dict(
                        event_id=str(e["id"]), title=e.get("title"), slug=e.get("slug"),
                        tags=", ".join(t.get("label") for t in (e.get("tags") or []) if t.get("label")),
                        matched_tags={tag}, end_date=(e.get("endDate") or "")[:10] or None,
                        volume_24h=_num(e.get("volume24hr")), volume_1wk=_num(e.get("volume1wk")),
                        volume_total=_num(e.get("volume")), liquidity=_num(e.get("liquidity")),
                        open_interest=_num(e.get("openInterest")), n_markets=len(ms), comments=e.get("commentCount"),
                        top_market=top.get("question"), top_price=_num(top.get("lastTradePrice")),
                        top_change_1d=_num(top.get("oneDayPriceChange")), top_spread=_num(top.get("spread")),
                        move_1d=round(sum(x[0] * x[1] for x in mv) / w, 6) if w else None,
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
KRAKEN_BASE = {"XBT": "BTC", "XXBT": "BTC", "XDG": "DOGE", "XXDG": "DOGE", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC",
               "XXLM": "XLM", "XZEC": "ZEC", "XETC": "ETC", "XXMR": "XMR", "XREP": "REP", "XMLN": "MLN"}


def crypto_spot():
    """24h stats per coin from Binance (USDT pairs), Coinbase and Kraken (USD pairs).

    Source of record for a coin's price is Binance, then Coinbase, then Kraken; volumes are kept per venue
    and summed in USD. on_coinbase / on_kraken say whether a US user can buy it there.
    """
    t0, err, coins = time.time(), [], {}

    def c(sym):
        return coins.setdefault(sym, dict(symbol=sym))
    try:
        for x in _get("https://data-api.binance.vision/api/v3/ticker/24hr"):
            s = x.get("symbol", "")
            if s.endswith("USDT") and (_num(x.get("quoteVolume")) or 0) > 0:
                r = c(s[:-4])
                r.update(binance_price=_num(x.get("lastPrice")), binance_chg=_num(x.get("priceChangePercent")),
                         binance_vol=_num(x.get("quoteVolume")), binance_trades=_num(x.get("count")),
                         high=_num(x.get("highPrice")), low=_num(x.get("lowPrice")))
    except Exception as e:
        err.append(f"Binance: {type(e).__name__}")
    try:
        stats = _get("https://api.exchange.coinbase.com/products/stats")
        for pid, st in stats.items():
            if not pid.endswith("-USD"):
                continue
            d = st.get("stats_24hour") or {}
            last, op, vol = _num(d.get("last")), _num(d.get("open")), _num(d.get("volume"))
            r = c(pid[:-4])
            r.update(on_coinbase=True, coinbase_price=last, coinbase_chg=((last / op - 1) * 100) if last and op else None,
                     coinbase_vol=(vol * last) if vol and last else None)
    except Exception as e:
        err.append(f"Coinbase: {type(e).__name__}")
    try:
        pairs = _get("https://api.kraken.com/0/public/AssetPairs").get("result", {})
        usd = {k: v for k, v in pairs.items() if v.get("quote") in ("ZUSD", "USD") and not v.get("altname", "").endswith(".d")}
        tick = _get("https://api.kraken.com/0/public/Ticker").get("result", {})
        for k, v in usd.items():
            t = tick.get(k)
            if not t:
                continue
            base = (v.get("wsname") or "").split("/")[0] or v.get("base")
            base = KRAKEN_BASE.get(base, KRAKEN_BASE.get(v.get("base"), base))
            last, op, vol = _num(t["c"][0]), _num(t.get("o")), _num(t["v"][1])
            r = c(base)
            r.update(on_kraken=True, kraken_price=last, kraken_chg=((last / op - 1) * 100) if last and op else None,
                     kraken_vol=(vol * last) if vol and last else None, kraken_pair=k)
    except Exception as e:
        err.append(f"Kraken: {type(e).__name__}")
    rows = []
    for sym, r in coins.items():
        for v in ("binance", "coinbase", "kraken"):
            if r.get(f"{v}_price"):
                r["primary"], r["price"], r["change_pct"] = v, r[f"{v}_price"], r.get(f"{v}_chg")
                break
        if not r.get("price"):
            continue
        r["usd_volume"] = sum(r.get(f"{v}_vol") or 0 for v in ("binance", "coinbase", "kraken"))
        r["on_coinbase"], r["on_kraken"] = bool(r.get("on_coinbase")), bool(r.get("on_kraken"))
        r["on_binance"] = r.get("binance_price") is not None
        if r.get("high") and r.get("low"):
            r["range_pct"] = round((r["high"] / r["low"] - 1) * 100, 3)
        rows.append(r)
    rows.sort(key=lambda r: -(r["usd_volume"] or 0))
    st = _status("crypto_spot", rows, t0, None)
    st["coinbase_usd_pairs"] = sum(r["on_coinbase"] for r in rows)
    st["kraken_usd_pairs"] = sum(r["on_kraken"] for r in rows)
    if err:
        st["error"] = "; ".join(err)
        st["status"] = "partial" if rows else "error"
    return rows, st


def crypto_daily(sym, primary, kraken_pair=None, days=31):
    """Daily closes [(ts, close)] for one coin from its source-of-record venue."""
    try:
        if primary == "binance":
            d = _get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}USDT&interval=1d&limit={days + 1}")
            return [(int(k[0] / 1000), float(k[4])) for k in d]
        if primary == "coinbase":
            d = _get(f"https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=86400")
            return sorted((int(k[0]), float(k[4])) for k in d)[-(days + 1):]
        if primary == "kraken" and kraken_pair:
            d = _get(f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval=1440")
            res = [v for k, v in d.get("result", {}).items() if k != "last"]
            return [(int(k[0]), float(k[4])) for k in (res[0] if res else [])][-(days + 1):]
    except Exception:
        return []
    return []


def pull_all(today: dt.date):
    out, statuses = {}, []
    for name, fn in (("us_stocks", nasdaq_screener), ("earnings_calendar", lambda: nasdaq_earnings(today)),
                     ("us_movers", yahoo_movers), ("polymarket", polymarket), ("crypto_spot", crypto_spot)):
        rows, st = fn()
        st["dataset"] = name
        out[name] = rows
        statuses.append(st)
    return out, statuses
