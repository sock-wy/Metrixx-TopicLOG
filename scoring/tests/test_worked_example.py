"""Scoring must reproduce the playbook worked example (playbook/README.md section 6)."""
import pathlib

from scoring.scoring import load_config, score_day

CFG = pathlib.Path(__file__).resolve().parents[2] / "config" / "weights_w0.yaml"

# Pool copied from playbook/index.html (illustrative values).
POOL = [
    ("SPX", 4.2, 35, 0.08, 0.06, 0.14, 62, 18, 0.07, 0.30, 2, 2, 1, 12),
    ("NDX", 9.8, 80, 0.21, 0.11, 0.24, 140, 40, 0.09, 0.35, 2, 9, 1, 8),
    ("DJI", -2.1, -10, 0.03, 0.02, 0.06, -15, 3, 0.12, 0.55, 2, 12, None, 5),
    ("AAPL", -7.1, -70, 0.385, 0.05, 0.18, 10, None, 0.151, 0.506, 1, 13, None, 1),
    ("NVDA", 12.5, 120, 0.30, 0.09, 0.22, 95, None, 0.11, 0.40, 1, 5, 1, 6),
    ("TSLA", 15.2, 60, 0.45, 0.03, 0.09, 20, None, 0.19, 0.48, 1, 20, None, 1),
    ("MSFT", 1.0, 5, 0.05, 0.01, 0.04, -5, None, 0.22, 0.82, 1, 30, None, 1),
    ("AMZN", 3.4, 22, 0.12, None, None, None, None, None, None, 1, 40, None, 0),
]


def rows():
    out = []
    for tk, b, t, s, pd, rg, v, oi, sp, z, src, days, cat, depth in POOL:
        out.append(
            dict(
                ticker=tk, buzz_delta_1d=b, trade_count_pct_change_1d=t,
                sentiment_delta_1d=s, mkt_prob_delta_1d=pd, mkt_prob_range_1d=rg,
                mkt_volume_delta_1d=v, mkt_oi_delta_1d=oi, avg_spread=sp,
                zero_trade_market_pct=z, sources_available=src, days_since_covered=days,
                catalyst_in_trading_days=cat, mkt_ladder_depth=depth,
                has_market_evidence=not (pd is None and v is None),
            )
        )
    return out


def test_worked_example():
    live, gated = score_day(rows(), load_config(CFG))
    got = [(r["ticker"], r["tier"], round(r["demand_score"], 3)) for r in live]
    assert got == [
        ("NDX", "T1", 0.584),
        ("NVDA", "T1", 0.416),
        ("TSLA", "T3", 0.349),
        ("AAPL", "T4", 0.167),
        ("DJI", "T4", 0.059),
    ], got
    assert {r["ticker"]: r["data_quality_flag"] for r in gated} == {
        "SPX": "G4", "MSFT": "G3", "AMZN": "G2"}


if __name__ == "__main__":
    test_worked_example()
    print("worked example reproduced")
