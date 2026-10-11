"""Study `topic_stocks` — engine. Implements backtest/studies/topic_stocks/PREREG.md.

    python -m backtest.topic_study            # snapshot tables -> runs/topic_stocks/<date>_<commit>/

Outputs per run (all CSVs gzip-compressed where large):
  summary.json         every pre-registered test, benchmark, ablation and sanity result
  panel.csv.gz         one row per (pick day, ticker, version): raw fields, transformed fields, the four
                       dimension scores, totals with and without Kalshi, labels
  picks.csv            one row per (pick day, version, score): the pick, its dimension scores, each
                       dimension's share of the total, the leading dimension, the pick's rank without
                       each dimension, and the pick's label percentiles
  dimension_report.csv per (version, period, label, dimension): standalone IC, ablation dIC, coverage,
                       share of picks led
  field_report.csv     per (version, period, label, field): standalone IC and coverage
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

from backtest.run import git_commit
from ingestion.common import et

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAP = ROOT / "backtest" / "snapshots" / "topic_stocks"
RUNS = ROOT / "backtest" / "runs" / "topic_stocks"
D = dt.date.fromisoformat

EVAL = (D("2026-08-13"), D("2026-10-07"))
PERIODS = {"discovery": (D("2026-08-13"), D("2026-09-10")), "holdout": (D("2026-09-11"), D("2026-10-07")),
           "all": EVAL}
VERSIONS = ["V0", "V1", "V2"]
DIMS = ["E", "A", "D", "M"]
SOCIAL = ["x", "reddit", "news"]
FIELDS = {"E": ["E1_momentum", "E2_today_move", "E3_kalshi_move"],
          "A": ["A1_x_mentions", "A2_reddit_mentions", "A3_news_mentions"],
          "D": ["D1_social_balance", "D2_sentiment_dev", "D3_pm_balance", "D4_kalshi_split"],
          "M": ["M1_pm_trades", "M2_kalshi_volume"]}
KALSHI_FIELDS = {"E3_kalshi_move", "D4_kalshi_split", "M2_kalshi_volume"}
LABELS = ["L_A", "L_E", "L_comp"]
PRIMARY = "L_A"
CLIP, BASE_LO, BASE_HI, BASE_MIN = 5.0, 31, 4, 15
HALF_LIFE, EWMA_K = 1.5, 10
N_PERM, N_BOOT, SEED = 5000, 5000, 23


# ============================================================== loading
def load():
    ad = pd.read_csv(SNAP / "adanos_daily.csv.gz", parse_dates=["date"])
    ad["date"] = ad.date.dt.date
    pdly = pd.read_csv(SNAP / "prices_daily.csv.gz", parse_dates=["date"])
    pdly["date"] = pdly.date.dt.date
    phr = pd.read_csv(SNAP / "prices_hourly.csv.gz")
    ks = pd.read_csv(SNAP / "kalshi_state.csv.gz", parse_dates=["date"]) if (SNAP / "kalshi_state.csv.gz").exists() else None
    if ks is not None:
        ks["date"] = ks.date.dt.date
    uni = pd.read_csv(SNAP / "universe_selection.csv")
    tickers = uni[uni.status == "selected"].ticker.tolist()
    return ad, pdly, phr, ks, tickers


def matrix(ad, platform, field, tickers, days, fill_zero=False, transform=None):
    """dates x tickers matrix of an Adanos daily field. Counts: missing day = 0 if the ticker has any data."""
    sub = ad[ad.platform == platform]
    m = sub.pivot_table(index="date", columns="ticker", values=field, aggfunc="first").reindex(index=days, columns=tickers)
    if fill_zero:
        has = sub.groupby("ticker").size().reindex(tickers).fillna(0) > 0
        m.loc[:, has.values] = m.loc[:, has.values].fillna(0)
    return transform(m) if transform else m


def balance(ad, platform, tickers, days):
    bull = matrix(ad, platform, "bullish_pct", tickers, days)
    bear = matrix(ad, platform, "bearish_pct", tickers, days)
    tot = bull + bear
    return (1 - (bull - bear).abs() / tot).where(tot > 0)


# ============================================================== version transforms
def _window(m, t, lo, hi):
    return m.loc[(m.index >= t - dt.timedelta(days=lo)) & (m.index <= t - dt.timedelta(days=hi))]


def transform(m, t, version, absolute=False):
    """Row vector (per ticker) of the version-transformed field for pick day t."""
    base = _window(m, t, BASE_LO, BASE_HI)
    mu, sd = base.mean(), base.std(ddof=1)
    ok = (base.notna().sum() >= BASE_MIN) & (sd > 0)
    d1, d2 = t - dt.timedelta(days=1), t - dt.timedelta(days=2)
    x1 = m.loc[d1] if d1 in m.index else pd.Series(np.nan, index=m.columns)
    if version == "V0":
        x2 = m.loc[d2] if d2 in m.index else pd.Series(np.nan, index=m.columns)
        sdd = base.diff().std(ddof=1)
        s = (x1 - x2) / sdd
        ok = ok & (sdd > 0)
    elif version == "V1":
        rows = [m.loc[t - dt.timedelta(days=k)] if t - dt.timedelta(days=k) in m.index else None
                for k in range(1, EWMA_K + 1)]
        w = np.array([0.5 ** ((k - 1) / HALF_LIFE) for k in range(1, EWMA_K + 1)])
        num = sum(wk * r.fillna(0) for wk, r in zip(w, rows) if r is not None)
        den = sum(wk * r.notna() for wk, r in zip(w, rows) if r is not None)
        e = num / den.replace(0, np.nan)
        s = (e - mu) / sd
    else:
        z1 = (x1 - mu) / sd
        last3 = _window(m, t, 3, 1)
        z3 = (last3.mean() - mu) / (sd / np.sqrt(3))
        z3 = z3.where(last3.notna().sum() == 3)
        s = pd.concat([z1, z3], axis=1).max(axis=1, skipna=True)
    if absolute:
        s = s.abs()
    return s.where(ok).clip(-CLIP, CLIP)


# ============================================================== features
def price_features(pdly, phr, tickers, days):
    """E1, E2 per (t, ticker) plus prices needed for labels. Uses sessions < t and the 14:30 ET price."""
    out, lab = {}, {}
    hr = phr.copy()
    hr["et_date"] = pd.to_datetime(hr.bar_start_et).dt.date
    hr["et_time"] = pd.to_datetime(hr.bar_start_et).dt.strftime("%H:%M")
    p1430 = hr[hr.et_time == "13:30"].set_index(["ticker", "et_date"])["close"]  # bar 13:30-14:30 ET -> close at 14:30
    for tk, g in pdly.groupby("ticker"):
        g = g.sort_values("date").set_index("date")
        rng = np.log(g.high / g.low)
        ret = np.log(g.close).diff()
        sess = list(g.index)
        for t in days:
            prev = [d for d in sess if d < t]
            if len(prev) < 22:
                continue
            d1 = prev[-1]
            base = rng.loc[prev[-21:-1]]
            e1 = (rng.loc[d1] - base.mean()) / base.std(ddof=1) if base.std(ddof=1) > 0 else np.nan
            sig = ret.loc[prev[-20:]].std(ddof=1)
            p = p1430.get((tk, t), np.nan)
            e2 = abs(np.log(p / g.close.loc[d1])) / sig if sig > 0 and p == p else np.nan
            out[(t, tk)] = dict(E1_momentum=float(np.clip(e1, -CLIP, CLIP)) if e1 == e1 else np.nan,
                                E2_today_move=float(np.clip(e2, -CLIP, CLIP)) if e2 == e2 else np.nan,
                                price_asof=f"{t} 14:30 ET" if p == p else str(d1))
            nxt = [d for d in sess if d > t]
            if nxt:
                n1 = nxt[0]
                b2 = rng.loc[[d for d in sess if d < n1][-20:]]
                lab[(t, tk)] = dict(L_E=rng.loc[n1] / b2.mean() if b2.mean() > 0 else np.nan, label_session=n1)
    return out, lab


def kalshi_features(ks, days):
    """Raw Kalshi fields per (t, ticker) at 15:00 ET; standardised later (pooled, past-only)."""
    out = {}
    if ks is None:
        return out
    for (t, tk), g in ks.groupby(["date", "ticker"]):
        rec = {"kalshi_open_markets": int(g.market.nunique()), "kalshi_last_candle_ts": g.last_candle_ts.max()}
        rec["M2_raw"] = float(np.log1p(g.vol_24h.fillna(0).sum()))
        ev = g[g.kind == "event"]
        if len(ev):
            mv = (ev.mid_now - ev.mid_24h_ago).abs().dropna()
            rec["E3_raw"] = float(mv.max()) if len(mv) else np.nan
            q = ev.dropna(subset=["mid_now"])
            if len(q):
                q = q.assign(dist=(q.mid_now - 0.5).abs()).sort_values(["vol_24h", "dist"], ascending=[False, True])
                rec["D4_raw"] = float(1 - 2 * abs(q.mid_now.iloc[0] - 0.5))
        lad = g[g.kind == "ladder"].dropna(subset=["mid_now", "strike"]).sort_values("strike")
        if len(lad) >= 5:
            k, p = lad.strike.to_numpy(), np.minimum.accumulate(lad.mid_now.to_numpy())  # P(above K) non-increasing
            if p.max() >= 0.75 and p.min() <= 0.25:
                kk = lambda q: float(np.interp(-q, -p, k))  # noqa: E731
                k50 = kk(0.5)
                rec["D4_raw"] = (kk(0.25) - kk(0.75)) / k50 if k50 > 0 else np.nan
        out[(t, tk)] = rec
    return out


def build_panel(ad, pdly, phr, ks, tickers):
    # Adanos history is 2026-07-14 .. 2026-10-10; matrices cover exactly that span, so a missing count
    # inside it is a true zero and nothing before it is invented
    days_all = [D("2026-07-14") + dt.timedelta(days=i) for i in range((D("2026-10-10") - D("2026-07-14")).days + 1)]
    spy = sorted(pdly[pdly.ticker == "SPY"].date)
    picks = [d for d in spy if EVAL[0] <= d <= EVAL[1]]
    log1p = lambda m: np.log1p(m)  # noqa: E731
    mats = {f"{p}_mentions": matrix(ad, p, "mentions", tickers, days_all, True, log1p) for p in SOCIAL}
    mats["pm_trades"] = matrix(ad, "polymarket", "trade_count", tickers, days_all, True, log1p)
    mats["reddit_bal"], mats["x_bal"] = balance(ad, "reddit", tickers, days_all), balance(ad, "x", tickers, days_all)
    mats["pm_bal"] = balance(ad, "polymarket", tickers, days_all)
    mats["reddit_sent"] = matrix(ad, "reddit", "sentiment_score", tickers, days_all)
    mats["x_sent"] = matrix(ad, "x", "sentiment_score", tickers, days_all)
    pf, pl = price_features(pdly, phr, tickers, picks)
    kf = kalshi_features(ks, days_all)

    # pooled, past-only standardisation for Kalshi fields
    kdf = pd.DataFrame([dict(date=t, ticker=tk, **v) for (t, tk), v in kf.items()]) if kf else pd.DataFrame()
    rows = []
    for v in VERSIONS:
        for t in picks:
            tr = {k: transform(m, t, v) for k, m in mats.items() if not k.endswith("sent")}
            tr["reddit_sent"] = transform(mats["reddit_sent"], t, v, absolute=True)
            tr["x_sent"] = transform(mats["x_sent"], t, v, absolute=True)
            # labels: attention persistence on t+1..t+3, same baseline as the features
            base = {p: _window(mats[f"{p}_mentions"], t, BASE_LO, BASE_HI) for p in SOCIAL}
            fut = {}
            for p in SOCIAL:
                mu, sd = base[p].mean(), base[p].std(ddof=1)
                ok = (base[p].notna().sum() >= BASE_MIN) & (sd > 0)
                z = [(mats[f"{p}_mentions"].loc[t + dt.timedelta(days=k)] - mu) / sd for k in (1, 2, 3)]
                fut[p] = (sum(z) / 3).where(ok)
            la = pd.concat(fut, axis=1).mean(axis=1, skipna=True)
            past = kdf[kdf.date < t] if len(kdf) else kdf
            for tk in tickers:
                r = dict(version=v, date=t, ticker=tk)
                r.update(pf.get((t, tk), {}))
                r["A1_x_mentions"], r["A2_reddit_mentions"], r["A3_news_mentions"] = (
                    tr["x_mentions"][tk], tr["reddit_mentions"][tk], tr["news_mentions"][tk])
                r["D1_social_balance"] = np.nanmean([tr["reddit_bal"][tk], tr["x_bal"][tk]]) \
                    if np.isfinite([tr["reddit_bal"][tk], tr["x_bal"][tk]]).any() else np.nan
                r["D2_sentiment_dev"] = np.nanmean([tr["reddit_sent"][tk], tr["x_sent"][tk]]) \
                    if np.isfinite([tr["reddit_sent"][tk], tr["x_sent"][tk]]).any() else np.nan
                r["D3_pm_balance"], r["M1_pm_trades"] = tr["pm_bal"][tk], tr["pm_trades"][tk]
                lvl = sum(np.expm1(mats[f"{p}_mentions"].loc[t - dt.timedelta(days=1), tk])
                          for p in SOCIAL if pd.notna(mats[f"{p}_mentions"].loc[t - dt.timedelta(days=1), tk]))
                r["B_most_discussed"] = float(np.log1p(lvl))
                r["adanos_asof"] = str(t - dt.timedelta(days=1))
                kv = kf.get((t, tk))
                r["kalshi_subset"] = int(tk in set(kdf.ticker)) if len(kdf) else 0
                for f, raw in (("E3_kalshi_move", "E3_raw"), ("D4_kalshi_split", "D4_raw"), ("M2_kalshi_volume", "M2_raw")):
                    x = kv.get(raw, np.nan) if kv else np.nan
                    r[raw] = x
                    col = past[raw].dropna() if len(past) and raw in past else pd.Series(dtype=float)
                    r[f] = float(np.clip((x - col.mean()) / col.std(ddof=1), -CLIP, CLIP)) \
                        if x == x and len(col) >= 20 and col.std(ddof=1) > 0 else np.nan
                r["kalshi_open_markets"] = kv.get("kalshi_open_markets", 0) if kv else 0
                r["kalshi_asof_ts"] = kv.get("kalshi_last_candle_ts") if kv else None
                r["L_A"] = la.get(tk, np.nan)
                r.update(pl.get((t, tk), {}))
                rows.append(r)
    panel = pd.DataFrame(rows)
    # look-ahead guards
    assert (pd.to_datetime(panel.adanos_asof) < pd.to_datetime(panel.date)).all(), "Adanos look-ahead"
    kts = panel.kalshi_asof_ts.dropna()
    if len(kts):
        pick_ts = panel.loc[kts.index].date.map(lambda d: et(d, 15).timestamp())
        assert (kts.astype(float) <= pick_ts).all(), "Kalshi look-ahead"
    return panel


def add_scores(panel):
    p = panel.copy()
    for dim, fs in FIELDS.items():
        base = [f for f in fs if f not in KALSHI_FIELDS]
        p[f"{dim}_dim"] = p[base].mean(axis=1, skipna=True)
        p[f"{dim}_dim_k"] = p[fs].mean(axis=1, skipna=True)
    p["score"] = p[[f"{d}_dim" for d in DIMS]].mean(axis=1, skipna=True)
    p["score_k"] = p[[f"{d}_dim_k" for d in DIMS]].mean(axis=1, skipna=True)
    for d in DIMS:
        p[f"score_without_{d}"] = p[[f"{x}_dim" for x in DIMS if x != d]].mean(axis=1, skipna=True)
    p["L_comp"] = (p.groupby(["version", "date"]).L_A.rank(pct=True) + p.groupby(["version", "date"]).L_E.rank(pct=True)) / 2
    return p


# ============================================================== metrics
def _rank(x):
    return pd.Series(x).rank().to_numpy(float)


def daily_ic(df, col, label):
    out = {}
    for t, g in df.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) >= 10 and g[col].nunique() > 1 and g[label].nunique() > 1:
            out[t] = float(np.corrcoef(_rank(g[col]), _rank(g[label]))[0, 1])
    return pd.Series(out, dtype=float)


def perm_p(df, col, label, rng):
    obs, null, k = [], np.zeros(N_PERM), 0
    for _, g in df.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) < 10 or g[col].nunique() < 2 or g[label].nunique() < 2:
            continue
        x, y = _rank(g[col]), _rank(g[label])
        yz = (y - y.mean()) / y.std()
        obs.append(np.corrcoef(x, y)[0, 1])
        xs = x[np.argsort(rng.random((N_PERM, len(x))), axis=1)]
        xs = (xs - xs.mean(1, keepdims=True)) / xs.std(1, keepdims=True)
        null += (xs * yz).mean(1)
        k += 1
    if not k:
        return np.nan, np.nan
    null /= k
    return float((null >= np.mean(obs) - 1e-12).mean()), float(null.std())


def boot(x, rng):
    x = np.asarray(pd.Series(x).dropna(), float)
    if len(x) < 3:
        return [np.nan, np.nan]
    m = x[rng.integers(0, len(x), (N_BOOT, len(x)))].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def pick_stats(df, col, label):
    pct, hit = [], []
    for _, g in df.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) < 10:
            continue
        y = g[label]
        top = g.sort_values(col, ascending=False)
        pv = y.loc[top.index[0]]
        pct.append((np.sum(y < pv) + 0.5 * (np.sum(y == pv) - 1)) / (len(y) - 1))
        top10 = set(y.sort_values(ascending=False).index[:10])
        hit.append(float(any(i in top10 for i in top.index[:3])))
    return (float(np.mean(pct)) if pct else np.nan, float(np.mean(hit)) if hit else np.nan, len(pct))


def evaluate(df, col, label, rng):
    ic = daily_ic(df, col, label)
    p, nsd = perm_p(df, col, label, rng)
    pp, hit, n = pick_stats(df, col, label)
    return dict(IC=float(ic.mean()) if len(ic) else np.nan, IC_ci95=boot(ic, rng), p=p, null_sd=nsd,
                mde=2.49 * nsd if nsd == nsd else np.nan, days=int(len(ic)), pick_pctl=pp, top3_hit=hit)


def paired(df, a, b, label, rng):
    d = (daily_ic(df, a, label) - daily_ic(df, b, label)).dropna()
    ci = boot(d, rng)
    m = np.asarray(d, float)
    bm = m[rng.integers(0, len(m), (N_BOOT, len(m)))].mean(1) if len(m) >= 3 else np.array([np.nan])
    return dict(mean=float(d.mean()) if len(d) else np.nan, ci95=ci, days=int(len(d)),
                p_two_sided=float(min(1.0, 2 * min((bm <= 0).mean(), (bm >= 0).mean()))) if len(m) >= 3 else np.nan)


def holm(p):
    items = sorted((v, k) for k, v in p.items() if v == v)
    out, run, m = {}, 0.0, len(items)
    for i, (v, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = run
    return out


def period(df, name):
    lo, hi = PERIODS[name]
    return df[(df.date >= lo) & (df.date <= hi)]


# ============================================================== records
def pick_records(p):
    rows = []
    for (v, t), g in p.groupby(["version", "date"]):
        g = g.dropna(subset=["score"])
        if not len(g):
            continue
        for col in ("score", "score_k"):
            gg = g if col == "score" else g[g.kalshi_subset == 1].dropna(subset=["score_k"])
            if not len(gg):
                continue
            top = gg.sort_values(col, ascending=False).iloc[0]
            dims = {d: top[f"{d}_dim" if col == "score" else f"{d}_dim_k"] for d in DIMS}
            tot_abs = sum(abs(x) for x in dims.values() if x == x)
            rec = dict(version=v, date=t, score_col=col, pool=len(gg), pick=top.ticker, total=top[col])
            for d in DIMS:
                rec[f"{d}_dim"] = dims[d]
                rec[f"{d}_share"] = abs(dims[d]) / tot_abs if dims[d] == dims[d] and tot_abs > 0 else np.nan
                if col == "score":
                    rec[f"rank_without_{d}"] = int(gg[f"score_without_{d}"].rank(ascending=False, method="min")
                                                   .loc[top.name])
            led = {d: x for d, x in dims.items() if x == x}
            rec["leading_dim"] = max(led, key=lambda d: led[d]) if led else None
            for lab in LABELS:
                y = gg[lab].dropna()
                pv = top[lab]
                rec[f"{lab}_pctl"] = ((np.sum(y < pv) + 0.5 * (np.sum(y == pv) - 1)) / (len(y) - 1)
                                      if pv == pv and len(y) > 1 else np.nan)
            rows.append(rec)
    return pd.DataFrame(rows)


def dimension_report(p, picks, rng):
    rows = []
    for v in VERSIONS:
        for per in PERIODS:
            dfv = period(p[p.version == v], per)
            pk = period(picks[(picks.version == v) & (picks.score_col == "score")], per)
            for lab in LABELS:
                for d in DIMS:
                    r = evaluate(dfv, f"{d}_dim", lab, rng)
                    ab = paired(dfv, "score", f"score_without_{d}", lab, rng)
                    rows.append(dict(version=v, period=per, label=lab, dimension=d, standalone_IC=r["IC"],
                                     standalone_p=r["p"], standalone_ci_lo=r["IC_ci95"][0], standalone_ci_hi=r["IC_ci95"][1],
                                     ablation_dIC=ab["mean"], ablation_ci_lo=ab["ci95"][0], ablation_ci_hi=ab["ci95"][1],
                                     ablation_p=ab["p_two_sided"], coverage=float(dfv[f"{d}_dim"].notna().mean()),
                                     share_of_picks_led=float((pk.leading_dim == d).mean()) if len(pk) else np.nan,
                                     mean_share_in_pick=float(pk[f"{d}_share"].mean()) if len(pk) else np.nan))
    dr = pd.DataFrame(rows)
    for (v, per, lab), g in dr.groupby(["version", "period", "label"]):
        hs = holm(dict(zip(g.dimension, g.standalone_p)))
        ha = holm(dict(zip(g.dimension, g.ablation_p)))
        dr.loc[g.index, "standalone_p_holm"] = g.dimension.map(hs)
        dr.loc[g.index, "ablation_p_holm"] = g.dimension.map(ha)
    return dr


def field_report(p, rng):
    rows = []
    fields = [f for fs in FIELDS.values() for f in fs]
    for v in VERSIONS:
        for per in PERIODS:
            dfv = period(p[p.version == v], per)
            for lab in LABELS:
                for f in fields:
                    sub = dfv if f not in KALSHI_FIELDS else dfv[dfv.kalshi_subset == 1]
                    ic = daily_ic(sub, f, lab) if sub[f].notna().sum() else pd.Series(dtype=float)
                    rows.append(dict(version=v, period=per, label=lab, field=f,
                                     dimension=[d for d, fs in FIELDS.items() if f in fs][0],
                                     IC=float(ic.mean()) if len(ic) else np.nan, IC_ci95=boot(ic, rng),
                                     days=int(len(ic)), coverage=float(sub[f].notna().mean()) if len(sub) else np.nan))
    return pd.DataFrame(rows)


# ============================================================== run
def run():
    rng = np.random.default_rng(SEED)
    ad, pdly, phr, ks, tickers = load()
    panel = add_scores(build_panel(ad, pdly, phr, ks, tickers))
    S = dict(study="topic_stocks", commit=git_commit(), run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
             n_tickers=len(tickers), n_pick_days=int(panel.date.nunique()),
             n_rows_per_version=int(len(panel) // len(VERSIONS)),
             n_rows_labelled=int(panel[panel.version == "V1"].L_A.notna().sum()),
             kalshi_subset=sorted(panel[panel.kalshi_subset == 1].ticker.unique().tolist()))
    # family (a): versions on discovery, primary label
    disc = {v: evaluate(period(panel[panel.version == v], "discovery"), "score", PRIMARY, rng) for v in VERSIONS}
    hv = holm({v: r["p"] for v, r in disc.items()})
    for v in VERSIONS:
        disc[v]["p_holm"] = hv[v]
    carried = max(["V1", "V2"], key=lambda v: disc[v]["IC"] if disc[v]["IC"] == disc[v]["IC"] else -9)
    S["discovery_versions"], S["carried_version"] = disc, carried
    # every score x label x period
    cols = {"score": "four dimensions", "A_dim": "attention only", "E1_momentum": "momentum",
            "B_most_discussed": "most discussed"}
    S["scores"] = {}
    for v in VERSIONS:
        for per in PERIODS:
            dfv = period(panel[panel.version == v], per)
            for lab in LABELS:
                for c in cols:
                    S["scores"][f"{v}|{per}|{lab}|{c}"] = evaluate(dfv, c, lab, rng)
    # random benchmark and oracle (sanity)
    ho = period(panel[panel.version == carried], "holdout")
    rs = []
    for k in range(200):
        tmp = ho.assign(_r=np.random.default_rng(1000 + k).random(len(ho)))
        rs.append(daily_ic(tmp, "_r", PRIMARY).mean())
    S["sanity"] = dict(random_IC_mean=float(np.mean(rs)), random_IC_sd=float(np.std(rs)),
                       oracle_IC=float(daily_ic(ho.assign(_o=ho[PRIMARY]), "_o", PRIMARY).mean()),
                       random_top3_hit_expected=float(1 - np.prod([(len(tickers) - 10 - i) / (len(tickers) - i)
                                                                   for i in range(3)])))
    # hypotheses on the holdout, primary label, carried version
    h1 = evaluate(ho, "score", PRIMARY, rng)
    S["H1_carried_IC_holdout"] = h1
    S["H2_vs_attention_only"] = paired(ho, "score", "A_dim", PRIMARY, rng)
    S["H3_vs_most_discussed"] = paired(ho, "score", "B_most_discussed", PRIMARY, rng)
    S["H3_vs_momentum"] = paired(ho, "score", "E1_momentum", PRIMARY, rng)
    sub = ho[ho.kalshi_subset == 1].dropna(subset=["score_k"])
    S["H4_kalshi_with_minus_without"] = paired(sub, "score_k", "score", PRIMARY, rng)
    S["H4_subset_IC_with"] = evaluate(sub, "score_k", PRIMARY, rng)
    S["H4_subset_IC_without"] = evaluate(sub, "score", PRIMARY, rng)
    S["decision"] = dict(
        H1=bool(h1["p"] < 0.05), H2=bool(S["H2_vs_attention_only"]["ci95"][0] > 0),
        H3_most_discussed=bool(S["H3_vs_most_discussed"]["ci95"][0] > 0),
        H3_momentum=bool(S["H3_vs_momentum"]["ci95"][0] > 0),
        H4=bool(S["H4_kalshi_with_minus_without"]["ci95"][0] > 0))
    # dimension and field records
    picks = pick_records(panel)
    dr = dimension_report(panel, picks, rng)
    fr = field_report(panel, rng)
    corr = panel[panel.version == carried][[f"{d}_dim" for d in DIMS]].corr(method="spearman")
    S["dimension_corr_carried"] = corr.round(3).to_dict()
    S["dimensions_carried_holdout_primary"] = dr[(dr.version == carried) & (dr.period == "holdout") &
                                                 (dr.label == PRIMARY)].drop(columns=["version", "period", "label"]).to_dict("records")
    run_dir = RUNS / f"{dt.date.today():%Y-%m-%d}_{S['commit']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(S, indent=2, default=str))
    panel.to_csv(run_dir / "panel.csv.gz", index=False)
    picks.to_csv(run_dir / "picks.csv", index=False)
    dr.to_csv(run_dir / "dimension_report.csv", index=False)
    fr.to_csv(run_dir / "field_report.csv", index=False)
    print(json.dumps({k: S[k] for k in ("carried_version", "decision", "sanity")}, indent=1, default=str))
    return run_dir, S


if __name__ == "__main__":
    run()
