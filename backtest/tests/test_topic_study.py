"""Bias checks for study topic_stocks (backtest/studies/topic_stocks/PREREG.md)."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backtest import topic_study as T

pytestmark = pytest.mark.skipif(not (T.SNAP / "adanos_daily.csv.gz").exists(), reason="snapshots not built")


@pytest.fixture(scope="module")
def data():
    ad, pdly, phr, ks, tickers = T.load()
    return ad, pdly, phr, ks, tickers[:15]


def _panel(ad, pdly, phr, ks, tickers):
    return T.add_scores(T.build_panel(ad, pdly, phr, ks, tickers))


def test_features_ignore_data_from_pick_day_onward(data, monkeypatch):
    ad, pdly, phr, ks, tickers = data
    t = dt.date(2026, 9, 15)
    monkeypatch.setattr(T, "EVAL", (t, t))
    p1 = _panel(ad, pdly, phr, ks, tickers)
    ad2, pd2, ph2 = ad.copy(), pdly.copy(), phr.copy()
    ad2.loc[ad2.date >= t, ["mentions", "trade_count", "sentiment_score", "bullish_pct"]] *= 7
    pd2.loc[pd2.date >= t, "high"] *= 1.3
    late = pd.to_datetime(ph2.bar_start_et) >= pd.Timestamp(f"{t} 14:30")
    ph2.loc[late, "close"] *= 1.3
    ks2 = None
    if ks is not None:
        ks2 = ks.copy()
        ks2.loc[ks2.date > t, ["vol_24h", "mid_now"]] = 0.123
    p2 = _panel(ad2, pd2, ph2, ks2, tickers)
    feats = [f for fs in T.FIELDS.values() for f in fs] + ["score", "score_k", "B_most_discussed"]
    pd.testing.assert_frame_equal(p1[feats].reset_index(drop=True), p2[feats].reset_index(drop=True))
    assert not np.allclose(p1.L_A.fillna(0), p2.L_A.fillna(0))   # labels do see the future, as they must


def test_oracle_and_random(data, monkeypatch):
    ad, pdly, phr, ks, tickers = data
    monkeypatch.setattr(T, "EVAL", (dt.date(2026, 9, 1), dt.date(2026, 9, 30)))
    p = _panel(ad, pdly, phr, ks, tickers)
    v = p[p.version == "V1"]
    assert abs(T.daily_ic(v.assign(o=v.L_A), "o", "L_A").mean() - 1) < 1e-9
    r = [T.daily_ic(v.assign(r=np.random.default_rng(k).random(len(v))), "r", "L_A").mean() for k in range(50)]
    assert abs(np.mean(r)) < 0.05
