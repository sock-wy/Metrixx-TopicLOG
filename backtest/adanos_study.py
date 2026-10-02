"""Study `adanos_crypto`: is the weakness a data problem or an algorithm problem?

Implements backtest/studies/adanos_crypto/PREREG.md exactly. Two steps:

    python -m backtest.adanos_study build   # raw API cache -> committed snapshot tables (universe fixed here)
    python -m backtest.adanos_study run     # snapshot tables -> runs/adanos_crypto/<date>_<commit>/

`run` needs no API access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd
import yaml

from backtest.run import git_commit
from scoring.scoring import pctrank

ROOT = pathlib.Path(__file__).resolve().parents[1]
STUDY = ROOT / "backtest" / "studies" / "adanos_crypto"
SNAP = ROOT / "backtest" / "snapshots" / "adanos_crypto"
RUNS = ROOT / "backtest" / "runs" / "adanos_crypto"

D = dt.date.fromisoformat
CFG = dict(
    history=("2026-07-04", "2026-10-01"),
    formation=("2026-07-04", "2026-08-02"),
    evaluation=("2026-08-03", "2026-10-01"),
    discovery=("2026-08-03", "2026-09-07"),
    holdout=("2026-09-08", "2026-10-01"),
    exclude=["USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "RLUSD", "WETH", "WBTC", "STETH", "PAXG", "XAUT"],
    min_coverage=0.80, min_median_mentions=3, top_n=30,
    weights={"attention": 0.25, "activity": 0.10, "sentiment": 0.15},
    z_window=30, z_min_obs=20, label_window=20, z_clip=5.0,
    n_perm=5000, n_boot=5000, seed=11,
)
SIGNALS = ["A0", "A1", "A2", "A3", "M"]
INPUTS = ["buzz_d1", "mentions_d1", "sentiment_d1", "buzz_z", "mentions_z", "sentiment_z"]


# --------------------------------------------------------------------------- build
def build():
    from ingestion import adanos, binance
    h0, h1 = CFG["history"]
    f0, f1 = CFG["formation"]
    trend = adanos.trending("reddit", "crypto", f0, f1, limit=100) or []
    usdt = binance.usdt_symbols()
    hist_days = pd.date_range(h0, h1).date
    form_days = pd.date_range(f0, f1).date
    rows, sel = [], []
    for rank, x in enumerate(trend, 1):
        s = x["symbol"]
        body = adanos.detail("reddit", "crypto", s, h0, h1) or {}
        dtr = pd.DataFrame(body.get("daily_trend") or [])
        if len(dtr):
            dtr["date"] = pd.to_datetime(dtr["date"]).dt.date
        form = dtr[dtr.date.isin(form_days)] if len(dtr) else dtr
        kl = binance.daily_klines(s, D("2026-06-01"), D(h1)) if s in usdt else []
        kdays = {k["date"] for k in kl}
        rec = dict(symbol=s, trending_rank=rank,
                   formation_mentions=int(form.mentions.sum()) if len(form) else 0,
                   formation_coverage=round(len(form) / len(form_days), 3),
                   formation_median_mentions=float(np.median([dict(zip(form.date, form.mentions)).get(d, 0) if len(form) else 0
                                                              for d in form_days])),
                   excluded=s in CFG["exclude"], binance_usdt=s in usdt,
                   binance_full_history=all(d in kdays for d in hist_days))
        rec["eligible"] = (not rec["excluded"] and rec["binance_usdt"] and rec["binance_full_history"]
                           and rec["formation_coverage"] >= CFG["min_coverage"]
                           and rec["formation_median_mentions"] >= CFG["min_median_mentions"])
        sel.append(rec)
        if rec["eligible"]:
            for _, r in dtr.iterrows():
                rows.append(dict(symbol=s, **r.to_dict()))
    sel = pd.DataFrame(sel)
    keep = sel[sel.eligible].sort_values("formation_mentions", ascending=False).head(CFG["top_n"]).symbol.tolist()
    sel["selected"] = sel.symbol.isin(keep)
    ad = pd.DataFrame(rows)
    ad = ad[ad.symbol.isin(keep)]
    px = []
    for s in keep:
        for k in binance.daily_klines(s, D("2026-06-01"), D(h1)):
            px.append(dict(symbol=s, date=k["date"], open=k["open"], high=k["high"], low=k["low"],
                           close=k["close"], volume=k["volume"], quote_volume=k["quote_volume"], trades=k["trades"]))
    SNAP.mkdir(parents=True, exist_ok=True)
    sel.to_csv(SNAP / "universe_selection.csv", index=False)
    ad.to_csv(SNAP / "adanos_daily.csv.gz", index=False)
    pd.DataFrame(px).to_csv(SNAP / "binance_daily.csv.gz", index=False)
    (SNAP / "meta.json").write_text(json.dumps(dict(config=CFG, selected=keep,
                                                    built_at=dt.datetime.now(dt.timezone.utc).isoformat()), indent=2))
    print(f"selected {len(keep)} of {int(sel.eligible.sum())} eligible / {len(sel)} candidates: {keep}")


# --------------------------------------------------------------------------- panel
def _series(df, col):
    return {s: g.set_index("date")[col].sort_index() for s, g in df.groupby("symbol")}


def build_panel(ad, px, days):
    buzz, men, sen = _series(ad, "buzz_score"), _series(ad, "mentions"), _series(ad, "sentiment_score")
    px = px.sort_values(["symbol", "date"]).copy()
    px["range"] = np.log(px.high / px.low)
    px["ret"] = px.groupby("symbol").close.transform(lambda c: np.log(c).diff())
    rng, ret = _series(px, "range"), _series(px, "ret")
    W, Z, ZMIN = CFG["label_window"], CFG["z_window"], CFG["z_min_obs"]
    rows = []
    for s in sorted(ad.symbol.unique()):
        b, m, se, r, rt = buzz.get(s), men.get(s), sen.get(s), rng[s], ret[s]

        def at(x, d):
            return float(x[d]) if x is not None and d in x.index and pd.notna(x[d]) else np.nan

        def window(x, a, b_):  # values on days a..b_ inclusive
            if x is None:
                return pd.Series(dtype=float)
            return x[(x.index >= a) & (x.index <= b_)].dropna()

        for t in days:
            d1, d2 = t - dt.timedelta(1), t - dt.timedelta(2)
            row = dict(date=t, symbol=s, feature_max_date=d1)
            # A0 inputs: 1-day changes
            row["buzz_d1"] = at(b, d1) - at(b, d2)
            m1, m2 = at(m, d1), at(m, d2)
            row["mentions_d1"] = (m1 / m2 - 1) * 100 if m2 and m2 > 0 and not np.isnan(m1) else np.nan
            row["sentiment_d1"] = abs(at(se, d1) - at(se, d2))
            # A1/A2 inputs: z-score of t-1 vs days t-31..t-2
            lo, hi = t - dt.timedelta(Z + 1), d2
            for name, x, tf in [("buzz_z", b, None), ("mentions_z", m, np.log1p), ("sentiment_z", se, None)]:
                base = window(x, lo, hi)
                v = at(x, d1)
                if tf is not None:
                    base, v = tf(base), tf(v) if not np.isnan(v) else np.nan
                z = (v - base.mean()) / base.std(ddof=1) if len(base) >= ZMIN and base.std(ddof=1) > 0 else np.nan
                row[name] = abs(z) if name == "sentiment_z" and not np.isnan(z) else z
            # A3 inputs: 3-day smoothing
            w1 = (t - dt.timedelta(3), d1)
            w0 = (t - dt.timedelta(6), t - dt.timedelta(4))
            bb1, bb0 = window(b, *w1), window(b, *w0)
            mm1, mm0 = window(m, *w1), window(m, *w0)
            ss1, ss0 = window(se, *w1), window(se, *w0)
            row["buzz_s3"] = bb1.mean() - bb0.mean() if len(bb1) == 3 and len(bb0) == 3 else np.nan
            row["mentions_s3"] = (mm1.sum() / mm0.sum() - 1) * 100 if len(mm1) == 3 and len(mm0) == 3 and mm0.sum() > 0 else np.nan
            row["sentiment_s3"] = abs(ss1.mean() - ss0.mean()) if len(ss1) == 3 and len(ss0) == 3 else np.nan
            # momentum (day t-1 abnormal range) and labels (day t)
            base_m = window(r, t - dt.timedelta(W + 1), d2)
            row["M"] = at(r, d1) / base_m.mean() if len(base_m) == W else np.nan
            base_l = window(r, t - dt.timedelta(W), d1)
            row["label_range"] = at(r, t) / base_l.mean() if len(base_l) == W else np.nan
            base_r = window(rt, t - dt.timedelta(W), d1)
            row["label_close"] = abs(at(rt, t)) / base_r.std(ddof=1) if len(base_r) == W else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def add_scores(panel):
    w = CFG["weights"]
    groups = {
        "A0": ("buzz_d1", "mentions_d1", "sentiment_d1"),
        "A1": ("buzz_z", "mentions_z", "sentiment_z"),
        "A3": ("buzz_s3", "mentions_s3", "sentiment_s3"),
    }
    out = []
    for t, g in panel.groupby("date"):
        g = g.copy()
        for name, cols in groups.items():
            pr = {c: pctrank([None if pd.isna(v) else v for v in g[c]]) for c in cols}
            num, den = np.zeros(len(g)), np.zeros(len(g))
            for c, wk in zip(cols, (w["attention"], w["activity"], w["sentiment"])):
                p = np.array([np.nan if v is None else v for v in pr[c]], float)
                ok = ~np.isnan(p)
                num[ok] += wk * p[ok]
                den[ok] += wk
            g[name] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
        zc = CFG["z_clip"]
        num, den = np.zeros(len(g)), np.zeros(len(g))
        for c, wk in zip(groups["A1"], (w["attention"], w["activity"], w["sentiment"])):
            v = g[c].clip(-zc, zc).to_numpy(float)
            ok = ~np.isnan(v)
            num[ok] += wk * v[ok]
            den[ok] += wk
        g["A2"] = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
        out.append(g)
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- evaluation
def _rank(x):
    return pd.Series(x).rank().to_numpy(float)


def daily_ic(panel, col, label):
    rec = {}
    for t, g in panel.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) >= 5 and g[col].nunique() > 1 and g[label].nunique() > 1:
            rec[t] = float(np.corrcoef(_rank(g[col]), _rank(g[label]))[0, 1])
    return pd.Series(rec, dtype=float)


def perm_test(panel, col, label, rng, n):
    obs, null, k = [], np.zeros(n), 0
    for _, g in panel.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) < 5 or g[col].nunique() < 2 or g[label].nunique() < 2:
            continue
        x, y = _rank(g[col]), _rank(g[label])
        yz = (y - y.mean()) / y.std()
        obs.append(np.corrcoef(x, y)[0, 1])
        perm = np.argsort(rng.random((n, len(x))), axis=1)
        xs = x[perm]
        xs = (xs - xs.mean(1, keepdims=True)) / xs.std(1, keepdims=True)
        null += (xs * yz).mean(1)
        k += 1
    if not k:
        return np.nan, np.nan, np.nan
    null /= k
    return float(np.mean(obs)), float((null >= np.mean(obs) - 1e-12).mean()), float(null.std())


def boot(x, rng, n):
    x = np.asarray(pd.Series(x).dropna(), float)
    if len(x) < 3:
        return [np.nan, np.nan]
    m = x[rng.integers(0, len(x), (n, len(x)))].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def pick_pctl(panel, col, label):
    vals = []
    for _, g in panel.groupby("date"):
        g = g[[col, label]].dropna()
        if len(g) < 5:
            continue
        top = g.loc[g[col].idxmax(), label]
        y = g[label].to_numpy()
        vals.append((np.sum(y < top) + 0.5 * (np.sum(y == top) - 1)) / (len(y) - 1))
    return float(np.mean(vals)) if vals else np.nan


def holm(p):
    items = sorted((v, k) for k, v in p.items() if v == v)
    out, run, m = {}, 0.0, len(items)
    for i, (v, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = run
    return out


def evaluate(panel, period, cols, label, rng):
    lo, hi = (D(x) for x in CFG[period])
    p = panel[(panel.date >= lo) & (panel.date <= hi)]
    res = {}
    for c in cols:
        ic, pv, nsd = perm_test(p, c, label, rng, CFG["n_perm"])
        d = daily_ic(p, c, label)
        res[c] = dict(IC=ic, p=pv, null_sd=nsd, mde=2.49 * nsd if nsd == nsd else np.nan,
                      ci95=boot(d, rng, CFG["n_boot"]), days=int(len(d)), pick_pctl=pick_pctl(p, c, label))
    adj = holm({c: r["p"] for c, r in res.items()})
    for c in res:
        res[c]["p_holm"] = adj.get(c, np.nan)
    return res


def paired(panel, a, b, label, period, rng):
    lo, hi = (D(x) for x in CFG[period])
    p = panel[(panel.date >= lo) & (panel.date <= hi)]
    da, db = daily_ic(p, a, label), daily_ic(p, b, label)
    diff = (da - db).dropna()
    return dict(mean=float(diff.mean()), ci95=boot(diff, rng, CFG["n_boot"]), days=int(len(diff)))


def run():
    ad = pd.read_csv(SNAP / "adanos_daily.csv.gz", parse_dates=["date"])
    ad["date"] = ad.date.dt.date
    px = pd.read_csv(SNAP / "binance_daily.csv.gz", parse_dates=["date"])
    px["date"] = px.date.dt.date
    e0, e1 = (D(x) for x in CFG["evaluation"])
    days = list(pd.date_range(e0, e1).date)
    panel = add_scores(build_panel(ad, px, days))
    assert (pd.to_datetime(panel.feature_max_date) < pd.to_datetime(panel.date)).all(), "look-ahead"
    rng = np.random.default_rng(CFG["seed"])

    out = dict(study="adanos_crypto", commit=git_commit(), run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
               config=CFG, universe=sorted(panel.symbol.unique()), n_tokens=int(panel.symbol.nunique()),
               n_rows=int(len(panel)), n_rows_labelled=int(panel.label_range.notna().sum()))
    out["inputs"] = {per: evaluate(panel, per, INPUTS, "label_range", rng) for per in ("discovery", "holdout", "evaluation")}
    out["signals"] = {per: evaluate(panel, per, SIGNALS, "label_range", rng) for per in ("discovery", "holdout", "evaluation")}
    out["signals_close_label"] = {per: evaluate(panel, per, SIGNALS, "label_close", rng) for per in ("holdout", "evaluation")}
    disc = out["signals"]["discovery"]
    carried = max(["A1", "A2", "A3"], key=lambda c: disc[c]["IC"] if disc[c]["IC"] == disc[c]["IC"] else -9)
    out["carried_variant"] = carried
    out["holdout_vs_A0"] = paired(panel, carried, "A0", "label_range", "holdout", rng)
    out["holdout_vs_M"] = paired(panel, carried, "M", "label_range", "holdout", rng)
    out["holdout_A0_vs_M"] = paired(panel, "A0", "M", "label_range", "holdout", rng)
    # sanity
    panel["_oracle"] = panel.label_range
    out["sanity_oracle_IC"] = evaluate(panel, "evaluation", ["_oracle"], "label_range", rng)["_oracle"]["IC"]
    rs = []
    for k in range(200):
        r2 = np.random.default_rng(1000 + k)
        panel["_rand"] = r2.random(len(panel))
        rs.append(daily_ic(panel[(panel.date >= e0)], "_rand", "label_range").mean())
    out["sanity_random_IC_mean"], out["sanity_random_IC_sd"] = float(np.mean(rs)), float(np.std(rs))
    panel = panel.drop(columns=["_oracle", "_rand"])
    # decision per the pre-registered rule
    hi_in = out["inputs"]["holdout"]
    any_input = any(v["p_holm"] < 0.05 for v in hi_in.values())
    mde = np.nanmax([v["mde"] for v in hi_in.values()])
    a0_sig = out["signals"]["holdout"]["A0"]["p_holm"] < 0.05
    out["decision"] = dict(
        any_input_significant=bool(any_input), max_mde_inputs=float(mde), A0_significant=bool(a0_sig),
        carried_beats_A0=bool(out["holdout_vs_A0"]["ci95"][0] > 0),
        carried_beats_M=bool(out["holdout_vs_M"]["ci95"][0] > 0),
        verdict=("data problem" if (not any_input and mde < 0.08) else
                 "algorithm problem" if (any_input and not a0_sig) else
                 "inconclusive (sample too small)" if (not any_input) else "signal present and captured"),
    )
    run_dir = RUNS / f"{dt.date.today():%Y-%m-%d}_{out['commit']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(yaml.safe_dump(json.loads(json.dumps(CFG)), sort_keys=False))
    (run_dir / "summary.json").write_text(json.dumps(out, indent=2, default=str))
    panel.to_csv(run_dir / "panel.csv", index=False)
    ics = pd.DataFrame({c: daily_ic(panel, c, "label_range") for c in SIGNALS + INPUTS})
    ics.index.name = "date"
    ics.to_csv(run_dir / "daily_ic.csv")
    print(json.dumps(out["decision"], indent=2))
    print("carried:", carried, "holdout vs A0", out["holdout_vs_A0"], "vs M", out["holdout_vs_M"])
    for per in ("discovery", "holdout"):
        print(per, {c: (round(v["IC"], 3), round(v["p_holm"], 3)) for c, v in out["signals"][per].items()})
        print(per, {c: (round(v["IC"], 3), round(v["p_holm"], 3)) for c, v in out["inputs"][per].items()})
    print("sanity oracle", out["sanity_oracle_IC"], "random", out["sanity_random_IC_mean"], out["sanity_random_IC_sd"])
    return run_dir, out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "run"])
    a = ap.parse_args()
    build() if a.step == "build" else run()
