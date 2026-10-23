"""Study v3: direction backtests (A social, B price, C prediction markets, D rules) and the overall champion.

Target: next day's attention (0.7) and next session's abnormal price move (0.3), combined as within-day percentiles.
Each candidate is a within-day ranking. Metrics per day: rank IC with the label, mean label percentile of the top 5.
Champion choice uses discovery days only; holdout days are reported once. One-sided t-tests on daily IC, Holm within
each direction. Output: backtest/v3/results.json
"""
from __future__ import annotations

import itertools
import json
import math
import pathlib

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
V3 = ROOT / "backtest" / "v3"
rng = np.random.default_rng(11)
SPLIT = pd.Timestamp("2026-10-01")          # Adanos-era discovery / holdout
SPLIT_B = pd.Timestamp("2026-07-01")        # price-only long history
ADANOS_START = pd.Timestamp("2026-08-24")
PL = ["reddit", "x", "news"]

A_FEATS = {
    "lvl20_all": "mentions vs 20-day normal, all platforms (w1)", "lvl7_all": "mentions vs 7-day normal", "lvl14_all": "mentions vs 14-day normal",
    "lvl30_all": "mentions vs 30-day normal", "raw_all": "mentions, raw level", "act3_all": "mentions 3 days vs 3 before (w1)",
    "act1_all": "mentions 1-day change", "trend_rank": "best rank in Adanos trending lists",
    **{f"lvl20_{p}": f"mentions vs 20-day normal, {p}" for p in PL}, **{f"buzzd1_{p}": f"buzz 1-day change, {p}" for p in PL},
    **{f"buzzlvl_{p}": f"buzz vs 20-day normal, {p}" for p in PL}, **{f"sentd1_{p}": f"|sentiment 1-day change|, {p}" for p in PL},
    **{f"sentlvl_{p}": f"|sentiment vs 20-day normal|, {p}" for p in PL}, **{f"bulldev_{p}": f"|bullish % vs normal|, {p}" for p in PL},
    "lvl20_polymarket": "Adanos Polymarket trades vs 20-day normal",
}
B_FEATS = {"mom": "|24h move| / 20-day σ (w1)", "mom_s60": "|24h move| / 60-day σ", "mom_5d": "|5-day move| / σ",
           "rng_abn": "intraday range so far vs normal", "vol_abn": "volume so far vs normal", "gap": "|move since yesterday's close| / σ"}
C_FEATS = {"k_flow": "Kalshi 24h volume vs prior 24h (w0/w1)", "k_vol_abn": "Kalshi 24h volume vs 20-day normal",
           "k_oi_chg": "Kalshi OI vs 24h earlier (w0/w1)", "k_oi_abn": "Kalshi OI vs 20-day normal", "k_move": "Kalshi |prob move| 24h (w0/w1)",
           "k_move_abn": "Kalshi |prob move| vs normal", "k_vol_raw": "Kalshi 24h volume, level", "p_move": "Polymarket |prob move| 1 day",
           "pp_vol_abn": "perps volume vs normal", "pp_oi_chg": "perps OI change", "pp_fund_abs": "perps |funding rate|", "pp_fund_chg": "perps |funding change|"}


def daypct(df, col):
    return df.groupby("day")[col].rank(pct=True)


def boot(x, n=3000):
    x = np.asarray([v for v in x if v == v])
    if len(x) < 3:
        return [float("nan")] * 3
    m = rng.choice(x, size=(n, len(x))).mean(1)
    return [float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def tp(x):
    x = np.asarray([v for v in x if v == v])
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan"), float("nan")
    t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))
    return float(t), float(0.5 * math.erfc(t / math.sqrt(2)))  # one-sided, normal approx


def holm(ps):
    keys = [k for k in ps if ps[k] == ps[k]]
    order = sorted(keys, key=lambda k: ps[k])
    out, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, ps[k] * (len(order) - i)))
        out[k] = run
    return out


def day_ic(df, feat, label, min_n=15):
    d = df[["day", feat, label]].dropna()
    g = d.groupby("day")
    ok = g.size()
    ok = ok[ok >= min_n].index
    d = d[d.day.isin(ok)]
    if d.empty:
        return pd.DataFrame(columns=["day", "ic", "top5", "n"])
    r1 = d.groupby("day")[feat].rank()
    r2 = d.groupby("day")[label].rank()
    lp = d.groupby("day")[label].rank(pct=True)
    d = d.assign(r1=r1, r2=r2, lp=lp)
    ic = d.groupby("day").apply(lambda x: x.r1.corr(x.r2), include_groups=False)
    top = d.sort_values(feat, ascending=False).groupby("day").head(5).groupby("day").lp.mean()
    n = d.groupby("day").size()
    return pd.DataFrame({"ic": ic, "top5": top, "n": n}).reset_index()


def summarize(r, split):
    out = {}
    for part, sub in (("all", r), ("discovery", r[r.day < split]), ("holdout", r[r.day >= split])):
        out[part] = {"ic": boot(sub.ic), "top5": boot(sub.top5), "days": int(len(sub)), "n": float(sub.n.mean()) if len(sub) else 0}
    out["t"], out["p"] = tp(r.ic)
    return out


def direction(df, feats, labels, split, name):
    res = {}
    for lab in labels:
        rows = {}
        for f in feats:
            if f not in df:
                continue
            r = day_ic(df, f, lab)
            if len(r) >= 5:
                rows[f] = summarize(r, split)
        hp = holm({f: v["p"] for f, v in rows.items()})
        for f in rows:
            rows[f]["p_holm"] = hp.get(f, float("nan"))
        res[lab] = rows
        print(f"[{name}] {lab}:", ", ".join(f"{f} {v['all']['ic'][0]:+.3f}" for f, v in sorted(rows.items(), key=lambda kv: -kv[1]['discovery']['ic'][0])[:6]))
    return res


def blend(df, cols, weights=None):
    w = weights or {c: 1.0 for c in cols}
    s = sum(w[c] * daypct(df, c).fillna(0.5) for c in cols)
    return s / sum(w.values())


def forward_select(df, cands, label, split, k=3):
    disc = df[df.day < split]
    chosen, best = [], -9
    for _ in range(k):
        scores = {}
        for c in cands:
            if c in chosen:
                continue
            tmp = disc.assign(_s=blend(disc, chosen + [c]))
            scores[c] = day_ic(tmp, "_s", label).ic.mean()
        if not scores:
            break
        c, v = max(scores.items(), key=lambda kv: kv[1])
        if v <= best + 0.003:
            break
        chosen.append(c)
        best = v
    return chosen, best


def main():
    df = pd.read_parquet(V3 / "panel.parquet")
    df["day"] = pd.to_datetime(df.day)
    # combined target where both labels exist
    both = df.dropna(subset=["label_attn", "label_move"]).copy()
    both["label_comb"] = 0.7 * daypct(both, "label_attn") + 0.3 * daypct(both, "label_move")
    df = df.merge(both[["day", "entity", "label_comb"]], on=["day", "entity"], how="left")
    R = {"meta": {}, "A": {}, "B": {}, "C": {}, "D": {}, "overall": {}}
    LAB = ["label_comb", "label_attn", "label_move"]

    # ---------------- A · social (Adanos-covered entities, Adanos era)
    A = df[(df.day >= ADANOS_START) & df.raw_all.notna()]
    R["meta"]["A"] = dict(days=int(A.day.nunique()), per_day=float(A.groupby("day").size().mean()), first=str(A.day.min().date()), last=str(A.day.max().date()))
    R["A"]["single"] = direction(A, A_FEATS, LAB, SPLIT, "A")
    selA, _ = forward_select(A, [f for f in A_FEATS if f in A], "label_comb", SPLIT)
    A = A.assign(champ_A=blend(A, selA))
    R["A"]["champion"] = {"features": selA, **{lab: summarize(day_ic(A, "champ_A", lab), SPLIT) for lab in LAB}}

    # ---------------- B · price (all priced entities): long history on move, Adanos era on the combined target
    B = df[df.mom.notna()]
    R["meta"]["B"] = dict(days=int(B.day.nunique()), per_day=float(B.groupby("day").size().mean()), first=str(B.day.min().date()), last=str(B.day.max().date()))
    R["B"]["single_long"] = direction(B, B_FEATS, ["label_move"], SPLIT_B, "B long")
    BA = B[(B.day >= ADANOS_START) & B.raw_all.notna()]
    R["B"]["single"] = direction(BA, B_FEATS, LAB, SPLIT, "B")
    selB, _ = forward_select(B[B.day >= pd.Timestamp("2025-03-01")], list(B_FEATS), "label_move", SPLIT_B, k=2)
    df["champ_B"] = blend(df, selB)
    BA = BA.assign(champ_B=blend(BA, selB))
    R["B"]["champion"] = {"features": selB, "label_move_long": summarize(day_ic(df[df.mom.notna()], "champ_B", "label_move"), SPLIT_B),
                          **{lab: summarize(day_ic(BA, "champ_B", lab), SPLIT) for lab in LAB}}

    # ---------------- C · prediction markets (topics with Kalshi volume)
    C = df[(df.k_vol > 0)]
    R["meta"]["C"] = dict(days=int(C.day.nunique()), per_day=float(C.groupby("day").size().mean()), first=str(C.day.min().date()), last=str(C.day.max().date()))
    R["C"]["single_long"] = direction(C, C_FEATS, ["label_move"], pd.Timestamp("2026-08-01"), "C long")
    CA = C[C.day >= ADANOS_START]
    R["C"]["single"] = direction(CA, C_FEATS, LAB, SPLIT, "C")
    selC, _ = forward_select(CA, [f for f in C_FEATS if f in CA and CA[f].notna().mean() > 0.3], "label_comb", SPLIT, k=2)
    df["champ_C"] = blend(df, selC) if selC else np.nan
    R["C"]["champion"] = {"features": selC, "label_move_long": summarize(day_ic(df[df.k_vol > 0], "champ_C", "label_move"), pd.Timestamp("2026-08-01")),
                          **{lab: summarize(day_ic(df[(df.k_vol > 0) & (df.day >= ADANOS_START)], "champ_C", lab), SPLIT) for lab in LAB}}

    # ---------------- overall: weights over the three champions, on two pools
    E = df[(df.day >= ADANOS_START)].copy()
    E["champ_A"] = blend(E, selA).where(E.raw_all.notna())
    E["champ_B"] = blend(E, selB)
    E["champ_C"] = (blend(E, selC) if selC else np.nan)
    E.loc[~(E.k_vol > 0), "champ_C"] = np.nan
    # reference scores
    def ref(E, w, missing="median"):
        cols = list(w)
        if missing == "median":
            return sum(w[c] * daypct(E, c).fillna(0.5) for c in cols) / sum(w.values())
        num = sum(w[c] * daypct(E, c).fillna(0) for c in cols)
        den = sum(w[c] * E[c].notna() for c in cols)
        return num / den.replace(0, np.nan)
    E["w1"] = ref(E, {"lvl20_all": .30, "act3_all": .10, "k_flow": .15, "k_oi_chg": .10, "k_move": .10, "mom": .25})
    E["w0"] = ref(E, {"buzzd1_reddit": .25, "act1_reddit": .10, "k_flow": .20, "k_oi_chg": .10, "k_move": .20, "sentd1_reddit": .15}, "drop")
    pools = {"prediction": E[(E.k_vol > 0) | E.p_move.notna()], "all": E[E.raw_all.notna()]}
    grid = [w for w in itertools.product(np.arange(0, 1.01, 0.05), repeat=2) if w[0] + w[1] <= 1.0001]
    for pname, P in pools.items():
        P = P.copy()
        pa, pb, pc = (daypct(P, c) for c in ("champ_A", "champ_B", "champ_C"))
        best = None
        disc = P.day < SPLIT
        for wa, wb in grid:
            wc = 1 - wa - wb
            s = wa * pa.fillna(0.5) + wb * pb.fillna(0.5) + wc * pc.fillna(0.5)
            r_ = day_ic(P[disc].assign(_s=s[disc]), "_s", "label_comb", 10)
            v = r_.ic.mean() + (r_.top5.mean() - 0.5)   # whole ranking and the top 5 the dashboard shows
            if best is None or v > best[0]:
                best = (v, wa, wb, wc)
        _, wa, wb, wc = best
        P["overall"] = wa * pa.fillna(0.5) + wb * pb.fillna(0.5) + wc * pc.fillna(0.5)
        res = {"weights": {"A": round(wa, 2), "B": round(wb, 2), "C": round(wc, 2)}, "objective": "IC + (top-5 percentile - 0.5), discovery days"}
        for col in ("overall", "w1", "w0", "mom", "champ_A", "champ_B", "champ_C"):
            res[col] = {lab: summarize(day_ic(P, col, lab, min_n=10), SPLIT) for lab in LAB}
        # paired differences on the holdout
        o = day_ic(P, "overall", "label_comb", 10).set_index("day")
        for col in ("w1", "mom"):
            r = day_ic(P, col, "label_comb", 10).set_index("day")
            j = o.join(r, rsuffix="_r", how="inner")
            res[f"overall_minus_{col}"] = {"all": boot(j.ic - j.ic_r), "holdout": boot((j.ic - j.ic_r)[j.index >= SPLIT])}
        R["overall"][pname] = res
        print(f"[overall {pname}] weights A {wa:.2f} B {wb:.2f} C {wc:.2f} ->",
              {c: round(res[c]['label_comb']['holdout']['ic'][0], 3) for c in ('overall', 'w1', 'w0', 'mom')})
        if pname == "prediction":
            PD = P

    # ---------------- D · rules, on the overall score in the prediction pool
    D = {}
    W = R["overall"]["prediction"]["weights"]
    P = PD.copy()
    pa, pb, pc = (daypct(P, c) for c in ("champ_A", "champ_B", "champ_C"))
    num = W["A"] * pa.fillna(0) + W["B"] * pb.fillna(0) + W["C"] * pc.fillna(0)
    den = W["A"] * pa.notna() + W["B"] * pb.notna() + W["C"] * pc.notna()
    P["drop_missing"] = num / den.replace(0, np.nan)
    D["missing"] = {k: summarize(day_ic(P, k, "label_comb", 10), SPLIT) for k in ("overall", "drop_missing")}
    # cooldown: the day's pick may not repeat a pick of the last N trading days
    lp = P.groupby("day").label_comb.rank(pct=True)
    P = P.assign(lp=lp)
    cd = {}
    for N in (0, 1, 3, 5):
        recent, vals, days_ = [], [], []
        for d, g in P.dropna(subset=["label_comb"]).sort_values("day").groupby("day"):
            g = g.sort_values("overall", ascending=False)
            g = g[~g.entity.isin(set(sum(recent[-N:], [])) if N else set())]
            if g.empty:
                continue
            pick = g.iloc[0]
            vals.append(pick.lp); days_.append(d)
            recent.append([pick.entity])
        s = pd.Series(vals, index=days_)
        cd[str(N)] = {"all": boot(s), "holdout": boot(s[s.index >= SPLIT]), "unique_picks": int(len(set(e for r in recent for e in r)))}
    D["cooldown_top1"] = cd
    # diversity: top 5 with at most 2 per asset class
    def top5(g, cap):
        out, cnt = [], {}
        for _, r in g.sort_values("overall", ascending=False).iterrows():
            if cap and cnt.get(r.asset_class, 0) >= cap:
                continue
            out.append(r.lp); cnt[r.asset_class] = cnt.get(r.asset_class, 0) + 1
            if len(out) == 5:
                break
        return np.mean(out) if out else np.nan
    for cap in (0, 2):
        s = P.dropna(subset=["label_comb"]).groupby("day").apply(lambda g: top5(g, cap), include_groups=False)
        D[f"top5_cap{cap}"] = {"all": boot(s), "holdout": boot(s[s.index >= SPLIT])}
    R["D"] = D
    R["meta"]["selected"] = {"A": selA, "B": selB, "C": selC}
    (V3 / "results.json").write_text(json.dumps(R, indent=1, default=float))
    print("selected", R["meta"]["selected"])


if __name__ == "__main__":
    main()
