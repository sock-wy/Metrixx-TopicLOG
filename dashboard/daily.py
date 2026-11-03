"""The day's Topic Log: one readable JSON per New York calendar day (00:00:01-23:59:59 ET), topic_log_YYYY-MM-DD.json.

Jim's ask (Nov 3): store each day under its date so we can go back and see, for any day, what was ranked, what the
sentiment was and what the prices were (for example for an "anatomy of a trade" episode). Every pull rewrites the
file for its ET day, so after the last pull of the day (16:15 ET) it holds the day's final state, plus every pull's
ranks for the intraday path.

Written to <out>/daily/ (the desktop app keeps it there and copies it to ~/Desktop/TopicLog/daily/ when that
folder exists) and to <out>/archive/daily/ (the cloud pushes it to the `archive` branch with the rest of the archive).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib

SCHEMA = "topiclog.daily/1"
TOP_N = 50
# NYSE full-day closures, 2026-2027
NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
}
TOPIC_FIELDS = ("pick_rank", "pick_score", "pick_tier", "rank", "tier", "gate", "topic", "name", "asset_class", "catalyst",
                "is_new", "demand_score", "price", "chg_24h", "chg_5d", "abnormal_move", "momentum_pct",
                "attention_shift", "attention_x", "volume_abn", "momentum", "money_stock",
                "k_vol", "k_oi", "p_vol", "p_oi", "n_events", "origin")
SOCIAL_PREFIXES = ("ad_",)  # Adanos fields: mentions, sentiment, buzz per platform


def _r(v, n=4):
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else round(v, n)
    return v


def market_open(day: dt.date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in NYSE_HOLIDAYS


def build(now_et: dt.datetime, runs: list, rows: list, history: list, market: list, sectors: list, news: list,
          digest: list | None = None) -> dict:
    day = now_et.date()
    tz = now_et.strftime("%z")
    tz = f"{tz[:3]}:{tz[3:]}" if tz else ""
    d = day.isoformat()
    pulls = [r for r in runs if (r.get("run_et") or "").startswith(d)]
    run_ts_today = {r.get("run_ts") for r in pulls}

    scored = sorted((r for r in rows if r.get("pick_rank")), key=lambda r: r["pick_rank"])
    others = [r for r in rows if not r.get("pick_rank")]
    topics = []
    for r in (scored + others)[:TOP_N]:
        o = {k: _r(r.get(k)) for k in TOPIC_FIELDS if r.get(k) is not None}
        o.update({k: _r(v) for k, v in r.items() if k.startswith(SOCIAL_PREFIXES) and v is not None})
        topics.append(o)
    keep = {t["topic"] for t in topics}

    path = {}
    for h in sorted(history, key=lambda h: h.get("run_ts") or ""):
        if h.get("run_ts") in run_ts_today and h.get("topic") in keep:
            path.setdefault(h["topic"], []).append(
                {"run_ts": h["run_ts"], "pick_rank": h.get("pick_rank"), "pick_score": _r(h.get("pick_score")),
                 "rank": h.get("rank"), "tier": h.get("tier")})

    last = pulls[-1] if pulls else {}
    return {
        "schema": SCHEMA, "date": d, "timezone": "America/New_York",
        "window": {"start": f"{d}T00:00:01{tz}", "end": f"{d}T23:59:59{tz}"},
        "market_open": market_open(day),
        "final": now_et.hour * 60 + now_et.minute >= 16 * 60 + 10,  # true once the afternoon (16:15 ET) pull is in
        "updated_et": now_et.strftime("%Y-%m-%d %H:%M"),
        "pulls": [{k: p.get(k) for k in ("run_ts", "run_et", "pick_top", "top_topic", "topics", "scored", "adanos", "prices")}
                  for p in pulls],
        "pick_top": last.get("pick_top"), "pick_version": last.get("pick_version"),
        "topics": topics,
        "intraday": path,
        "prices": [{k: _r(v) for k, v in m.items()} for m in market],
        "sectors": sectors,
        "news": news,
        "briefing": ((digest or [{}])[0] or {}).get("briefing") if digest else None,
        "notes": "Ranks are by the scoring of record (pick_rank, w2). Prices and moves as of the last pull of the day. "
                 "Facts from public data; not investment advice.",
    }


def write(out: pathlib.Path, now_et: dt.datetime, **kw) -> str:
    doc = build(now_et, **kw)
    name = f"topic_log_{doc['date']}.json"
    text = json.dumps(doc, separators=(",", ":"), default=str)
    for folder in (out / "daily", out / "archive" / "daily"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    return name
