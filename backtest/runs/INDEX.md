# Backtest runs

Latest run of each version, per study. `p (Holm)` adjusts the pick-vs-random p-value for the number of versions tested in the study. Sanity rows check the harness, not the strategy.

## crypto_indices

| version | mode | days | pool | IC mean [95% CI] | IC p | pick pctl [95% CI] | p | p (Holm) | top-1 hit (random) | momentum pctl | pick − momentum [95% CI] | run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B_atm3 | normal | 57 | 3.56 | +0.059 [-0.12, +0.24] | 0.252 | 0.566 [+0.45, +0.67] | 0.114 | 1.0 | 0.42 (0.31) | 0.498 | +0.068 [-0.09, +0.23] | [2026-10-02_B_atm3_df59eee](crypto_indices/2026-10-02_B_atm3_df59eee/summary.json) |
| B_band_1pct | normal | 55 | 3.71 | +0.072 [-0.11, +0.25] | 0.200 | 0.543 [+0.44, +0.65] | 0.210 | 1.0 | 0.35 (0.30) | 0.653 | -0.109 [-0.25, +0.04] | [2026-10-02_B_band_1pct_df59eee](crypto_indices/2026-10-02_B_band_1pct_df59eee/summary.json) |
| B_band_3pct | normal | 54 | 3.46 | +0.150 [-0.03, +0.34] | 0.052 | 0.629 [+0.52, +0.73] | 0.010 | 0.1176 | 0.44 (0.32) | 0.610 | +0.019 [-0.13, +0.17] | [2026-10-02_B_band_3pct_df59eee](crypto_indices/2026-10-02_B_band_3pct_df59eee/summary.json) |
| B_base | normal | 54 | 3.69 | +0.051 [-0.13, +0.24] | 0.279 | 0.492 [+0.38, +0.60] | 0.562 | 1.0 | 0.33 (0.30) | 0.642 | -0.150 [-0.32, +0.02] | [2026-10-02_B_base_df59eee](crypto_indices/2026-10-02_B_base_df59eee/summary.json) |
| B_cat_crypto | normal | 54 | 3.56 | +0.058 [-0.15, +0.27] | 0.263 | 0.560 [+0.45, +0.67] | 0.140 | 1.0 | 0.39 (0.31) | 0.542 | +0.018 [-0.13, +0.17] | [2026-10-02_B_cat_crypto_df59eee](crypto_indices/2026-10-02_B_cat_crypto_df59eee/summary.json) |
| B_floor_off | normal | 54 | 3.63 | +0.042 [-0.14, +0.22] | 0.317 | 0.516 [+0.40, +0.63] | 0.381 | 1.0 | 0.35 (0.30) | 0.576 | -0.059 [-0.22, +0.10] | [2026-10-02_B_floor_off_df59eee](crypto_indices/2026-10-02_B_floor_off_df59eee/summary.json) |
| B_floor_p20 | normal | 50 | 3.76 | +0.005 [-0.19, +0.21] | 0.472 | 0.514 [+0.40, +0.62] | 0.400 | 1.0 | 0.32 (0.29) | 0.645 | -0.131 [-0.27, +0.01] | [2026-10-02_B_floor_p20_df59eee](crypto_indices/2026-10-02_B_floor_p20_df59eee/summary.json) |
| B_floor_p5 | normal | 53 | 3.62 | +0.138 [-0.05, +0.32] | 0.066 | 0.564 [+0.45, +0.67] | 0.126 | 1.0 | 0.40 (0.30) | 0.615 | -0.051 [-0.20, +0.10] | [2026-10-02_B_floor_p5_df59eee](crypto_indices/2026-10-02_B_floor_p5_df59eee/summary.json) |
| B_idio | normal | 54 | 3.69 | +0.024 [-0.15, +0.20] | 0.397 | 0.505 [+0.40, +0.61] | 0.467 | 1.0 | 0.30 (0.30) | 0.602 | -0.097 [-0.25, +0.06] | [2026-10-02_B_idio_df59eee](crypto_indices/2026-10-02_B_idio_df59eee/summary.json) |
| B_no_cooldown | normal | 57 | 6.0 | -0.028 [-0.15, +0.09] | 0.675 | 0.558 [+0.46, +0.66] | 0.103 | 1.0 | 0.32 (0.18) | 0.630 | -0.072 [-0.21, +0.07] | [2026-10-02_B_no_cooldown_df59eee](crypto_indices/2026-10-02_B_no_cooldown_df59eee/summary.json) |
| C_no_tiers | normal | 55 | 3.55 | +0.048 [-0.13, +0.23] | 0.302 | 0.498 [+0.39, +0.61] | 0.509 | 1.0 | 0.31 (0.31) | 0.641 | -0.142 [-0.29, +0.02] | [2026-10-02_C_no_tiers_df59eee](crypto_indices/2026-10-02_C_no_tiers_df59eee/summary.json) |
| D_kalshi_only | normal | 54 | 3.59 | -0.049 [-0.23, +0.12] | 0.690 | 0.488 [+0.39, +0.59] | 0.584 | 1.0 | 0.30 (0.31) | 0.637 | -0.149 [-0.28, -0.02] | [2026-10-02_D_kalshi_only_df59eee](crypto_indices/2026-10-02_D_kalshi_only_df59eee/summary.json) |
| S_oracle | oracle | 58 | 6.0 | +1.000 [+1.00, +1.00] | 0.000 | 1.000 [+1.00, +1.00] | 0.000 | — | 1.00 (0.18) | 0.636 | +0.364 [+0.27, +0.46] | [2026-10-02_S_oracle_df59eee](crypto_indices/2026-10-02_S_oracle_df59eee/summary.json) |
| S_placebo_random | placebo_random | 58 | 6.0 | -0.104 [-0.19, -0.01] | 0.954 | 0.430 [+0.34, +0.51] | 0.940 | — | 0.10 (0.18) | 0.636 | -0.206 [-0.34, -0.07] | [2026-10-02_S_placebo_random_df59eee](crypto_indices/2026-10-02_S_placebo_random_df59eee/summary.json) |
| S_placebo_shuffle | placebo_shuffle | 58 | 6.0 | +0.018 [-0.10, +0.14] | 0.390 | 0.515 [+0.43, +0.61] | 0.370 | — | 0.16 (0.18) | 0.505 | +0.011 [-0.11, +0.13] | [2026-10-02_S_placebo_shuffle_df59eee](crypto_indices/2026-10-02_S_placebo_shuffle_df59eee/summary.json) |
