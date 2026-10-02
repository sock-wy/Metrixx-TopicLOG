"""Bias checks for the backtest harness. Run: python -m pytest -q backtest/tests scoring/tests

These guard the validation itself:
  - no data newer than the pick reaches a feature (snapshots, features, labels)
  - rolling statistics (volume floor, sigma, beta) use only the past
  - sanity modes behave as theory says (oracle = perfect, placebos = random); run in memory, nothing written
"""
import datetime as dt
import pathlib

import numpy as np
import pandas as pd
import pytest

from backtest.labels import build_labels
from backtest.run import compute, load_study
from scoring.features import build_features, load_snapshots

ROOT = pathlib.Path(__file__).resolve().parents[2]
STUDY = ROOT / "backtest" / "studies" / "crypto_indices"
SNAP = ROOT / "backtest" / "snapshots" / "crypto_indices"

pytestmark = pytest.mark.skipif(not (SNAP / "ladder_totals.csv.gz").exists(), reason="snapshots not built")


@pytest.fixture(scope="module")
def snap():
    return load_snapshots(SNAP)


@pytest.fixture(scope="module")
def base():
    return load_study(STUDY / "base.yaml")


def _days(study):
    s, e = (dt.date.fromisoformat(str(study["window"][k])) for k in ("start", "end"))
    return [s + dt.timedelta(days=i) for i in range((e - s).days + 1)]


def test_snapshots_use_only_closed_candles(snap):
    st = snap["strikes"]
    snap_s = (st.snapshot_ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    assert (st.last_candle_ts <= snap_s).all()


def test_features_not_after_pick(snap, base):
    f = build_features(snap, _days(base), list(snap["totals"].ticker.unique()), base["features"])
    assert (pd.to_datetime(f.feature_asof_ts) <= pd.to_datetime(f.pick_ts)).all()


def test_adanos_uses_complete_days_only(snap, base):
    """Changing Adanos data dated on the pick day itself must not change any feature."""
    days = _days(base)[10:20]
    tk = list(snap["totals"].ticker.unique())
    f1 = build_features(snap, days, tk, base["features"])
    s2 = dict(snap)
    a = snap["adanos"].copy()
    a.loc[a.date.isin(days), ["buzz_score", "mentions", "sentiment_score"]] *= 7.0
    s2["adanos"] = a
    # rows for day t use t-1 and t-2; poisoning day t only touches rows of t+1, t+2
    f2 = build_features(s2, days, tk, base["features"])
    first = days[0]
    a1 = f1[f1.date == first].set_index("ticker")["buzz_delta_1d"]
    a2 = f2[f2.date == first].set_index("ticker")["buzz_delta_1d"]
    pd.testing.assert_series_equal(a1, a2)


def test_volume_floor_ignores_future(snap, base):
    days = _days(base)
    tk = ["BTC"]
    t = days[25]
    f1 = build_features(snap, [t], tk, base["features"])
    s2 = dict(snap)
    tot = snap["totals"].copy()
    tot.loc[(tot.ticker == "BTC") & (tot.event_date > t), "total_cum_volume"] *= 1000
    s2["totals"] = tot
    f2 = build_features(s2, [t], tk, base["features"])
    assert f1.volume_floor.iloc[0] == f2.volume_floor.iloc[0]
    assert f1.mkt_volume_delta_1d.iloc[0] == f2.mkt_volume_delta_1d.iloc[0]


def test_labels_are_after_pick_and_sigma_is_past_only(snap, base):
    days = _days(base)
    tk = list(snap["totals"].ticker.unique())
    lab = build_labels(snap["prices"], snap["vol_scale"], days, tk)
    ok = lab.dropna(subset=["next_date"])
    assert (pd.to_datetime(ok.next_date) > pd.to_datetime(ok.date)).all()
    t = days[30]
    vs = snap["vol_scale"]
    lab2 = build_labels(snap["prices"], vs[vs.date < t], [t], tk)
    a = lab[lab.date == t].set_index("ticker")[["sigma20", "abn_move"]]
    b = lab2.set_index("ticker")[["sigma20", "abn_move"]]
    pd.testing.assert_frame_equal(a.loc[b.index], b, check_dtype=False)


def test_oracle_is_perfect():
    s = compute(STUDY / "sanity" / "S_oracle.yaml")[4]
    assert s["hit_top1"] == 1.0 and abs(s["IC_mean"] - 1.0) < 1e-9


@pytest.mark.parametrize("name", ["S_placebo_random", "S_placebo_shuffle"])
def test_placebos_look_random(name):
    s = compute(STUDY / "sanity" / f"{name}.yaml")[4]
    lo, hi = s["pick_pctl_ci95"]
    assert lo <= 0.5 <= hi, s["pick_pctl_ci95"]
    assert abs(s["IC_mean"]) < 0.15
