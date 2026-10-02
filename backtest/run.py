"""Run one backtest version, or every version of a study.

    python -m backtest.run backtest/studies/crypto_indices/base.yaml
    python -m backtest.run --study backtest/studies/crypto_indices      # all versions + sanity checks

Each run writes backtest/runs/<study>/<YYYY-MM-DD>_<version>_<commit>/ and refreshes
backtest/runs/INDEX.md. Runs read only the committed snapshot tables, never the APIs.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import subprocess

import numpy as np
import pandas as pd
import yaml

from backtest import engine, evaluate
from backtest.labels import build_labels
from scoring.features import build_features, load_snapshots
from scoring.scoring import COMPONENTS

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ROOT / "backtest" / "runs"


def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_study(path):
    path = pathlib.Path(path)
    cfg = yaml.safe_load(path.read_text()) or {}
    if "inherits" in cfg:
        parent = load_study(path.parent / cfg.pop("inherits"))
        cfg = deep_merge(parent, cfg)
    return cfg


def git_commit():
    try:
        h = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.call(["git", "-C", str(ROOT), "diff", "--quiet", "--", "scoring", "backtest/engine.py",
                                 "backtest/labels.py", "backtest/evaluate.py", "backtest/run.py"])
        return h + ("-dirty" if dirty else "")
    except Exception:
        return "nogit"


def run_one(study_path, quiet=False):
    study = load_study(study_path)
    universe = yaml.safe_load((ROOT / study["universe"]).read_text())
    weights_cfg = deep_merge(yaml.safe_load((ROOT / study["weights"]).read_text()), study.get("weights_overrides"))
    weights = {k: weights_cfg["components"][k]["weight"] for k in COMPONENTS}
    cats_file = yaml.safe_load((ROOT / study["catalysts"]["file"]).read_text())
    cats = dict(events=cats_file["events"], applies_to=study["catalysts"].get("applies_to", cats_file["applies_to"]))
    for e in cats["events"]:
        e["date"] = e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(str(e["date"]))

    snap = load_snapshots(ROOT / study["snapshots"])
    start, end = (dt.date.fromisoformat(str(study["window"][k])) for k in ("start", "end"))
    pick_days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    tickers = list(universe["tickers"])
    crypto = [t for t, s in universe["tickers"].items() if s["asset_class"] == "crypto"]

    feats = build_features(snap, pick_days, tickers, study.get("features"))
    labels = build_labels(snap["prices"], snap["vol_scale"], pick_days, tickers, crypto=crypto)
    rng = np.random.default_rng(study.get("seed", 7))
    days, pools, skipped = engine.run(feats, labels, weights_cfg, weights, study, universe, cats, rng)
    summary, per_day = evaluate.summarize(days, pools, np.random.default_rng(study.get("seed", 7)))
    summary["skipped_days"] = int(len(skipped))
    summary["gate_counts"] = (pd.Series(" ".join(days.gated.fillna("")).split()).str.split(":").str[1]
                              .value_counts().to_dict() if len(days) else {})

    study_name = pathlib.Path(study_path).resolve().parent.name if study.get("mode", "normal") == "normal" \
        else pathlib.Path(study_path).resolve().parent.parent.name
    out = RUNS / study_name / f"{dt.date.today():%Y-%m-%d}_{study['name']}_{git_commit()}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(yaml.safe_dump(json.loads(json.dumps(study, default=str)), sort_keys=False))
    meta = dict(version=study["name"], study=study_name, mode=study.get("mode", "normal"),
                commit=git_commit(), run_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                snapshots_meta=json.loads((ROOT / study["snapshots"] / "meta.json").read_text()),
                weights_version=weights_cfg["version"])
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    feats.to_csv(out / "features.csv", index=False)
    days.merge(per_day.drop(columns=["pick"]), on="date", how="left").to_csv(out / "daily_log.csv", index=False)
    pools.to_csv(out / "pool_log.csv", index=False)
    skipped.to_csv(out / "skipped.csv", index=False)
    summary = dict(version=study["name"], mode=study.get("mode", "normal"), description=study.get("description", ""),
                   **summary)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if not quiet:
        print(f"{study['name']:22s} days={summary['days']:3d} IC={summary['IC_mean']:+.3f} "
              f"pick_pctl={summary['pick_pctl']:.3f} p={summary['p_value_vs_random']:.3f} -> {out.relative_to(ROOT)}")
    return out, summary


def write_index():
    lines = ["# Backtest runs", "",
             "Latest run of each version, per study. `p (Holm)` adjusts the pick-vs-random p-value for the number "
             "of versions tested in the study. Sanity rows check the harness, not the strategy.", ""]
    for study_dir in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        latest = {}
        for run_dir in sorted(study_dir.iterdir()):
            sj = run_dir / "summary.json"
            if sj.exists():
                s = json.loads(sj.read_text())
                latest[s["version"]] = (run_dir.name, s)  # sorted by name -> last date wins
        normal = {v: s for v, (_, s) in latest.items() if s["mode"] == "normal"}
        adj = evaluate.holm({v: s["p_value_vs_random"] for v, s in normal.items()})
        lines += [f"## {study_dir.name}", "",
                  "| version | mode | days | pool | IC mean [95% CI] | IC p | pick pctl [95% CI] | p | p (Holm) | "
                  "top-1 hit (random) | momentum pctl | pick − momentum [95% CI] | run |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for v, (run, s) in sorted(latest.items(), key=lambda x: (x[1][1]["mode"] != "normal", x[0])):
            ci = lambda a: f"[{a[0]:+.2f}, {a[1]:+.2f}]"
            lines.append(
                f"| {v} | {s['mode']} | {s['days']} | {s['avg_pool']} | {s['IC_mean']:+.3f} {ci(s['IC_ci95'])} | {s.get('IC_p_value', float('nan')):.3f} | "
                f"{s['pick_pctl']:.3f} {ci(s['pick_pctl_ci95'])} | {s['p_value_vs_random']:.3f} | "
                f"{adj.get(v, '—')} | {s['hit_top1']:.2f} ({s['random_hit_top1']:.2f}) | {s['momentum_pctl']:.3f} | "
                f"{s['pick_minus_momentum']:+.3f} {ci(s['pick_minus_momentum_ci95'])} | "
                f"[{run}]({study_dir.name}/{run}/summary.json) |")
        lines.append("")
    (RUNS / "INDEX.md").write_text("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?")
    ap.add_argument("--study")
    a = ap.parse_args(argv)
    paths = [a.config] if a.config else sorted(str(p) for p in pathlib.Path(a.study).rglob("*.yaml"))
    for p in paths:
        if pathlib.Path(p).name.startswith("_"):
            continue
        run_one(p)
    write_index()


if __name__ == "__main__":
    main()
