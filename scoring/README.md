# scoring

**Status:** v0 — scoring and feature builder implemented; worked-example test passes

## Purpose

Turns the day's snapshots into one row per ticker in `2_topic_log`: applies the hard gates, computes each component's percentile, `demand_score`, tier and rank, exactly as defined in `playbook/README.md` sections 3–5.

## Inputs

`1_market_snapshots` (today and previous day, for deltas); active `config/weights_wN.yaml`.

## Outputs

`2_topic_log` rows including component percentiles, `demand_score`, `rank`, tier, `data_quality_flag` and `weights_version`.

## Depends on

`ingestion/` running continuously (deltas need an overnight history); `config/`.

## Contents

| File | Purpose |
|---|---|
| `scoring.py` | `score_day`: hard gates, percentiles, renormalised weights, quality, cooldown, tiers, rank. Reads every number from the config |
| `features.py` | Snapshot tables → one row per (day, ticker) of component inputs, as of the pick time, with a look-ahead guard |
| `tests/test_worked_example.py` | Reproduces the playbook worked example (NDX 0.584, NVDA 0.416, TSLA 0.349, AAPL 0.167, DJI 0.059) |

## Usage

```python
from scoring.scoring import load_config, score_day
cfg = load_config("config/weights_w0.yaml")
ranked, gated = score_day(rows, cfg)   # rows: one dict per ticker, see the scoring.py docstring
```

```bash
python -m pytest -q scoring/tests
```

Every output row carries `weights_version`.

---

Back to the [project README](../README.md).
