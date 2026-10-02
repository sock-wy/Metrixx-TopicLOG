# Proposed changelog entry (not yet in config/CHANGELOG.md)

Copy above the w0 entry in `config/CHANGELOG.md` if adopted, and move
`weights_w1_proposed.yaml` to `config/weights_w1.yaml`.

## w1 — YYYY-MM-DD

- **Change**: `gates.G3_liquidity_floor` measured on the 3 strikes nearest the implied median
  for Kalshi ladders (new key `ladder_nearest_strikes: 3`); thresholds unchanged (0.80 / 0.30).
- **Reason**: on Kalshi ladders the zero-trade share depends on strike spacing, not liquidity.
  A ±2% band holds ~1 strike for DOGE and ~120 for NDX; NDX was removed by G3 on 59% of days.
  Backtest `crypto_indices` (2026-10-02, `backtest/runs/crypto_indices/REPORT.md`), version `B_atm3`.
  The change is justified by comparability; its effect on pick quality was not significant
  (pick percentile 0.566 vs 0.492, Holm p = 1.0).
- **Expected effect**: NDX and DJI enter the pool on most trading days; G3 rejections track
  real illiquidity (thin quotes at the money) instead of ladder granularity.
- **Code needed**: `scoring/features.py` reads `ladder_nearest_strikes` from the active config
  (the backtest passes it as the study parameter `liquidity_strikes`).
