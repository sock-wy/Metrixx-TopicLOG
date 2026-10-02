# ingestion

**Status:** v0 — backfill for Kalshi, Adanos, Yahoo; live snapshot command ready for cron

## Purpose

Runs continuously on the VPS, pulls data from each source on a schedule, and writes raw rows to `1_market_snapshots`. Also answers how to access the running job and its output.

## Inputs

Kalshi public market data (no key), Adanos API (`ADANOS_API_KEY`), Yahoo Finance daily closes (no key). eToro not yet evaluated.

## Outputs

Raw API responses, stored whole (every field kept), under `ingestion/data/raw/<source>/` (git-ignored).

## Depends on

Network access; `ADANOS_API_KEY` in a local `.env` (copy `.env.example`). Never commit `.env`.

## Contents

| File | Purpose |
|---|---|
| `common.py` | Paths, `.env` loading, HTTP with retry, ET/UTC conversion (DST-safe) |
| `kalshi.py` | Event candlesticks (whole ladder), event markets (settlement value), live open-market snapshot |
| `adanos.py` | Per-token / per-ticker detail with `daily_trend`, quota tracking |
| `yahoo.py` | Daily closes (used only to scale backtest labels) |
| `pull.py` | Entry point: `kalshi`, `adanos`, `yahoo` backfills and the live `snapshot` |

## Usage

All commands are idempotent: responses are cached, re-runs only fetch what is missing.

```bash
python -m ingestion.pull kalshi --universe backtest/universes/crypto_indices.yaml --start 2026-08-03 --end 2026-10-01
python -m ingestion.pull adanos --universe backtest/universes/crypto_indices.yaml --start 2026-07-20 --end 2026-10-01
python -m ingestion.pull yahoo  --universe backtest/universes/crypto_indices.yaml
python -m ingestion.pull snapshot --universe backtest/universes/crypto_indices.yaml   # live, for cron
```

On the VPS, schedule `snapshot` four times a day at the pick-anchored times (15:00, 21:00, 03:00, 09:00 ET), e.g.

```cron
CRON_TZ=America/New_York
0 15,21,3,9 * * *  cd ~/Metrixx-TopicLOG && .venv/bin/python -m ingestion.pull snapshot --universe backtest/universes/crypto_indices.yaml >> logs/pull.log 2>&1
```

**Known source issues:** Kalshi moves events settled before its historical cutoff (2026-08-02 at the time of writing) to `/historical/*`, which does not serve event-level candles. One Kalshi settlement value was malformed at source (`KXDJI-26SEP1015`, `expiration_value = "No"`); malformed values are treated as missing, never guessed.

---

Back to the [project README](../README.md).
