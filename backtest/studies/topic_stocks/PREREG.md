# Pre-registration — study `topic_stocks`

Written 2026-10-11T12:40Z, before any data for this study was pulled. Nothing below changes after
results are seen; later additions go under "Amendments" and are reported as exploratory.

## Question

Does a four-dimension topic score (event, attention, disagreement, money) pick the stocks that stay
talked about after the pick, and better than simple alternatives? Which dimensions carry the result?
Does Kalshi data add anything on the names where it exists?

## Calendar

| Period | Dates | Use |
|---|---|---|
| Formation | 2026-07-14 → 2026-08-12 | universe selection, warm-up of baselines; never evaluated |
| Evaluation | US trading days 2026-08-13 → 2026-10-07 (39 days) | one simulated pick per day at 15:00 ET |
| Discovery | 2026-08-13 → 2026-09-10 (20 days) | choose one algorithm version |
| Holdout | 2026-09-11 → 2026-10-07 (19 days) | confirm once |

The evaluation ends 2026-10-07 because the primary label needs three complete UTC days after the pick
and the Adanos history ends 2026-10-10 (90-day lookback limit of the account).

## Universe (fixed from the formation period only)

- **Main (option 2):** the 100 US-listed common stocks with the most mentions summed over Adanos X,
  Reddit and News in the formation period (candidates: each platform's top 300 trending list for
  that period), plus SPY and QQQ as index proxies. A name needs a Yahoo instrument type `EQUITY` (or
  is SPY/QQQ) and complete daily prices over the whole calendar.
- **Kalshi subset (option 1):** universe names with an active Kalshi Financials market in the
  calendar (company KPI, consumer-data, M&A, product or CEO markets; S&P 500 and Nasdaq-100 ladders
  for SPY and QQQ).

## Timing (no look-ahead)

Pick time is 15:00 ET on day *t*. Adanos counts by UTC day; day *t* is still open at 15:00 ET, so
Adanos inputs use complete UTC days up to *t*−1. Prices use the last complete session (*t*−1) and the
hourly bar that closes at 14:30 ET on *t*. Kalshi inputs use hourly candles that closed by 15:00 ET.
Every feature row records the latest timestamp it used; the run asserts it is before the pick.

## Field transforms (three versions)

Counts (mentions, trades) are taken as log(1+x). Baseline μ, σ: the field's own values on days
*t*−31 … *t*−4 (at least 15 values), so the last three days cannot be absorbed into the baseline.

| Version | Transform |
|---|---|
| **V0** single-day change (w0 style, control) | s = x(t−1) − x(t−2), divided by the baseline σ of daily changes |
| **V1** EWMA | e = Σₖ wₖ·x(t−k), k = 1…10, wₖ ∝ 0.5^((k−1)/1.5); s = (e − μ)/σ |
| **V2** dual max | z1 = (x(t−1) − μ)/σ; z3 = (mean x(t−1…t−3) − μ)/(σ/√3); s = max(z1, z3) |

All s are clipped to ±5. Price fields are already abnormality measures and are used as defined below
in every version.

## Dimensions and fields

| Dimension | Fields (main universe) | Added on the Kalshi subset |
|---|---|---|
| **E event** | E1 momentum: ln(H/L) of session *t*−1 ÷ mean of the previous 20 sessions, as a z-score against those 20; E2 today so far: \|ln(P(14:30 ET, t)/Close(t−1))\| ÷ 20-session σ of daily log returns | E3 Kalshi move: largest \|Δ mid\| over the last 24 h among the name's open markets |
| **A attention** | A1 X mentions, A2 Reddit mentions, A3 News mentions (version transform) | — |
| **D disagreement** | D1 bull/bear balance 1 − \|bull − bear\|/(bull + bear) on Reddit and X (averaged, version transform); D2 sentiment deviation \|sentiment − μ\|/σ (Reddit and X averaged, either direction); D3 Polymarket bull/bear balance (version transform) | D4 Kalshi split: 1 − 2·\|mid − 0.5\| of the most-traded open market (companies); implied-distribution width (strike distance between 25% and 75% above-probability ÷ price) for the S&P 500 / Nasdaq-100 ladders |
| **M money** | M1 Polymarket trade count (version transform) | M2 Kalshi volume in the last 24 h across the name's open markets |

Kalshi fields are standardised against the pooled values of all subset names on earlier days
(past-only), because most companies have markets open on only a few days.

Combination: dimension score = mean of its available fields; total = mean of the available dimension
scores (equal weights). Missing fields and dimensions are skipped, never zero-filled. The pick is the
highest total. No post-score filters (freshness, producibility, timeliness, audience fit) in this study.

## Labels (all measured after the pick)

| Label | Definition | Role |
|---|---|---|
| **L_A attention persistence** | mean over UTC days *t*+1, *t*+2, *t*+3 of the mean over X, Reddit, News of z(log(1+mentions)), with the same baseline as the features | **primary** |
| L_E event | ln(H/L) of session *t*+1 ÷ mean of the previous 20 sessions | secondary |
| L composite | average of the within-day percentile ranks of L_A and L_E | reported |

## Benchmarks

Random; momentum (E1 alone); most-discussed (log total mentions on *t*−1, level not abnormality);
attention only (A score of the same version); V0 as the w0-style control.

## Metrics

- Daily Spearman IC of score vs label over the pool; mean over days.
- Pick percentile of the top-scored name in the day's label distribution (random = 0.5).
- Top-3 hit: at least one of the three top-scored names is among the label's top 10 (random ≈ 0.27 for 102 names).
- Significance: one-sided permutation within day (5,000 draws); bootstrap 95% CI over days.
- Holm correction within families: (a) V0/V1/V2 on discovery; (b) the four ablations; (c) the four single-dimension scores.

## Dimension records (what each dimension did)

Every run writes, per pick and per version: each dimension's score, its share of the total
(|dimension| ÷ Σ|dimensions|), and the dimension that contributed most; the rank the pick would have
without each dimension. Per run: each dimension's standalone IC on each label, the IC change when it is
removed (ablation, with CI), its coverage, the correlation matrix of the four dimensions, and how often
each dimension led the daily pick. The same per field.

## Decisions

| Hypothesis (holdout, primary label) | Accepted if |
|---|---|
| H1 the carried version (best of V1/V2 on discovery) has IC > 0 | permutation p < 0.05 |
| H2 four dimensions beat attention alone | paired daily IC difference, 95% CI above 0 |
| H3 it beats most-discussed and momentum | paired CI above 0 for each |
| H4 Kalshi adds information on the subset | with-Kalshi minus without-Kalshi paired CI above 0 |
| Per dimension | ablation ΔIC CI excludes 0 → the dimension matters |

Attention persists by nature, so the primary label favours the attention dimension; H2 and H3 are the
tests that matter for "does multi-dimensional scoring add anything".

## Sanity checks (must pass before results are read)

Oracle score = label gives IC = 1; random scores over 200 seeds give IC ≈ 0; no feature uses data
dated at or after the pick.

## Not in this study

Post-score filters (dimensions 5–8); per-day Adanos aggregates (`unique_posts`, `subreddit_count`);
intraday Adanos data (needs the VPS collector); social-versus-market divergence (no clean market
direction for KPI markets).

## Amendments

None.
