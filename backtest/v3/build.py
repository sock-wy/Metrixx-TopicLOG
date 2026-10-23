"""Study v3: point-in-time feature panel for the direction backtests (A social, B price, C prediction markets).

Pick time: 15:00 ET on each trading day t. Every feature uses only data available then:
  prices      hourly bars that ended by 15:00 ET                        (Yahoo: Topic Log topics + 2,000 largest stocks)
  Adanos      complete UTC days up to t-1                                 (daily per symbol, reddit / x / news / polymarket)
  Kalshi      hourly candles that ended by 15:00 ET                       (before and after Kalshi's historical cutoff)
  perps       daily candles and funding settled by 15:00 ET
  Polymarket  daily prices stamped before 15:00 ET
Labels (after the pick):
  move  |ln P(t+1, 15:00) / P(t, 15:00)| / sigma20 (daily log returns before t)
  attn  ln(1 + mentions on UTC day t+1) - ln(1 + mean mentions over t-20..t-1), reddit + x + news
Output: backtest/v3/panel.parquet (one row per entity per trading day).
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dashboard import symbols  # noqa: E402

BF = pathlib.Path("/home/claude/backfill/data")
OUT = ROOT / "backtest" / "v3"
NY = "America/New_York"
PL = ["reddit", "x", "news"]


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ entities
def entity_map():
    """price symbol -> entity id (topic), and Adanos (kind, symbol) -> entity."""
    px, ad, cls = {}, {}, {}
    for t, (name, ac, yh, a) in symbols.TOPICS.items():
        if yh:
            px[yh] = t
        if a:
            ad[(a[0], a[1].upper())] = t
        cls[t] = ac
    return px, ad, cls


# ------------------------------------------------------------------ prices
def prices():
    h = pd.concat([pd.read_parquet(BF / "yahoo/topics_1h.parquet", columns=["symbol", "ts", "high", "low", "close", "volume"]),
                   pd.read_parquet(BF / "yahoo/stocks_1h.parquet", columns=["symbol", "ts", "high", "low", "close", "volume"])])
    px, _, cls = entity_map()
    h["entity"] = h.symbol.map(lambda s: px.get(s, s.replace("-", ".") if s.isupper() else s))
    h = h.dropna(subset=["close"]).drop_duplicates(["entity", "ts"])
    h["end"] = h.ts + pd.Timedelta(hours=1)
    h["et_end"] = h.end.dt.tz_convert(NY)
    h["day"] = h.et_end.dt.date
    h["hour_end"] = h.et_end.dt.hour + h.et_end.dt.minute / 60
    log("hourly bars", len(h), "entities", h.entity.nunique())
    return h


def price_panel(h, days):
    """P at 15:00 (last bar ended by 15:00 ET), day volume so far, day range so far, daily close."""
    pre = h[h.hour_end <= 15.0]
    g = pre.sort_values("end").groupby(["entity", "day"])
    snap = g.agg(p15=("close", "last"), vol15=("volume", "sum"), hi15=("high", "max"), lo15=("low", "min"), first=("close", "first"))
    close = h.sort_values("end").groupby(["entity", "day"]).close.last().rename("close_d")
    s = snap.join(close, how="outer").reset_index()
    s["day"] = pd.to_datetime(s.day)
    P = s.pivot(index="day", columns="entity", values="p15").sort_index()
    C = s.pivot(index="day", columns="entity", values="close_d").sort_index()
    V = s.pivot(index="day", columns="entity", values="vol15").sort_index()
    R = (s.hi15 / s.lo15).pipe(np.log)
    s["rng"] = R
    RG = s.pivot(index="day", columns="entity", values="rng").sort_index()
    # keep trading days of US equities (crypto trades daily; using the equity calendar keeps rows aligned)
    P = P.reindex(days)
    C = C.reindex(sorted(set(C.index) | set(days))).ffill(limit=3).reindex(days)
    V, RG = V.reindex(days), RG.reindex(days)
    ret_d = np.log(C).diff()                                   # close-to-close, day t-1 -> t (known after the close of t)
    sig20 = ret_d.shift(1).rolling(20, min_periods=15).std()   # through t-1: known at the pick
    sig60 = ret_d.shift(1).rolling(60, min_periods=40).std()
    r15 = np.log(P / P.shift(1))                               # 15:00 t-1 -> 15:00 t
    out = {
        "label_move": (np.log(P.shift(-1) / P)).abs() / sig20,
        "mom": r15.abs() / sig20,                              # B1 (w1)
        "mom_s60": r15.abs() / sig60,                          # B2
        "mom_5d": (np.log(P / P.shift(5))).abs() / (sig20 * np.sqrt(5)),   # B3
        "rng_abn": np.log(RG / RG.shift(1).rolling(20, min_periods=10).mean()),  # B4 intraday range so far vs normal
        "vol_abn": np.log1p(V) - np.log1p(V.shift(1).rolling(20, min_periods=10).mean()),  # B5 volume so far vs normal
        "gap": (np.log(P / C.shift(1))).abs() / sig20,         # B6 move since yesterday's close
        "mom_signed": r15 / sig20,                              # direction (kept for analysis)
    }
    long = []
    for k, m in out.items():
        x = m.stack(future_stack=True).rename(k)
        long.append(x)
    df = pd.concat(long, axis=1).reset_index().rename(columns={"level_0": "day", "level_1": "entity"})
    df.columns = ["day", "entity"] + list(out)
    return df.dropna(subset=["mom"])


# ------------------------------------------------------------------ Adanos
def adanos(days):
    a = pd.concat([pd.read_parquet(BF / "adanos/daily_by_symbol.parquet"),
                   pd.read_parquet(BF / "adanos/daily_by_symbol_more.parquet")] if (BF / "adanos/daily_by_symbol_more.parquet").exists()
                  else [pd.read_parquet(BF / "adanos/daily_by_symbol.parquet")])
    _, admap, _ = entity_map()
    a["symbol"] = a.symbol.str.upper()
    a["entity"] = [admap.get((k, s), s if k == "stocks" else None) for k, s in zip(a.kind, a.symbol)]
    a = a.dropna(subset=["entity"]).drop_duplicates(["platform", "entity", "date"])
    a["date"] = pd.to_datetime(a.date)
    cal = pd.date_range(a.date.min(), a.date.max(), freq="D")
    feats = {}
    M = {}
    for pl in PL + ["polymarket"]:
        sub = a[a.platform == pl]
        if sub.empty:
            continue
        m = sub.pivot(index="date", columns="entity", values="mentions").reindex(cal)
        cover = m.notna().cumsum() > 0
        m = m.where(cover, np.nan).fillna(0).where(cover)       # zero after the symbol's first row (no row = no mentions)
        M[pl] = m
        b = sub.pivot(index="date", columns="entity", values="buzz_score").reindex(cal)
        se = sub.pivot(index="date", columns="entity", values="sentiment_score").reindex(cal)
        bu = sub.pivot(index="date", columns="entity", values="bullish_pct").reindex(cal) if "bullish_pct" in sub else None
        L1 = np.log1p(m)
        for n in (7, 14, 20, 30):
            feats[f"lvl{n}_{pl}"] = L1 - np.log1p(m.shift(1).rolling(n, min_periods=max(3, n // 2)).mean())
        feats[f"raw_{pl}"] = L1
        feats[f"buzzd1_{pl}"] = b - b.shift(1)
        feats[f"buzzlvl_{pl}"] = b - b.shift(1).rolling(20, min_periods=7).mean()
        feats[f"act1_{pl}"] = np.log1p(m) - np.log1p(m.shift(1))
        feats[f"act3_{pl}"] = np.log1p(m.rolling(3).sum()) - np.log1p(m.shift(3).rolling(3).sum())
        feats[f"sentd1_{pl}"] = (se - se.shift(1)).abs()
        feats[f"sentlvl_{pl}"] = (se - se.shift(1).rolling(20, min_periods=7).mean()).abs()
        if bu is not None:
            feats[f"bulldev_{pl}"] = (bu - bu.shift(1).rolling(20, min_periods=7).mean()).abs()
    allm = sum(M[p].fillna(0) for p in PL if p in M)
    anycov = sum(M[p].notna().astype(int) for p in PL if p in M) > 0
    allm = allm.where(anycov)
    for n in (7, 14, 20, 30):
        feats[f"lvl{n}_all"] = np.log1p(allm) - np.log1p(allm.shift(1).rolling(n, min_periods=max(3, n // 2)).mean())
    feats["raw_all"] = np.log1p(allm)
    feats["act3_all"] = np.log1p(allm.rolling(3).sum()) - np.log1p(allm.shift(3).rolling(3).sum())
    feats["act1_all"] = np.log1p(allm) - np.log1p(allm.shift(1))
    # label: day t+1 (UTC) vs the 20 days before t
    label = np.log1p(allm.shift(-1)) - np.log1p(allm.shift(1).rolling(20, min_periods=10).mean())  # row t: day t+1 vs t-20..t-1
    # trending lists: best rank across platforms on day d (1 = top)
    tr = pd.read_parquet(BF / "adanos/trending_stocks.parquet", columns=["date", "platform", "rank", "ticker"])
    tr["date"] = pd.to_datetime(tr.date)
    tr = tr[tr.platform.isin(PL)].groupby(["date", "ticker"])["rank"].min().reset_index()
    T = tr.pivot(index="date", columns="ticker", values="rank").reindex(cal)
    feats["trend_rank"] = -T  # higher = better (missing = not trending)
    # shift: features on calendar day d describe UTC day d; at the pick on trading day t we know days <= t-1
    days = days[(days > cal.min()) & (days <= cal.max() + pd.Timedelta(days=1))]
    rows = []
    for k, m in feats.items():
        rows.append(m.shift(1).reindex(days).astype("float32").stack().rename(k))
    rows.append(label.reindex(days).astype("float32").stack().rename("label_attn"))
    df = pd.concat(rows, axis=1)
    df.index.names = ["day", "entity"]
    df = df.reset_index()
    log("adanos features", df.shape)
    return df


# ------------------------------------------------------------------ Kalshi
def kalshi(days):
    parts = [pd.read_parquet(p) for p in sorted((BF / "kalshi").glob("hist_candles_*.parquet"))]
    parts.append(pd.read_parquet(BF / "kalshi/candles_1h.parquet"))
    k = pd.concat(parts, ignore_index=True)
    k["ts"] = k.ts.astype("datetime64[ns, UTC]")
    k = k.drop_duplicates(["market", "ts"])
    k["mid"] = (k.yes_bid + k.yes_ask) / 2
    k["et"] = k.ts.dt.tz_convert(NY)
    log("kalshi candles", len(k), "topics", k.topic.nunique(), k.ts.min(), k.ts.max())
    # daily per topic: volume in the 24h to 15:00 ET; OI at 15:00 (sum of last bar per market); prob move of traded markets
    k = k.sort_values("et").reset_index(drop=True)
    et = k.et.values
    rows = []
    for d in days:
        T = pd.Timestamp(d).tz_localize(NY) + pd.Timedelta(hours=15)
        lo, hi = np.searchsorted(et, (T - pd.Timedelta(hours=48)).to_datetime64(), "right"), np.searchsorted(et, T.to_datetime64(), "right")
        w = k.iloc[lo:hi]
        if w.empty:
            continue
        cur = w[w.et > T - pd.Timedelta(hours=24)]
        prev = w[w.et <= T - pd.Timedelta(hours=24)]
        v1 = cur.groupby("topic").volume.sum()
        v0 = prev.groupby("topic").volume.sum()
        last = w.sort_values("et").groupby("market").tail(1)
        lastp = prev.sort_values("et").groupby("market").tail(1)
        j = last.merge(lastp[["market", "open_interest", "mid"]], on="market", suffixes=("", "_p"))
        j = j.merge(cur.groupby("market").volume.sum().rename("v24"), on="market", how="left").fillna({"v24": 0})
        oi1, oi0 = j.groupby("topic").open_interest.sum(), j.groupby("topic").open_interest_p.sum()
        ok = j[(j.v24 > 0) & j.mid.between(0.02, 0.98) & j.mid_p.between(0.02, 0.98)]
        ok = ok.assign(dm=(ok.mid - ok.mid_p).abs())
        mv = ok.groupby("topic").apply(lambda g: np.average(g.dm, weights=g.v24), include_groups=False) if len(ok) else pd.Series(dtype=float)
        f = pd.DataFrame({"k_vol": v1, "k_vol0": v0, "k_oi": oi1, "k_oi0": oi0, "k_move": mv})
        f["day"] = pd.Timestamp(d)
        rows.append(f)
    f = pd.concat(rows).reset_index().rename(columns={"index": "entity", "topic": "entity"})
    f = f.rename(columns={f.columns[0]: "entity"}) if "entity" not in f else f
    f = f.sort_values(["entity", "day"])
    g = f.groupby("entity")
    f["k_flow"] = np.log1p(f.k_vol) - np.log1p(f.k_vol0)                                  # C1 (w0/w1 money flow, log form)
    f["k_vol_abn"] = np.log1p(f.k_vol) - np.log1p(g.k_vol.transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean()))  # C2
    f["k_oi_chg"] = np.log1p(f.k_oi) - np.log1p(f.k_oi0)                                   # C3
    f["k_oi_abn"] = np.log1p(f.k_oi) - np.log1p(g.k_oi.transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean()))    # C4
    f["k_move_abn"] = f.k_move - g.k_move.transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())                 # C5
    f["k_vol_raw"] = np.log1p(f.k_vol)                                                       # C6 level
    log("kalshi features", f.shape)
    return f.drop(columns=["k_vol0", "k_oi0"])


def perps(days):
    c = pd.read_parquet(BF / "kalshi_perps/candles.parquet")
    c = c[c.interval == 1440].copy()
    m = pd.read_json(BF / "kalshi_perps/markets.json")
    und = {}
    for t, title in zip(m.ticker, m.title):
        u = str(title).split()[-1].upper()
        und[t] = {"US500": "SPX", "100": "NDX", "2000": "RUT", "GOLD": "GOLD", "SILVER": "SILVER", "OIL": "WTI",
                  "COPPER": "COPPER", "PLATINUM": "PLATINUM", "PALLADIUM": "PALLADIUM"}.get(u, u)
    c["entity"] = c.ticker.map(und)
    for col in ("volume_usd", "oi_usd"):
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c["date"] = c.ts.dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    V = c.pivot_table(index="date", columns="entity", values="volume_usd", aggfunc="sum")
    O = c.pivot_table(index="date", columns="entity", values="oi_usd", aggfunc="sum")
    fr = pd.read_parquet(BF / "kalshi_perps/funding_rates.parquet")
    fr["entity"] = fr.market_ticker.map(und)
    fr["date"] = pd.to_datetime(fr.funding_time).dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    F = fr.groupby(["date", "entity"]).funding_rate.mean().unstack()
    feats = {"pp_vol_abn": np.log1p(V) - np.log1p(V.shift(1).rolling(20, min_periods=5).mean()),
             "pp_oi_chg": np.log1p(O) - np.log1p(O.shift(1)),
             "pp_fund_abs": F.abs(), "pp_fund_chg": (F - F.shift(1)).abs()}
    rows = [m_.shift(1).reindex(days).stack().rename(k) for k, m_ in feats.items()]   # daily bar of t-1
    df = pd.concat(rows, axis=1)
    df.index.names = ["day", "entity"]
    return df.reset_index()


def polymarket(days):
    from dashboard.registry import Registry
    import json
    m = pd.read_parquet(BF / "polymarket/markets.parquet")
    us = json.load(open("/home/claude/work/v2out2/us_stocks.json"))
    reg = Registry(us, symbols.CRYPTO, {})
    tm = {e: reg.match(t)[0] for e, t in m.groupby("event_id").event_title.first().items()}
    m["entity"] = m.event_id.map(tm)
    m = m.dropna(subset=["entity"])
    p = pd.read_parquet(BF / "polymarket/prices_1d.parquet")
    p = p[p.market_id.isin(m.market_id)].merge(m[["market_id", "entity"]], on="market_id")
    p["date"] = p.ts.dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    P = p.pivot_table(index="date", columns="market_id", values="price", aggfunc="last").sort_index()
    D = (P - P.shift(1)).abs().where((P >= 0.02) & (P <= 0.98))
    long = D.stack().rename("dm").reset_index().merge(m[["market_id", "entity"]], on="market_id")
    f = long.groupby(["date", "entity"]).dm.mean().unstack()
    df = f.shift(1).reindex(days).stack().rename("p_move").reset_index()
    df.columns = ["day", "entity", "p_move"]
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    h = prices()
    days = pd.to_datetime(sorted({d for d in h[h.entity == "SPX"].day.unique()}))
    days = days[days >= pd.Timestamp("2025-01-01")]
    pp = price_panel(h, days)
    del h
    import gc; gc.collect()
    log("price panel", pp.shape)
    ad = adanos(days)
    kc = kalshi(days[days >= pd.Timestamp("2026-02-15")])
    pe = perps(days)
    pm = polymarket(days)
    df = pp.merge(ad, on=["day", "entity"], how="left").merge(kc, on=["day", "entity"], how="left") \
        .merge(pe, on=["day", "entity"], how="left").merge(pm, on=["day", "entity"], how="left")
    _, _, cls = entity_map()
    df["asset_class"] = df.entity.map(lambda e: cls.get(e, "equity"))
    df.to_parquet(OUT / "panel.parquet", index=False)
    log("panel", df.shape, df.day.min(), df.day.max())


if __name__ == "__main__":
    main()
