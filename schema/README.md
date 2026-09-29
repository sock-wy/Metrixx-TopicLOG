# schema

**Task:** Shared  
**Status:** v0 draft (columns will change once eToro is integrated)

## Purpose

Defines the three Topic Log sheets and every column in them. Code, config and docs use these exact field names.

## Inputs

Source API fields (Adanos, Kalshi, eToro).

## Outputs

The column contract that `ingestion/`, `scoring/`, `alerts/` and `visuals/` read and write.

## Depends on

Nothing.

## Contents

| Sheet | Grain | Role |
|---|---|---|
| `1_market_snapshots` | one row per contract per pull (15 min) | Raw layer: quotes, volume, open interest, contract structure, lifecycle, provenance |
| `2_topic_log` | one row per ticker per day | Decision layer: rolled-up signals, `demand_score`, `rank`, flags |
| `3_episode_log` | one row per episode | Feedback layer: selection state, override, production, audience, outcome |

The schema workbook (`topic_log_schema_vN.xlsx`) and a `schema.md` field reference belong in this folder.

## Usage

**Pending column changes (from the playbook):**

- Sheet 2 add: `mkt_volume_delta_1d`, `mkt_oi_delta_1d`, `weights_version`, `catalyst`, `catalyst_date`
- Sheet 2 rename: `buzz_trend` → `buzz_trend_7d`
- Sheet 1: move from Excel to a database (about 40,000 rows a day at 15-minute cadence); keep Excel as a view

When a column changes, update the schema version and every module README that lists it.

---

Back to the [project README](../README.md).
