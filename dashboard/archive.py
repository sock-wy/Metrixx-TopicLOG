"""Permanent archive: every pull writes what it saw, so backtests are no longer limited by API history.

Layout (gzipped JSON, one file per dataset per pull), under <out>/archive/:
  YYYY/MM/DD/HHMM_<name>.json.gz     per pull: kalshi_markets, kalshi_perps, polymarket, us_movers, topic_log, events, claude_digest
  YYYY/MM/DD/daily_<name>.json.gz    once per ET day, first pull at/after 17:00 ET: us_stocks, crypto_spot, earnings_calendar
  adanos/YYYY-MM-DD.json.gz          once per complete UTC day: every symbol in the Adanos universe, every platform

The cloud scheduled task pushes <out>/archive to the `archive` branch of the repo; the desktop app keeps it in its
data folder. `archive_state.json` in the state folder (and the run log, for the cloud) records which daily parts are done.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import time
import urllib.parse
import urllib.request

PERPS = "https://external-api.kalshi.com/trade-api/v2/margin"
UNIVERSE = pathlib.Path(__file__).with_name("adanos_universe.json")


def _write(path: pathlib.Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=str)


def _get(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Metrixx TopicLog)", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def kalshi_perps(now):
    """Kalshi perpetual futures: market stats plus funding rates of the last 2 days (public endpoints)."""
    try:
        ms = _get(f"{PERPS}/markets").get("markets") or []
        start = int((now - dt.timedelta(days=2)).timestamp())
        fr = _get(f"{PERPS}/funding_rates/historical?start_ts={start}").get("funding_rates") or []
        keep = ("ticker", "title", "asset_class", "price", "reference_price", "bid", "ask", "open_interest",
                "open_interest_notional_value_dollars", "volume_24h", "volume_24h_notional_value_dollars", "status")
        return {"markets": [{k: m.get(k) for k in keep} for m in ms], "funding_rates": fr}, "ok"
    except Exception as e:  # never fail the pull for the archive
        return {"error": f"{type(e).__name__}: {e}"[:200]}, "error"


def adanos_day(key, day, stat):
    """One complete UTC day for the whole Adanos universe (reddit / x / news; crypto: reddit), 10 symbols per /compare call."""
    import concurrent.futures as cf
    try:
        uni = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    except Exception:
        return None
    jobs = []
    for kind, plats in (("stocks", ("reddit", "x", "news")), ("crypto", ("reddit",))):
        syms = uni.get(kind) or []
        arg = "tickers" if kind == "stocks" else "symbols"
        for plat in plats:
            for i in range(0, len(syms), 10):
                jobs.append((kind, plat, f"https://api.adanos.org/{plat}/{kind}/v1/compare?from={day}&to={day}&{arg}={urllib.parse.quote(','.join(syms[i:i + 10]))}"))

    def one(job):
        kind, plat, url = job
        for attempt in range(3):
            try:
                d = _get(url, {"X-API-Key": key})
                return [{"platform": plat, "kind": kind, **{k: v for k, v in x.items() if k != "trend_history"}}
                        for x in d.get("stocks") or d.get("tokens") or []]
            except Exception:
                time.sleep(1 + attempt)
        return []
    out = []
    with cf.ThreadPoolExecutor(4) as ex:
        for rows in ex.map(one, jobs):
            out += rows
    stat["archive_calls"] = stat.get("archive_calls", 0) + len(jobs)
    return out


def write(out: pathlib.Path, state: pathlib.Path, now, now_et, run_ts, *, mrows, raw, topic_log, events, adanos_key, ad_stat, runs=(), perps=None,
          digest=None):
    root = out / "archive"
    day = now_et.date()
    base = root / f"{day:%Y/%m/%d}"
    stamp = now_et.strftime("%H%M")
    meta = {"run_ts": run_ts}
    st_path = state / "archive_state.json"
    try:
        st = json.loads(st_path.read_text())
    except Exception:
        st = {}
    for r in runs:  # the cloud keeps only runs.json between pulls, so the run log also records what is done
        st["daily_day"] = max(st.get("daily_day") or "", r.get("archive_daily_day") or "") or None
        st["adanos_day"] = max(st.get("adanos_day") or "", r.get("archive_adanos_day") or "") or None
    written = []

    km = [{k: r.get(k) for k in ("topic", "series", "event", "market", "bid", "ask", "last", "vol24", "oi", "close")}
          for r in mrows if (r.get("vol24") or 0) > 0 or (r.get("oi") or 0) > 0]
    perps_status = "ok" if perps else None
    if perps is None:
        perps, perps_status = kalshi_perps(now)
    for name, obj in (("kalshi_markets", km), ("kalshi_perps", perps), ("polymarket", raw.get("polymarket")),
                      ("us_movers", raw.get("us_movers")), ("topic_log", topic_log), ("events", events),
                      ("claude_digest", digest)):
        if obj:
            _write(base / f"{stamp}_{name}.json.gz", {**meta, "rows": obj})
            written.append(name)

    if now_et.hour >= 17 and st.get("daily_day") != day.isoformat():
        for name in ("us_stocks", "crypto_spot", "earnings_calendar"):
            if raw.get(name):
                _write(base / f"daily_{name}.json.gz", {**meta, "rows": raw[name]})
                written.append("daily_" + name)
        st["daily_day"] = day.isoformat()

    d1 = (now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()
    if adanos_key and st.get("adanos_day") != d1:
        rows = adanos_day(adanos_key, d1, ad_stat)
        if rows:
            _write(root / "adanos" / f"{d1}.json.gz", {**meta, "day": d1, "rows": rows})
            written.append("adanos")
            st["adanos_day"] = d1

    st_path.write_text(json.dumps(st))
    return {"archive_files": len(written), "archive_parts": ",".join(written), "perps": perps_status,
            "archive_daily_day": st.get("daily_day"), "archive_adanos_day": st.get("adanos_day")}
