"""Bias checks for study adanos_crypto (backtest/studies/adanos_crypto/PREREG.md)."""
import datetime as dt
import pathlib

import numpy as np
import pandas as pd
import pytest

from backtest import adanos_study as A

SNAP = pathlib.Path(A.SNAP)
pytestmark = pytest.mark.skipif(not (SNAP / "adanos_daily.csv.gz").exists(), reason="snapshots not built")


def _load():
    ad = pd.read_csv(SNAP / "adanos_daily.csv.gz", parse_dates=["date"])
    ad["date"] = ad.date.dt.date
    px = pd.read_csv(SNAP / "binance_daily.csv.gz", parse_dates=["date"])
    px["date"] = px.date.dt.date
    return ad, px


def test_features_use_only_days_before_t():
    ad, px = _load()
    days = [dt.date(2026, 8, 20)]
    p1 = A.build_panel(ad, px, days)
    # poison everything dated t or later: features must not change, labels must
    ad2, px2 = ad.copy(), px.copy()
    ad2.loc[ad2.date >= days[0], ["buzz_score", "mentions", "sentiment_score"]] *= 9
    px2.loc[px2.date >= days[0], ["high"]] *= 1.5
    p2 = A.build_panel(ad2, px2, days)
    feat = ["buzz_d1", "mentions_d1", "sentiment_d1", "buzz_z", "mentions_z", "sentiment_z",
            "buzz_s3", "mentions_s3", "sentiment_s3", "M"]
    pd.testing.assert_frame_equal(p1[feat], p2[feat])
    assert not np.allclose(p1.label_range.fillna(0), p2.label_range.fillna(0))


def test_universe_fixed_in_formation_period():
    sel = pd.read_csv(SNAP / "universe_selection.csv")
    assert sel.selected.sum() <= A.CFG["top_n"]
    assert (sel[sel.selected].formation_coverage >= A.CFG["min_coverage"]).all()
