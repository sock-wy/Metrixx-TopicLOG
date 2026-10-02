# Backtest runs

Latest run of each version, per study. `p (Holm)` adjusts the pick-vs-random p-value for the number of versions tested in the study.

## crypto_indices

| version | mode | days | pool | IC mean [95% CI] | IC p | pick pctl [95% CI] | p | p (Holm) | top-1 hit (random) | momentum pctl | pick − momentum [95% CI] | run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B_atm3 | normal | 57 | 3.56 | +0.059 [-0.12, +0.24] | 0.252 | 0.566 [+0.45, +0.67] | 0.114 | 0.4108 | 0.42 (0.31) | 0.498 | +0.068 [-0.09, +0.23] | [2026-10-02_B_atm3_4caa167](crypto_indices/2026-10-02_B_atm3_4caa167/summary.json) |
| B_base | normal | 54 | 3.69 | +0.051 [-0.13, +0.24] | 0.279 | 0.492 [+0.38, +0.60] | 0.562 | 1.0 | 0.33 (0.30) | 0.642 | -0.150 [-0.32, +0.02] | [2026-10-02_B_base_4caa167](crypto_indices/2026-10-02_B_base_4caa167/summary.json) |
| B_no_cooldown | normal | 57 | 6.0 | -0.028 [-0.15, +0.09] | 0.675 | 0.558 [+0.46, +0.66] | 0.103 | 0.4108 | 0.32 (0.18) | 0.630 | -0.072 [-0.21, +0.07] | [2026-10-02_B_no_cooldown_4caa167](crypto_indices/2026-10-02_B_no_cooldown_4caa167/summary.json) |
| D_kalshi_only | normal | 54 | 3.59 | -0.049 [-0.23, +0.12] | 0.690 | 0.488 [+0.39, +0.59] | 0.584 | 1.0 | 0.30 (0.31) | 0.637 | -0.149 [-0.28, -0.02] | [2026-10-02_D_kalshi_only_4caa167](crypto_indices/2026-10-02_D_kalshi_only_4caa167/summary.json) |
