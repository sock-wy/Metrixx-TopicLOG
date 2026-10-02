# Pre-registration — study `adanos_crypto`

Written 2026-10-02T07:45Z, before any Adanos history for this study was pulled and before any label was computed.
Nothing below may change after results are seen. Anything added later goes in a dated "Amendments" section and is reported as exploratory.

## Question

Is the weakness found in study `crypto_indices` a **data** problem (Adanos signals carry no information about the next day's market activity) or an **algorithm** problem (the information is there, but the `demand_score` construction loses it)?

## Data

| Item | Rule |
|---|---|
| Sentiment | Adanos Reddit crypto, `/reddit/crypto/v1/token/{symbol}`, `daily_trend` fields `buzz_score`, `mentions`, `sentiment_score` |
| Prices | Binance spot daily klines, `<SYMBOL>USDT`, from `data-api.binance.vision` (UTC days) |
| History | 2026-07-04 → 2026-10-01 (the account's 90-day lookback limit) |
| Formation period | 2026-07-04 → 2026-08-02: universe selection and baseline warm-up only; never evaluated |
| Evaluation period | 2026-08-03 → 2026-10-01 (60 days) |
| Discovery / holdout | discovery 2026-08-03 → 2026-09-07 (36 days); holdout 2026-09-08 → 2026-10-01 (24 days) |

## Universe (fixed from the formation period only)

1. Candidates: the Adanos Reddit crypto trending list for 2026-07-04 → 2026-08-02 (top 100 by the API's order).
2. Exclude stablecoins, wrapped and asset-backed tokens (USDT, USDC, DAI, FDUSD, TUSD, USDE, RLUSD, WETH, WBTC, STETH, PAXG, XAUT).
3. Require a Binance `<SYMBOL>USDT` spot pair with a daily kline on every day of the history.
4. Require mentions on at least 80% of formation days and a median of at least 3 mentions per day in the formation period.
5. Keep the top 30 by total formation-period mentions. If fewer than 30 pass, keep all that pass.

## Timing (no look-ahead)

Decision time for day *t* is 00:00 UTC on *t*. Features use only complete UTC days ≤ *t*−1 (Adanos and Binance). The label is day *t*.

## Label

- **Primary:** abnormal range `ln(high_t / low_t) / mean(ln(high/low) over days t−20 … t−1)`.
- **Secondary (reported, not used for decisions):** `|ln(close_t / close_{t−1})| / std(daily log returns over t−20 … t−1)`.

## Signals

Inputs are the three Adanos components with w0 weights, renormalised: attention 0.25 (`buzz_score`), activity 0.10 (`mentions`), sentiment 0.15 (`sentiment_score`).

| Version | Construction |
|---|---|
| **A0** | w0 as written: 1-day changes (buzz *t*−1 minus *t*−2; mentions % change; \|sentiment change\|) → within-day percentile → weighted mean |
| **A1** | Abnormal level instead of change: z-score of the *t*−1 value against the token's own days *t*−31 … *t*−2 (mentions on log1p; sentiment as \|z\|) → within-day percentile → weighted mean |
| **A2** | A1's z-scores, clipped to ±5, averaged with the same weights directly (no percentile step) |
| **A3** | 3-day smoothing: mean of *t*−1 … *t*−3 vs mean of *t*−4 … *t*−6 for buzz and sentiment (\|change\|); % change of 3-day mention sums → percentile → weighted mean |
| **M** | Momentum benchmark: day *t*−1 abnormal range (same construction as the primary label) |

Individual inputs, tested separately (the data question): buzz, mentions, sentiment, each as 1-day change and as z-score (6 signals).

Not used (Kalshi-specific or editorial): gates G2–G5, quality multiplier, tiers, cooldown. G1 freshness holds by construction.

## Metric and tests

- **Metric:** mean daily Spearman rank IC between signal and label across the pool.
- **Significance:** one-sided permutation test (signal shuffled within day, 5,000 draws). Bootstrap 95% CI over days.
- **Families and correction (Holm):** family 1 = the 6 individual inputs; family 2 = A0, A1, A2, A3, M.
- **Algorithm choice:** the best of A1–A3 by discovery IC is the only candidate carried to the holdout. On the holdout it is compared with A0 (paired daily IC difference, bootstrap CI) and with M.

## Decision rule

| Outcome on the holdout | Conclusion |
|---|---|
| No individual input significant (Holm) and the minimum detectable IC is below 0.08 | **Data problem**: these Adanos signals do not anticipate next-day activity |
| At least one input significant, A0 not significant | **Algorithm problem**: the information exists but A0 loses it |
| Carried variant beats A0 (paired CI above 0) | The specific construction change (level vs change, no percentile, smoothing) is the fix |
| Nothing beats M | Adanos adds nothing beyond recent price activity, whatever its other merits |

## Sanity checks (must pass before results are read)

Oracle (signal = label) gives IC = 1; random signals over 200 seeds average IC ≈ 0; features never use data dated *t* or later.

## Amendments

None.
