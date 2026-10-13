# workbook

**Task:** WO-TOPICLOG-ALERTS-01 (Jim, Oct 1 2026), deliverables D2 and D3
**Status:** v0: header-safe writer + Kalshi perps columns. The full daily Sheet 1 / Sheet 2 writer is next.

## Purpose

Writes Topic Log data into Jim's merged Excel workbook (`TOPICLOG_MERGED_v0_x`), which holds the
three schema tabs plus UPLOAD, SETTINGS, RANK, BOARD and CLAUDE_INSIDE. The workbook's formulas
and macro read what this module writes, so two rules from the WO are enforced in code:

1. **Columns are found by header name, never by position.** Jim's v0.4 added three columns at
   AH–AJ; any future insert or reorder is harmless.
2. **Each ticker's rows stay in date order.** RANK treats a ticker's last row as its latest, so a
   row older than the ticker's latest is refused instead of appended.

## Inputs

- The workbook (`.xlsx` or `.xlsm`); tab `2_topic_log` with a header row containing `date` and `ticker`
  (found automatically in the first 10 rows).
- Kalshi perps API (public, no key), via `ingestion/kalshi_perps.py`.
- `config/perps.yaml`: ticker → perp map and field definitions.

## Outputs

On `2_topic_log`, for each (ticker, date):

| Column | Meaning |
|---|---|
| `perp_funding_rate` | Latest settled funding rate at or before the as-of time, fraction per period. Crypto settles 3×/day, metals 1×/day. |
| `perp_funding_z` | That rate's z-score against the previous 30 days of settlements (clipped ±5). Blank if fewer than 15 settlements or no variation. |
| `perp_oi_chg_pct` | Open interest at the last closed hour vs 24 h earlier, minus 1. |

Tickers without an active Kalshi perp (OIL, NATGAS, NDX on 2026-10-13) get blank cells, never zeros.

## Depends on

`ingestion/kalshi_perps.py`, `scoring/perp_fields.py`, `config/perps.yaml`, openpyxl.

## Contents

| File | Role |
|---|---|
| `sheet.py` | `Sheet`: find header, find/append/update rows by (ticker, date), date-order guard; refuses a file open in Excel; keeps VBA in `.xlsm`. |
| `fill_perps.py` | CLI that fills the three perp columns. |
| `tests/` | Header shift, ordering guard, lock file, funding z, OI change, end-to-end fill with a fake API. |

## Usage

```bash
# close the workbook in Excel first; a .bak copy is written before each save
python -m workbook.fill_perps --workbook TOPICLOG_MERGED_v0_5.xlsm --date 2026-10-13 \
    --asof 2026-10-13T19:00:00Z          # 15:00 ET pick time; nothing later is used
python -m workbook.fill_perps --workbook ... --tickers GOLD SILVER --create   # add rows that don't exist yet
python -m workbook.fill_perps --workbook ... --dry-run                        # print, don't write
```

## Notes from the first live pull (2026-10-13)

- Kalshi's funding has a deadband: rates inside it are paid as exactly 0. Over the last 30 days
  40% of gold, 60% of silver, 38% of BTC and 82% of ETH settlements were 0. `perp_funding_z` is
  therefore a coarse signal; `perp_oi_chg_pct` moves more.
- The S&P 500 perp (KXUS500PERP) started trading on 2026-10-06, so its z-score stays blank until it
  has 15 settlements.
- openpyxl rewrites the file on save. Formulas are kept and Excel recalculates them on open, but test
  the first write on a copy of Jim's workbook and check RANK, BOARD and the macro still work.

---

Back to the [project README](../README.md).
