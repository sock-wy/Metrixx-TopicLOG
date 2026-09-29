# scoring

**Task:** Task 6  
**Status:** planned

## Purpose

Turns the day's snapshots into one row per ticker in `2_topic_log`: applies the hard gates, computes each component's percentile, `demand_score`, tier and rank, exactly as defined in `playbook/README.md` sections 3–5.

## Inputs

`1_market_snapshots` (today and previous day, for deltas); active `config/weights_wN.yaml`.

## Outputs

`2_topic_log` rows including component percentiles, `demand_score`, `rank`, tier, `data_quality_flag` and `weights_version`.

## Depends on

`ingestion/` running continuously (deltas need an overnight history); `config/`.

## Contents

Planned: a scoring module, a daily job entry point, and tests that reproduce the worked example in `playbook/README.md` section 6 (NDX 0.584, NVDA 0.416, TSLA 0.349, AAPL 0.167, DJI 0.059).

## Usage

To be written. Rule: every number comes from the config file; the output row must carry the config `version` it used.

---

Back to the [project README](../README.md).
