# ingestion

**Status:** v0 — backfill for Kalshi, Adanos, Binance, Yahoo; live snapshot command ready for cron

## Purpose

Runs continuously on the VPS, pulls data from each source on a schedule, and writes raw rows to `1_market_snapshots`. Also answers how to access the running job and its output.

## Inputs

Kalshi public market data (no key), Adanos API (`ADANOS_API_KEY`), Binance public market data (no key), Yahoo Finance daily closes (no key). eToro not yet evaluated.

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
| `binance.py` | Spot daily klines from `data-api.binance.vision` (crypto prices; `api.binance.com` refuses some regions) |
| `yahoo.py` | Daily closes (used to scale `crypto_indices` labels) |
| `pull.py` | Entry point: `kalshi`, `adanos`, `yahoo` backfills and the live `snapshot` |

## Usage

All commands are idempotent: responses are cached, re-runs only fetch what is missing.

```bash
python -m ingestion.pull kalshi --universe backtest/universes/crypto_indices.yaml --start 2026-08-03 --end 2026-10-01
python -m ingestion.pull adanos --universe backtest/universes/crypto_indices.yaml --start 2026-07-20 --end 2026-10-01
python -m ingestion.pull yahoo  --universe backtest/universes/crypto_indices.yaml
python -m ingestion.pull snapshot --universe backtest/universes/crypto_indices.yaml   # live, for cron
```

On the VPS, schedule the Kalshi `snapshot` eight times a day, every three hours anchored on the 15:00 ET pick (15, 18, 21, 00, 03, 06, 09, 12 ET). Adanos data is daily, so it is pulled once a day after 00:00 UTC (one `/compare` request covers every token):

```cron
CRON_TZ=America/New_York
0 0,3,6,9,12,15,18,21 * * *  cd ~/Metrixx-TopicLOG && .venv/bin/python -m ingestion.pull snapshot --universe backtest/universes/crypto_indices.yaml >> logs/pull.log 2>&1
```

**Account limits:** the current Adanos key is a hobby account: 250,000 requests a month, at most 90 days of lookback per request. Data older than 90 days is only available if it was stored when it was fresh, which is another reason to run the collector continuously.

**Known source issues:** Kalshi moves events settled before its historical cutoff (2026-08-02 at the time of writing) to `/historical/*`, which does not serve event-level candles. One Kalshi settlement value was malformed at source (`KXDJI-26SEP1015`, `expiration_value = "No"`); malformed values are treated as missing, never guessed.

---

Back to the [project README](../README.md).
