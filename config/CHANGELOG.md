# Changelog

Every change to a weight, threshold, tier rule or gate is recorded here.
Newest first. One change per week (see README, "Review loop").

Each entry records:

- **Version**: the new `weights_version` (matches `config/weights_wN.yaml`)
- **Date**: when it takes effect
- **Change**: parameter, old value → new value
- **Reason**: the evidence (override codes, weekly review finding, episode IDs)
- **Expected effect**: what should look different in next week's review

---

## p0 (perps.yaml) — 2026-10-13

- **Change**: new file `config/perps.yaml`: Topic Log ticker → Kalshi perp map and definitions of `perp_funding_rate`, `perp_funding_z` (30-day window, min 15 settlements, clip ±5) and `perp_oi_chg_pct` (24 h, hourly candles).
- **Reason**: WO-TOPICLOG-ALERTS-01 step 4 (D3) adds these three columns to `2_topic_log`. OIL and NATGAS have no active Kalshi perp and stay blank.
- **Expected effect**: perp columns filled daily for mapped tickers; not yet used in `demand_score`.

## w0 — 2026-09-29

- **Change**: initial draft. All values in `config/weights_w0.yaml` are starting points.
- **Reason**: no episode history yet.
- **Expected effect**: baseline for the first weekly review.

<!--
Template for the next entry (copy above the w0 entry):

## w1 — YYYY-MM-DD

- **Change**: `gates.G4_cooldown.window_days` 3 → 5
- **Reason**: SIMILAR_RECENT override used 3 times in 14 days
  (MYCAST-2026-10-02-01, MYCAST-2026-10-06-01, MYCAST-2026-10-09-01)
- **Expected effect**: fewer repeat index episodes; override rate should drop
-->
