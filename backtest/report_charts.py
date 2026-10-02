"""Charts for a study report, built from the latest run of each version.

    python -m backtest.report_charts --study crypto_indices
Writes PNGs to backtest/runs/<study>/report/.
"""
from __future__ import annotations

import argparse
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scoring.scoring import COMPONENTS  # noqa: E402

RUNS = pathlib.Path(__file__).resolve().parent / "runs"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
})


def latest(study_dir):
    out = {}
    for d in sorted(study_dir.iterdir()):
        sj = d / "summary.json"
        if sj.exists():
            s = json.loads(sj.read_text())
            out[s["version"]] = (d, s)
    return out


def ci95(x):
    x = pd.Series(x).dropna()
    if len(x) < 3:
        return np.nan, np.nan
    h = 1.96 * x.std(ddof=1) / np.sqrt(len(x))
    return x.mean() - h, x.mean() + h


def forest(runs, out):
    normal = {v: s for v, (_, s) in runs.items() if s["mode"] == "normal"}
    order = sorted(normal, key=lambda v: normal[v]["pick_pctl"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.42 * len(order) + 1.6), sharey=True)
    y = np.arange(len(order))
    ax = axes[0]
    for i, v in enumerate(order):
        s = normal[v]
        lo, hi = s["pick_pctl_ci95"]
        ax.plot([lo, hi], [i, i], color=BLUE, lw=2, solid_capstyle="round")
        ax.plot(s["pick_pctl"], i, "o", color=BLUE, ms=7, mec=SURFACE, mew=2, zorder=3)
        ax.plot(s["momentum_pctl"], i, "D", color=ORANGE, ms=6, mec=SURFACE, mew=1.5, zorder=3)
    ax.axvline(0.5, color=INK2, lw=1, ls="--")
    ax.set_yticks(y, order)
    ax.set_xlim(0.25, 0.85)
    ax.set_xlabel("Pick's percentile in the pool (0.5 = random)")
    ax.set_title("Where the pick landed, next-day move", loc="left", fontsize=11)
    ax.plot([], [], "o", color=BLUE, label="demand_score pick (95% CI)")
    ax.plot([], [], "D", color=ORANGE, label="momentum benchmark")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax = axes[1]
    for i, v in enumerate(order):
        s = normal[v]
        lo, hi = s["IC_ci95"]
        ax.plot([lo, hi], [i, i], color=BLUE, lw=2, solid_capstyle="round")
        ax.plot(s["IC_mean"], i, "o", color=BLUE, ms=7, mec=SURFACE, mew=2, zorder=3)
    ax.axvline(0, color=INK2, lw=1, ls="--")
    ax.set_xlim(-0.4, 0.4)
    ax.set_xlabel("Mean daily rank IC (0 = no relation)")
    ax.set_title("Score vs next-day move", loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "versions_forest.png", dpi=160)
    plt.close(fig)


def components(runs, out, versions=("B_base", "B_no_cooldown")):
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    h = 0.36
    colors = [BLUE, AQUA]
    for j, v in enumerate(versions):
        d = pd.read_csv(runs[v][0] / "daily_log.csv")
        for i, k in enumerate(COMPONENTS):
            x = d[f"IC_{k}"]
            m = x.mean()
            lo, hi = ci95(x)
            yy = i + (j - 0.5) * h
            ax.barh(yy, m, height=h * 0.9, color=colors[j], edgecolor=SURFACE, lw=2)
            ax.plot([lo, hi], [yy, yy], color=INK2, lw=1.2)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(range(len(COMPONENTS)), COMPONENTS)
    ax.invert_yaxis()
    ax.set_xlim(-0.45, 0.45)
    ax.set_xlabel("Mean daily rank IC with next-day move (bar) and 95% CI (line)")
    ax.set_title("Which components carry information", loc="left", fontsize=11)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=colors[j], label=v) for j, v in enumerate(versions)],
              loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "component_ic.png", dpi=160)
    plt.close(fig)


def gates(runs, out, version="B_base"):
    d = pd.read_csv(runs[version][0] / "daily_log.csv")
    f = pd.read_csv(runs[version][0] / "features.csv")
    cand = f.groupby("ticker").size()
    g = d.gated.dropna().str.split().explode().reset_index(drop=True).str.split(":", expand=True)
    g.columns = ["ticker", "gate"]
    tab = pd.crosstab(g.ticker, g.gate).reindex(cand.index).fillna(0)
    share = tab.div(cand, axis=0)
    order = share.sum(axis=1).sort_values().index
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    left = np.zeros(len(order))
    for gate, col in [("G2", INK2), ("G3", ORANGE), ("G4", BLUE)]:
        if gate not in share:
            continue
        vals = share.loc[order, gate].values
        ax.barh(order, vals, left=left, color=col, edgecolor=SURFACE, lw=2, label={
            "G2": "G2 no traded contract", "G3": "G3 liquidity floor", "G4": "G4 cooldown"}[gate])
        left += vals
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of candidate days removed by a gate")
    ax.set_title(f"Why tickers left the pool ({version})", loc="left", fontsize=11)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "gates_by_ticker.png", dpi=160)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    a = ap.parse_args(argv)
    study_dir = RUNS / a.study
    runs = latest(study_dir)
    out = study_dir / "report"
    out.mkdir(exist_ok=True)
    forest(runs, out)
    components(runs, out)
    gates(runs, out)
    print("charts ->", out)


if __name__ == "__main__":
    main()
