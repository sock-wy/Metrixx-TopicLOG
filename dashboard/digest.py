"""A compact JSON of one pull for Claude (or any model) to read: claude_digest.json.

Everything a reader needs to talk about today's ranking in ~15 KB instead of the ~10 MB of full datasets:
the run, the scoring method, the top 20 topics with their inputs, percentiles, best events and news, rank changes
since the previous pull, the sector movers on each platform, and the briefing. Written as a one-element list
(the dashboard's datasets are lists); the object inside is the digest.
"""
from __future__ import annotations

import math

SCHEMA = "topiclog.claude_digest/1"
INPUTS = (  # w2 inputs: field in topic_log -> name in the digest
    ("attention_shift", "attention_vs_normal"),
    ("attention_x", "x_attention_vs_normal"),
    ("volume_abn", "volume_vs_normal"),
    ("momentum", "move_in_sigmas"),
    ("money_stock", "open_interest_vs_normal"),
)
GLOSSARY = {
    "score": "weighted mean of the topic's within-pull percentiles (0-1); rank 1 = best episode candidate",
    "attention_vs_normal": "log ratio of yesterday's Adanos mentions (Reddit+X+News) to the topic's own 19-day mean",
    "x_attention_vs_normal": "the same on X only",
    "volume_vs_normal": "log ratio of volume traded so far today to the same hours of the previous 20 sessions",
    "move_in_sigmas": "|24h price change| / the month's daily volatility",
    "open_interest_vs_normal": "Kalshi + Polymarket open interest vs its own mean over earlier pulls",
    "pct": "the topic's percentile among scored topics this pull, per input (0-1)",
    "prev_rank": "rank in the previous pull (null = not ranked then)",
    "tier": "T1 catalyst within 2 trading days and an active market; T2 money flow and attention; T3 strong attention; T4 rest (labels only)",
    "news.sentiment": "Adanos sentiment of the article, -1 to 1",
    "sectors": "Adanos trending sectors, last complete UTC day vs the day before; buzz 0-100",
}


def _r(v, n=3):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, n)
    return v


def _pct(values: dict) -> dict:
    """Percentile (0-1, ties averaged) of each key's value among the non-null values."""
    xs = sorted(v for v in values.values() if v is not None)
    n = len(xs)
    if n < 2:
        return {k: (0.5 if v is not None else None) for k, v in values.items()}
    out = {}
    for k, v in values.items():
        if v is None:
            out[k] = None
            continue
        lo = sum(1 for x in xs if x < v)
        eq = sum(1 for x in xs if x == v)
        out[k] = round((lo + (eq - 1) / 2) / (n - 1), 3)
    return out


def build(run: dict, weights: dict, rows: list, events: list, history: list, sectors: list, news: list,
          briefing: list, top_n: int = 20) -> list:
    scored = [r for r in rows if r.get("pick_rank")]
    pcts = {f: _pct({r["topic"]: r.get(f) for r in scored}) for f, _ in INPUTS}

    # rank in the previous pull
    run_ts = run.get("run_ts")
    prev_ts = max((h["run_ts"] for h in history if h.get("run_ts") and h["run_ts"] < (run_ts or "")), default=None)
    prev_rank = {h["topic"]: h.get("pick_rank") for h in history if prev_ts and h.get("run_ts") == prev_ts}

    ev_by = {}
    for e in events:
        ev_by.setdefault(e.get("topic"), []).append(e)
    news_by = {}
    for n in news:
        news_by.setdefault(n.get("topic"), []).append(n)

    top = []
    for r in sorted(scored, key=lambda x: x["pick_rank"])[:top_n]:
        t = r["topic"]
        evs = sorted(ev_by.get(t, []), key=lambda e: -((e.get("volume_24h") or 0) + (e.get("open_interest") or 0) / 10))[:2]
        nws = news_by.get(t, [])
        top.append({
            "rank": r["pick_rank"], "prev_rank": prev_rank.get(t), "topic": t, "name": r.get("name"),
            "class": r.get("asset_class"), "score": _r(r.get("pick_score")), "tier": r.get("pick_tier"),
            "catalyst": r.get("catalyst"), "new_topic": bool(r.get("is_new")),
            "price": _r(r.get("price"), 4), "chg_24h": _r(r.get("chg_24h")), "chg_5d": _r(r.get("chg_5d")),
            "inputs": {name: _r(r.get(f)) for f, name in INPUTS},
            "pct": {name: pcts[f].get(t) for f, name in INPUTS},
            "mentions": {p: r.get(f"ad_mentions_{p}") for p in ("reddit", "x", "news") if r.get(f"ad_mentions_{p}") is not None},
            "events": [{"source": e.get("source"), "title": e.get("title"), "price": _r(e.get("top_price")),
                        "volume_24h": _r(e.get("volume_24h"), 0), "open_interest": _r(e.get("open_interest"), 0)} for e in evs],
            "news": ({"articles_2d": nws[0].get("topic_mentions"), "positive": nws[0].get("positive"),
                      "negative": nws[0].get("negative"),
                      "headlines": [{"text": (n.get("headline") or "")[:160], "sentiment": _r(n.get("sentiment"), 2),
                                     "source": n.get("source"), "time_utc": n.get("time")} for n in nws[:2]]}
                     if nws else None),
        })

    entered = [x["topic"] for x in top[:10] if x["prev_rank"] is None or x["prev_rank"] > 10]
    top10_now = {x["topic"] for x in top[:10]}
    left = sorted((t for t, k in prev_rank.items() if k and k <= 10 and t not in top10_now), key=lambda t: prev_rank[t])

    sec = {}
    for plat in ("news", "x", "reddit"):
        ps = [s for s in sectors if s.get("platform") == plat and s.get("buzz_chg") is not None]
        if not ps:
            continue
        pick = lambda s: {"sector": s.get("sector"), "rank": s.get("rank"), "rank_prev": s.get("rank_prev"),
                          "buzz": _r(s.get("buzz"), 1), "buzz_chg": _r(s.get("buzz_chg"), 1),
                          "buzz_7d_chg": _r(s.get("buzz_7d_chg"), 1), "mentions_chg_pct": _r(s.get("mentions_chg_pct"), 0),
                          "sentiment": _r(s.get("sentiment"), 2), "top_tickers": s.get("top_tickers")}
        ps.sort(key=lambda s: s["buzz_chg"])
        sec[plat] = {"date": ps[0].get("date"), "top": pick(min(ps, key=lambda s: s.get("rank") or 99)),
                     "risers": [pick(s) for s in reversed(ps[-3:]) if s["buzz_chg"] > 0],
                     "fallers": [pick(s) for s in ps[:2] if s["buzz_chg"] < 0]}

    keys = ("kalshi", "adanos", "prices", "polymarket_status", "us_movers_status", "us_stocks_status",
            "earnings_calendar_status", "crypto_spot_status", "perps")
    return [{
        "schema": SCHEMA,
        "about": "Metrixx Topic Log: market topics ranked by how likely they are to carry today's MYCAST episode. "
                 "Facts from public data; not investment advice. The 15:00 ET pull is the pick of record.",
        "run": {"run_et": run.get("run_et"), "run_ts": run_ts, "pick_version": run.get("pick_version"),
                "topics": run.get("topics"), "scored": run.get("scored"), "gated": run.get("gated"),
                "sources": {k: run.get(k) for k in keys if run.get(k) is not None}},
        "method": {"weights": weights, "missing_input": "median", "gates": "G2 prediction-market volume in 24h; "
                   "G3 Kalshi zero-trade share <= 80% and spread <= $0.30 on the 3 strikes nearest 50%"},
        "top": top,
        "top10_changes": {"entered": entered, "left": left, "previous_pull": prev_ts},
        "sectors": sec,
        "briefing": [{"section": b.get("section"), "source": b.get("source"), "text": b.get("text")} for b in briefing],
        "glossary": GLOSSARY,
    }]
