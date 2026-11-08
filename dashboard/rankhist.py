"""Rank history: the ranking of every pull, kept for good, and the analysis of how it changes.

rank_history.json (state folder) is a long table, one row per (pull, topic) for the top TOP_N topics of the
ranking of record (pick_rank). It never expires, unlike score_history.json (10 days).
rank_changes.json is the analysis the "Rank changes" tab and the PDF / Excel exports read: one object with
the latest pull vs the pull before, the latest pick of record vs the day before, streaks in the top 10,
rank volatility, top-10 turnover per pull, the path of today's top 10, and the history of daily picks.

Backfill: rank_seed.json (shipped with the app, built from the archive branch) and the local
score_history.json are merged in on start, so the analysis has history from Oct 23 on.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import statistics

SCHEMA = "topiclog.rank_history/1"
TOP_N = 50
TOP_K = 10  # "in the top 10"
CATEGORIES = {"equity": "Stocks", "crypto": "Crypto", "macro": "Macro", "theme": "Themes", "commodity": "Commodities",
              "index": "Indexes", "rates": "Rates", "fx": "FX", "private": "Private companies"}
FIELDS = ("run_ts", "run_et", "topic", "name", "asset_class", "pick_rank", "pick_score", "pick_tier", "chg_24h")

# w2 weights (dashboard/pipeline.py WD): each input's share of the score, by angle
W2 = {"attention_shift": .35, "attention_x": .35, "volume_abn": .125, "momentum": .125, "money_stock": .05}
ANGLE_OF = {"attention_shift": "attention", "attention_x": "attention", "volume_abn": "price", "momentum": "price",
            "money_stock": "money"}
# the four angles: label, the measure used to rank risers / fallers, how to show it
ANGLES = {
    "attention": dict(label="Attention", metric="att", unit="x normal", what="Mentions on Reddit, X and news vs the topic's own 20-day normal (Adanos)"),
    "money": dict(label="Money", metric="money", unit="x normal", what="Prediction-market open interest (money left in the market) vs its normal, Kalshi + Polymarket"),
    "price": dict(label="Price & volume", metric="mom", unit="sigma", what="Size of the 24h price move in typical days (sigma), with trading volume vs normal"),
    "sentiment": dict(label="Sentiment", metric="sent", unit="-1 to 1", what="Average Adanos sentiment of the posts and articles, -1 (negative) to 1 (positive)"),
}


def _et():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def _ct():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/Chicago")


def _r(v, n=4):
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else round(v, n)
    return v


def to_et(run_ts: str) -> str:
    return dt.datetime.fromisoformat(run_ts).astimezone(_et()).strftime("%Y-%m-%d %H:%M")


def to_ct(run_ts: str) -> str:
    return dt.datetime.fromisoformat(run_ts).astimezone(_ct()).strftime("%Y-%m-%d %H:%M")


def record_threshold(day: str) -> int:
    """Minutes after midnight ET from which a pull counts as the day's pick of record.

    15:00 ET until Nov 2 (the old 15:00 slot), 16:10 ET from Nov 3 (the 16:15 ET = 15:15 CT slot)."""
    return 15 * 60 if day < "2026-11-03" else 16 * 60 + 10


def is_record_time(run_et: str) -> bool:
    day, hm = run_et[:10], run_et[11:16]
    return int(hm[:2]) * 60 + int(hm[3:5]) >= record_threshold(day)


def _pct(values):
    """Percentile within the pool (average rank / (n-1)); None stays None; one value = 0.5. Same as scoring.pctrank."""
    idx = sorted((i for i, v in enumerate(values) if v is not None), key=lambda i: values[i])
    out = [None] * len(values)
    n = len(idx)
    if n == 1:
        out[idx[0]] = 0.5
    i = 0
    while n > 1 and i < n:
        j = i
        while j + 1 < n and values[idx[j + 1]] == values[idx[i]]:
            j += 1
        for k in range(i, j + 1):
            out[idx[k]] = ((i + j) / 2) / (n - 1)
        i = j + 1
    return out


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _inputs(r):
    """The raw measures behind the four angles, for one topic on one pull."""
    att = r.get("attention_shift")
    money = r.get("money_stock")
    return {"att": _r(math.exp(att)) if isinstance(att, (int, float)) else None,          # mentions vs 20-day normal, as a multiple
            "att_x": _r(math.exp(r["attention_x"])) if isinstance(r.get("attention_x"), (int, float)) else None,
            "mentions": sum(int(r.get(f"ad_mentions_{p}") or 0) for p in ("reddit", "x", "news")) or None,
            "money": _r(math.exp(money)) if isinstance(money, (int, float)) else None,   # open interest vs normal, as a multiple
            "pm_vol": _r((r.get("k_vol") or 0) + (r.get("p_vol") or 0)) or None,       # prediction-market 24h volume, $
            "mom": _r(abs(r["momentum"]), 2) if isinstance(r.get("momentum"), (int, float)) else None,
            "vol": _r(math.exp(r["volume_abn"])) if isinstance(r.get("volume_abn"), (int, float)) else None,
            "sent": _r(_mean([r.get(f"ad_sent_d_{p}") for p in ("reddit", "x", "news")]), 3)}


def rows_from_pull(run_ts: str, rows: list) -> list:
    """Top TOP_N of a pull's topic_log rows by pick_rank (falls back to rank when a pull had no pick_rank), with the
    inputs behind the four angles and each w2 input's contribution to the score (weight x percentile in the pool)."""
    key = "pick_rank" if any(r.get("pick_rank") for r in rows) else "rank"
    live = [r for r in rows if r.get(key)]
    pct = {c: _pct([r.get(c) for r in live]) for c in W2}
    contrib = {}
    for i, r in enumerate(live):
        c = {"attention": 0.0, "price": 0.0, "money": 0.0}
        for col, w in W2.items():
            c[ANGLE_OF[col]] += w * (pct[col][i] if pct[col][i] is not None else 0.5)
        contrib[r["topic"]] = {k: round(v, 4) for k, v in c.items()}
    top = sorted(live, key=lambda r: r[key])[:TOP_N]
    et = to_et(run_ts)
    return [{"run_ts": run_ts, "run_et": et, "topic": r["topic"], "name": r.get("name"), "asset_class": r.get("asset_class"),
             "pick_rank": r.get(key), "pick_score": _r(r.get("pick_score") if key == "pick_rank" else r.get("demand_score")),
             "pick_tier": r.get("pick_tier") if key == "pick_rank" else r.get("tier"), "chg_24h": _r(r.get("chg_24h")),
             "in": _inputs(r), "c": contrib[r["topic"]] if key == "pick_rank" else None}
            for r in top]


def merge(history: list, new_rows: list) -> list:
    """Add rows of pulls not yet in history. A pull already present is kept, unless it has no inputs and the new rows do."""
    rich = {h["run_ts"] for h in history if h.get("in")}
    have = {h["run_ts"] for h in history}
    new_rich = {r["run_ts"] for r in new_rows if r.get("in")}
    replace = (new_rich & have) - rich
    add = [r for r in new_rows if r["run_ts"] not in have or r["run_ts"] in replace]
    if not add:
        return history
    out = [h for h in history if h["run_ts"] not in replace] + add
    out.sort(key=lambda h: (h["run_ts"], h.get("pick_rank") or 0))
    return out


def from_score_history(score_history: list, names: dict) -> list:
    """Rows from the 10-day score_history.json (backfill on start). names: topic -> (name, asset_class)."""
    by = {}
    for h in score_history:
        if h.get("pick_rank"):
            by.setdefault(h["run_ts"], []).append(h)
    out = []
    for ts, hs in by.items():
        et = to_et(ts)
        for h in sorted(hs, key=lambda x: x["pick_rank"])[:TOP_N]:
            n, c = names.get(h["topic"], (None, None))
            out.append({"run_ts": ts, "run_et": et, "topic": h["topic"], "name": n, "asset_class": c,
                        "pick_rank": h["pick_rank"], "pick_score": _r(h.get("pick_score")), "pick_tier": h.get("tier"), "chg_24h": None})
    return out


def snapshot(run_ts: str, rows: list) -> dict:
    """One pull's full ranking as a readable file for the Desktop data folder (rank_history/)."""
    key = "pick_rank" if any(r.get("pick_rank") for r in rows) else "rank"
    top = sorted((r for r in rows if r.get(key)), key=lambda r: r[key])
    cats = {}
    for r in top:
        cats.setdefault(r.get("asset_class") or "other", []).append(r)
    slim = lambda r, k: {"rank": r[key], "category_rank": k, "topic": r["topic"], "name": r.get("name"),
                         "category": CATEGORIES.get(r.get("asset_class"), r.get("asset_class")),
                         "score": _r(r.get("pick_score") if key == "pick_rank" else r.get("demand_score")),
                         "tier": r.get("pick_tier") if key == "pick_rank" else r.get("tier"),
                         "price": _r(r.get("price")), "chg_24h": _r(r.get("chg_24h")), "is_new": r.get("is_new")}
    pos = {r["topic"]: i + 1 for c in cats.values() for i, r in enumerate(c)}
    return {"schema": SCHEMA, "run_ts": run_ts, "run_et": to_et(run_ts), "run_ct": to_ct(run_ts),
            "pick_of_record": is_record_time(to_et(run_ts)), "scored": len(top),
            "ranking": [slim(r, pos[r["topic"]]) for r in top],
            "notes": "Ranking of record (pick_rank, w2). Facts from public data; not investment advice."}


# ------------------------------------------------------------------ analysis
def _pulls(history):
    by = {}
    for h in history:
        by.setdefault(h["run_ts"], []).append(h)
    return [(ts, sorted(by[ts], key=lambda x: x["pick_rank"])) for ts in sorted(by)]


def _record_pulls(pulls):
    """One pull per ET day: the first at or after the pick-of-record time, else the day's last pull."""
    days = {}
    for ts, rows in pulls:
        et = rows[0]["run_et"] if rows else to_et(ts)
        days.setdefault(et[:10], []).append((ts, et, rows))
    out = []
    for d in sorted(days):
        ps = days[d]
        rec = next((p for p in ps if is_record_time(p[1])), None)
        out.append((d, *(rec or ps[-1]), rec is not None))
    return out


def _diff(a_rows, b_rows, k=TOP_K):
    """Changes from pull a (older) to pull b (newer)."""
    ra = {r["topic"]: r["pick_rank"] for r in a_rows}
    rb = {r["topic"]: r for r in b_rows}
    top_a = {t for t, k_ in ra.items() if k_ <= k}
    top_b = {t for t, r in rb.items() if r["pick_rank"] <= k}
    info = {r["topic"]: r for r in a_rows} | rb
    entered = [{"topic": t, "name": info[t].get("name"), "category": CATEGORIES.get(info[t].get("asset_class"), info[t].get("asset_class")),
                "rank": rb[t]["pick_rank"], "prev_rank": ra.get(t)} for t in top_b - top_a]
    dropped = [{"topic": t, "name": info[t].get("name"), "category": CATEGORIES.get(info[t].get("asset_class"), info[t].get("asset_class")),
                "rank": rb[t]["pick_rank"] if t in rb else None, "prev_rank": ra[t]} for t in top_a - top_b]
    moves = []
    for t, r in rb.items():
        if t in ra and (r["pick_rank"] <= 20 or ra[t] <= 20):
            moves.append({"topic": t, "name": r.get("name"), "category": CATEGORIES.get(r.get("asset_class"), r.get("asset_class")),
                          "rank": r["pick_rank"], "prev_rank": ra[t], "change": ra[t] - r["pick_rank"]})
    moves.sort(key=lambda m: -abs(m["change"]))
    entered.sort(key=lambda e: e["rank"])
    dropped.sort(key=lambda e: e["prev_rank"])
    turnover = len(top_b - top_a) / k if top_a else None
    return {"entered": entered, "dropped": dropped, "movers": [m for m in moves if m["change"]][:15], "turnover": turnover}


def analyze(history: list) -> dict:
    pulls = _pulls(history)
    if not pulls:
        return {"schema": SCHEMA, "pulls": 0}
    rec = _record_pulls(pulls)
    last_ts, last_rows = pulls[-1]
    out = {"schema": SCHEMA, "pulls": len(pulls), "days": len(rec), "first_et": to_et(pulls[0][0]), "last_et": to_et(last_ts),
           "last_ct": to_ct(last_ts), "top_k": TOP_K}

    out["angles_meta"] = ANGLES
    rich = [(ts, rows) for ts, rows in pulls if any(r.get("in") for r in rows)]
    rich_rec = [p for p in rec if any(r.get("in") for r in p[3])]
    if len(rich) > 1:
        out["angles_pull"] = {"from_et": to_et(rich[-2][0]), "to_et": to_et(rich[-1][0]), **_angles(rich[-2][1], rich[-1][1])}
        out["drivers_pull"] = _drivers(rich[-2][1], rich[-1][1])
    if len(rich_rec) > 1:
        a, b = rich_rec[-2], rich_rec[-1]
        out["angles_day"] = {"from_et": a[2], "to_et": b[2], **_angles(a[3], b[3])}
        out["drivers_day"] = _drivers(a[3], b[3])
    out["latest"] = {"top": [{"rank": r["pick_rank"], "topic": r["topic"], "name": r.get("name"),
                              "category": CATEGORIES.get(r.get("asset_class"), r.get("asset_class")), "score": r.get("pick_score"),
                              "tier": r.get("pick_tier"), "chg_24h": r.get("chg_24h")} for r in last_rows[:20]]}
    if len(pulls) > 1:
        out["vs_prev_pull"] = {"from_et": to_et(pulls[-2][0]), "to_et": to_et(last_ts), **_diff(pulls[-2][1], last_rows)}
    if len(rec) > 1:
        a, b = rec[-2], rec[-1]
        out["vs_prev_day"] = {"from_et": a[2], "to_et": b[2], **_diff(a[3], b[3])}

    # streaks: consecutive record days in the top 10 up to the latest record day; total days in the top 10
    in_top = [{r["topic"] for r in p[3] if r["pick_rank"] <= TOP_K} for p in rec]
    names = {}
    for _, rows in pulls:
        for r in rows:
            names[r["topic"]] = (r.get("name"), r.get("asset_class"))
    streaks = []
    for t in {t for s in in_top for t in s}:
        cur = 0
        for s in reversed(in_top):
            if t not in s:
                break
            cur += 1
        total = sum(1 for s in in_top if t in s)
        best = run = 0
        for s in in_top:
            run = run + 1 if t in s else 0
            best = max(best, run)
        n, c = names.get(t, (None, None))
        streaks.append({"topic": t, "name": n, "category": CATEGORIES.get(c, c), "current_streak": cur, "longest_streak": best,
                        "days_in_top": total, "days": len(in_top), "rank_now": next((r["pick_rank"] for r in rec[-1][3] if r["topic"] == t), None)})
    streaks.sort(key=lambda s: (-s["current_streak"], -s["days_in_top"], s["rank_now"] or 999))
    out["streaks"] = streaks[:30]

    # volatility over all pulls, topics seen in the top 20 at least 3 times
    seen = {}
    for _, rows in pulls:
        for r in rows:
            seen.setdefault(r["topic"], []).append(r["pick_rank"])
    vol = []
    for t, ranks in seen.items():
        if sum(1 for x in ranks if x <= 20) >= 3:
            n, c = names.get(t, (None, None))
            vol.append({"topic": t, "name": n, "category": CATEGORIES.get(c, c), "pulls": len(ranks), "mean_rank": round(statistics.mean(ranks), 1),
                        "sd_rank": round(statistics.pstdev(ranks), 1), "best": min(ranks), "worst": max(ranks),
                        "times_no1": sum(1 for x in ranks if x == 1)})
    vol.sort(key=lambda v: (-v["sd_rank"], v["mean_rank"]))
    out["volatility"] = vol[:30]

    # turnover of the top 10, pull to pull
    out["turnover"] = [{"run_et": to_et(pulls[i][0]), "turnover": _diff(pulls[i - 1][1], pulls[i][1])["turnover"],
                        "top": pulls[i][1][0]["topic"] if pulls[i][1] else None} for i in range(1, len(pulls))]

    # path of the latest top 10 across every pull (rank, or None when outside the top 50)
    watch = [r["topic"] for r in last_rows[:TOP_K]]
    out["paths"] = [{"run_et": to_et(ts), **{t: next((r["pick_rank"] for r in rows if r["topic"] == t), None) for t in watch}}
                    for ts, rows in pulls]
    out["path_topics"] = watch

    # daily picks of record, and where each pick stood on the next record day
    picks = []
    for i, (d, ts, et, rows, is_rec) in enumerate(rec):
        if not rows:
            continue
        t = rows[0]
        nxt = next((r["pick_rank"] for r in rec[i + 1][3] if r["topic"] == t["topic"]), None) if i + 1 < len(rec) else None
        picks.append({"date": d, "run_et": et, "of_record": is_rec, "topic": t["topic"], "name": t.get("name"),
                      "category": CATEGORIES.get(t.get("asset_class"), t.get("asset_class")), "score": t.get("pick_score"),
                      "next_day_rank": nxt, "has_next": i + 1 < len(rec)})
    out["picks"] = picks[::-1]
    return out


def _angles(a_rows, b_rows, n=6):
    """Per angle: the topics whose measure rose and fell most from pull a to pull b (topics in the top 50 both times)."""
    ra = {r["topic"]: r for r in a_rows if r.get("in")}
    out = {}
    for key, meta in ANGLES.items():
        m = meta["metric"]
        ch = []
        for r in b_rows:
            o = ra.get(r["topic"])
            if not (o and r.get("in")):
                continue
            x0, x1 = o["in"].get(m), r["in"].get(m)
            if x0 is None or x1 is None:
                continue
            ch.append({"topic": r["topic"], "name": r.get("name"), "category": CATEGORIES.get(r.get("asset_class"), r.get("asset_class")),
                       "before": x0, "after": x1, "change": round(x1 - x0, 3), "rank": r["pick_rank"], "prev_rank": o["pick_rank"],
                       "extra": {"mentions": r["in"].get("mentions"), "pm_vol": r["in"].get("pm_vol"), "vol": r["in"].get("vol")}})
        ch.sort(key=lambda x: -x["change"])
        out[key] = {"up": [x for x in ch if x["change"] > 0][:n], "down": [x for x in ch[::-1] if x["change"] < 0][:n]}
    return {"angles": out}


def _drivers(a_rows, b_rows, n=12):
    """Biggest rank moves (top 20 either time) and which angle moved the score: change in each angle's contribution."""
    ra = {r["topic"]: r for r in a_rows}
    out = []
    for r in b_rows:
        o = ra.get(r["topic"])
        if not (o and r.get("c") and o.get("c")) or (r["pick_rank"] > 20 and o["pick_rank"] > 20):
            continue
        d = {k: round(r["c"][k] - o["c"][k], 4) for k in r["c"]}
        main = max(d, key=lambda k: abs(d[k]))
        out.append({"topic": r["topic"], "name": r.get("name"), "category": CATEGORIES.get(r.get("asset_class"), r.get("asset_class")),
                    "prev_rank": o["pick_rank"], "rank": r["pick_rank"], "places": o["pick_rank"] - r["pick_rank"],
                    "score_change": round((r.get("pick_score") or 0) - (o.get("pick_score") or 0), 4), "by_angle": d,
                    "main": ANGLES[main]["label"] if abs(d[main]) > 0.005 else "No single angle"})
    out.sort(key=lambda x: -abs(x["places"]))
    return [x for x in out if x["places"]][:n]


def by_category(rows: list, per=10) -> list:
    """Latest pull ranked within each category (for the exports)."""
    cats = {}
    for r in sorted((r for r in rows if r.get("pick_rank")), key=lambda r: r["pick_rank"]):
        cats.setdefault(r.get("asset_class") or "other", []).append(r)
    order = list(CATEGORIES) + [c for c in cats if c not in CATEGORIES]
    out = []
    for c in order:
        for i, r in enumerate(cats.get(c, [])[:per]):
            out.append({"category": CATEGORIES.get(c, c), "category_rank": i + 1, "rank": r["pick_rank"], "topic": r["topic"],
                        "name": r.get("name"), "score": _r(r.get("pick_score")), "tier": r.get("pick_tier"),
                        "price": _r(r.get("price")), "chg_24h": _r(r.get("chg_24h"))})
    return out


def update(state: pathlib.Path, run_ts: str, rows: list) -> tuple[list, dict]:
    """Called by every pull: add this pull to rank_history.json and return (history, analysis)."""
    p = state / "rank_history.json"
    try:
        hist = json.loads(p.read_text())
    except Exception:
        hist = []
    hist = merge(hist, rows_from_pull(run_ts, rows))
    return hist, analyze(hist)
