"""Study `broad_v2`: point-in-time features and labels for every Topic Log topic with an hourly price.

Replays the dashboard's 15:00 ET pull on each trading day from the backfill (see dashboard/backfill/):
  Kalshi hourly candles  -> k_vol, k_flow, k_oi, k_oi_chg, k_move, k_spread, k_zero
  Polymarket daily price -> p_move, p_active
  Adanos daily, per platform (reddit, x, news) -> 1-day changes (as the dashboard) and 3-day smoothed changes
  Yahoo hourly / daily   -> price at the pick, momentum, labels

Nothing dated after the pick is used for a feature: Kalshi bars that end by 15:00 ET, Polymarket prices
stamped before 15:00 ET, Adanos complete UTC days up to t-1, prices from completed hourly bars.

Labels (both strictly after the pick):
  move  = |ln(P(next session, same time) / P(pick))| / sigma20 (daily log returns before t)
  attn  = ln((1 + mentions on UTC day t+1) / (1 + mean mentions over UTC days t-20..t-1)), summed over reddit+x+news

Writes backtest/broad/features.parquet (one row per topic per day).
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard import symbols  # noqa: E402
from dashboard.registry import Registry  # noqa: E402

BF = pathlib.Path("/home/claude/backfill/data")
OUT = ROOT / "backtest" / "broad"
OUT.mkdir(exist_ok=True)
ET = dt.timezone(dt.timedelta(hours=-4))  # whole window is EDT (DST ends 2026-11-01)
START, END = dt.date(2026, 8, 26), dt.date(2026, 10, 21)
PLATS = ["reddit", "x", "news"]


def pick_ts(d):
    return pd.Timestamp(dt.datetime(d.year, d.month, d.day, 15, 0, tzinfo=ET)).tz_convert("UTC")


# ------------------------------------------------------------------ prices
def load_prices():
    h = pd.read_parquet(BF / "yahoo/topics_1h.parquet")
    h["end"] = h["ts"] + pd.Timedelta(hours=1)
    d1 = pd.read_parquet(BF / "yahoo/topics_1d.parquet")
    d1["date"] = d1["ts"].dt.tz_convert("America/New_York").dt.date
    return h, d1


def price_at(series_end, series_close, t):
    """Close of the last hourly bar completed by t (within 4 days)."""
    i = np.searchsorted(series_end, t, side="right") - 1
    if i < 0 or (t - series_end[i]) > np.timedelta64(4, "D"):
        return np.nan
    return series_close[i]


# ------------------------------------------------------------------ main
def build():
    days = [d for d in pd.bdate_range(START, END).date]
    h, d1 = load_prices()
    topics = sorted(h["topic"].unique())
    cls = h.groupby("topic")["asset_class"].first().to_dict()

    # sigma20 from daily closes strictly before t
    sig = {}
    for tp, g in d1.groupby("topic"):
        s = g.sort_values("ts").drop_duplicates("date", keep="last").set_index("date")["close"]
        r = np.log(s).diff().dropna()
        sig[tp] = r

    # per-topic hourly arrays
    H = {}
    for tp, g in h.groupby("topic"):
        g = g.sort_values("end")
        H[tp] = (g["end"].values.astype("datetime64[ns]"), g["close"].values)

    rows = []
    for i, d in enumerate(days):
        t = pick_ts(d).to_datetime64()
        nxt = days[i + 1] if i + 1 < len(days) else d + dt.timedelta(days=1 if d.weekday() < 4 else 3)
        prv = pd.bdate_range(end=d - dt.timedelta(days=1), periods=1).date[0]
        t_n, t_p = pick_ts(nxt).to_datetime64(), pick_ts(prv).to_datetime64()
        for tp in topics:
            ends, close = H[tp]
            c = cls.get(tp)
            # crypto trades every day: next = +24h, prev = -24h
            tn = t + np.timedelta64(24, "h") if c == "crypto" else t_n
            tq = t - np.timedelta64(24, "h") if c == "crypto" else t_p
            p0, p1, pm = price_at(ends, close, t), price_at(ends, close, tn), price_at(ends, close, tq)
            r = sig.get(tp)
            s20 = np.nan
            if r is not None:
                hist = r[r.index < d]
                if len(hist) >= 20:
                    s20 = hist.iloc[-20:].std(ddof=1)
            if not (p0 > 0) or not (s20 > 0):
                continue
            rows.append(dict(date=d, topic=tp, asset_class=c, price=p0, sigma20=s20,
                             label_move=abs(np.log(p1 / p0)) / s20 if p1 > 0 else np.nan,
                             momentum=abs(np.log(p0 / pm)) / s20 if pm > 0 else np.nan))
    base = pd.DataFrame(rows)
    print("price rows", len(base), "topics", base.topic.nunique(), "days", base.date.nunique())

    base = base.merge(kalshi_features(days), on=["date", "topic"], how="left")
    base = base.merge(poly_features(days), on=["date", "topic"], how="left")
    base = base.merge(adanos_features(days, base.topic.unique()), on=["date", "topic"], how="left")
    base.to_parquet(OUT / "features.parquet", index=False)
    print("wrote", OUT / "features.parquet", base.shape)
    return base


def kalshi_features(days):
    k = pd.read_parquet(BF / "kalshi/candles_1h.parquet")
    ev = pd.read_parquet(BF / "kalshi/events.parquet", columns=["event", "close_time"])
    k = k.merge(ev, on="event", how="left")
    k["ts"] = k["ts"].astype("datetime64[ns, UTC]")
    k["close_time"] = pd.to_datetime(k["close_time"], utc=True)
    k["mid"] = (k["yes_bid"] + k["yes_ask"]) / 2
    k["spr"] = k["yes_ask"] - k["yes_bid"]
    out = []
    for d in days:
        t = pick_ts(d)
        w = k[(k.ts > t - pd.Timedelta(hours=48)) & (k.ts <= t)]
        if w.empty:
            continue
        cur = w[w.ts > t - pd.Timedelta(hours=24)]
        prev = w[w.ts <= t - pd.Timedelta(hours=24)]
        vol1 = cur.groupby("topic").volume.sum()
        vol0 = prev.groupby("topic").volume.sum()
        last = w.sort_values("ts").groupby("market").tail(1)
        last_prev = prev.sort_values("ts").groupby("market").tail(1)
        both = last.merge(last_prev[["market", "open_interest", "mid", "yes_bid", "yes_ask"]], on="market", suffixes=("", "_p"))
        oi1 = both.groupby("topic").open_interest.sum()
        oi0 = both.groupby("topic").open_interest_p.sum()
        oi_now = last.groupby("topic").open_interest.sum()
        mvol = cur.groupby("market").volume.sum().rename("v24")
        both = both.merge(mvol, on="market", how="left").fillna({"v24": 0})
        ok = both[(both.v24 > 0) & both.yes_bid.gt(0) & both.yes_ask.lt(1) & both.yes_bid_p.gt(0) & both.yes_ask_p.lt(1)
                  & (both.mid.between(0.01, 0.99)) & (both.close_time > t + pd.Timedelta(hours=24))]
        ok = ok.assign(dm=(ok.mid - ok.mid_p).abs())
        move = ok.groupby("topic").apply(lambda g: np.average(g.dm, weights=g.v24), include_groups=False)
        # G3: the 3 quoted strikes nearest 50% in the topic's most traded event
        ev_vol = cur.groupby(["topic", "event"]).volume.sum().reset_index().sort_values("volume").groupby("topic").tail(1)
        lm = last.merge(mvol, on="market", how="left").fillna({"v24": 0})
        lm = lm[lm.event.isin(ev_vol.event) & lm.yes_bid.notna() & lm.yes_ask.notna() & (lm.spr <= 0.5)]
        lm = lm.assign(dist=(lm.mid - 0.5).abs()).sort_values("dist").groupby("topic").head(3)
        spread = lm.groupby("topic").spr.mean()
        zero = lm.groupby("topic").v24.apply(lambda s: float((s <= 0).mean()))
        f = pd.DataFrame({"k_vol": vol1, "k_vol_prev": vol0, "k_oi": oi_now, "k_oi1": oi1, "k_oi0": oi0,
                          "k_move": move, "k_spread": spread, "k_zero": zero})
        f["k_flow"] = np.where(f.k_vol_prev > 0, f.k_vol / f.k_vol_prev - 1, np.nan)
        f["k_oi_chg"] = np.where(f.k_oi0 > 0, f.k_oi1 / f.k_oi0 - 1, np.nan)
        f = f.drop(columns=["k_oi1", "k_oi0"]).reset_index().rename(columns={"index": "topic"})
        f["date"] = d
        out.append(f)
    f = pd.concat(out)
    print("kalshi rows", len(f))
    return f


def poly_features(days):
    m = pd.read_parquet(BF / "polymarket/markets.parquet")
    us = __import__("json").load(open("/home/claude/work/v2out2/us_stocks.json")) if pathlib.Path("/home/claude/work/v2out2/us_stocks.json").exists() \
        else __import__("json").load(open("/home/claude/work/v2out/us_stocks.json"))
    reg = Registry(us, symbols.CRYPTO, {})
    tmap = {}
    for eid, title in m.groupby("event_id").event_title.first().items():
        tp, how = reg.match(title)[:2]
        if tp:
            tmap[eid] = tp
    m["topic"] = m.event_id.map(tmap)
    m = m.dropna(subset=["topic"])
    p = pd.read_parquet(BF / "polymarket/prices_1d.parquet")
    p = p[p.market_id.isin(m.market_id)].merge(m[["market_id", "topic", "volume"]], on="market_id")
    p["ts"] = p["ts"].astype("datetime64[ns, UTC]")
    out = []
    for d in days:
        t = pick_ts(d)
        a = p[(p.ts <= t) & (p.ts > t - pd.Timedelta(hours=26))].sort_values("ts").groupby("market_id").tail(1)
        b = p[(p.ts <= t - pd.Timedelta(hours=24)) & (p.ts > t - pd.Timedelta(hours=50))].sort_values("ts").groupby("market_id").tail(1)
        j = a.merge(b[["market_id", "price"]], on="market_id", suffixes=("", "_p"))
        j = j[j.price.between(0.01, 0.99)]
        j["dm"] = (j.price - j.price_p).abs()
        g = j.groupby("topic")
        f = pd.DataFrame({"p_move": g.apply(lambda x: np.average(x.dm, weights=x.volume.clip(lower=1)), include_groups=False),
                          "p_markets": g.size()}).reset_index()
        f["date"] = d
        out.append(f)
    f = pd.concat(out)
    print("polymarket rows", len(f), "topics", f.topic.nunique())
    return f


def adanos_features(days, topics):
    a = pd.read_parquet(BF / "adanos/daily_by_symbol.parquet")
    a = a[a.platform.isin(PLATS + ["reddit"])]
    a["date"] = pd.to_datetime(a["date"]).dt.date
    sym = {}
    for tp in topics:
        info = symbols.topic_info(tp, fallback_class="equity")
        if info["adanos_symbol"]:
            sym[(info["adanos_kind"], info["adanos_symbol"])] = tp
        elif info["asset_class"] == "equity":
            sym[("stocks", tp)] = tp
    a["topic"] = [sym.get((k, s)) for k, s in zip(a.kind, a.symbol)]
    a = a.dropna(subset=["topic"])
    piv = {}
    for (tp, pl), g in a.groupby(["topic", "platform"]):
        piv[(tp, pl)] = g.set_index("date")[["buzz_score", "mentions", "sentiment_score"]]
    out = []
    for d in days:
        D = [d - dt.timedelta(days=k) for k in range(0, 22)]  # D[1] = t-1 (last complete UTC day)
        for tp in topics:
            row = {"date": d, "topic": tp}
            any_ = False
            ment_next, ment_hist = 0.0, []
            for pl in PLATS:
                g = piv.get((tp, pl))
                if g is None:
                    continue
                any_ = True
                val = lambda day, c: g.at[day, c] if day in g.index else np.nan  # noqa: E731
                men = lambda day: g.at[day, "mentions"] if day in g.index else 0.0  # noqa: E731
                b1, b2 = val(D[1], "buzz_score"), val(D[2], "buzz_score")
                m1, m2 = men(D[1]), men(D[2])
                s1, s2 = val(D[1], "sentiment_score"), val(D[2], "sentiment_score")
                row[f"ad_buzz_d_{pl}"] = b1 - b2 if not (np.isnan(b1) or np.isnan(b2)) else np.nan
                row[f"ad_ment_chg_{pl}"] = (m1 / m2 - 1) * 100 if m2 > 0 else (np.nan if m1 == 0 else 100.0)
                row[f"ad_sent_d_{pl}"] = s1 - s2 if not (np.isnan(s1) or np.isnan(s2)) else np.nan
                # 3-day smoothing (study adanos_crypto, A3)
                bb = [val(D[k], "buzz_score") for k in range(1, 7)]
                mm = [men(D[k]) for k in range(1, 7)]
                ss = [val(D[k], "sentiment_score") for k in range(1, 7)]
                b3, b6 = np.nanmean(bb[:3]) if not all(np.isnan(bb[:3])) else np.nan, np.nanmean(bb[3:]) if not all(np.isnan(bb[3:])) else np.nan
                row[f"ad3_buzz_d_{pl}"] = b3 - b6
                row[f"ad3_ment_chg_{pl}"] = (sum(mm[:3]) / sum(mm[3:]) - 1) * 100 if sum(mm[3:]) > 0 else np.nan
                s3, s6 = (np.nanmean(ss[:3]) if not all(np.isnan(ss[:3])) else np.nan), (np.nanmean(ss[3:]) if not all(np.isnan(ss[3:])) else np.nan)
                row[f"ad3_sent_d_{pl}"] = s3 - s6
                row[f"ad_mentions_{pl}"] = m1
                # attention label: day t+1 (UTC) vs the 20 days before t
                nd = d + dt.timedelta(days=1)
                ment_next += men(nd)
                ment_hist.append([men(D[k]) for k in range(1, 21)])
            if not any_:
                continue
            hist = np.sum(ment_hist, axis=0).mean() if ment_hist else np.nan
            row["label_attn"] = np.log1p(ment_next) - np.log1p(hist) if d + dt.timedelta(days=1) <= dt.date(2026, 10, 21) else np.nan
            row["ad_level_z"] = np.log1p(np.sum(ment_hist, axis=0)[0]) - np.log1p(np.sum(ment_hist, axis=0)[1:].mean()) if ment_hist else np.nan
            out.append(row)
    f = pd.DataFrame(out)
    print("adanos rows", len(f), "topics", f.topic.nunique())
    return f


if __name__ == "__main__":
    build()
