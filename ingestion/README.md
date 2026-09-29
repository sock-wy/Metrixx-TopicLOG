# ingestion

**Task:** Task 4  
**Status:** planned

## Purpose

Runs continuously on the VPS, pulls data from each source on a schedule, and writes raw rows to `1_market_snapshots`. Also answers how to access the running job and its output.

## Inputs

Adanos API (live), Kalshi public market data (verified 2026-09-16; indices only in the free tier), eToro (not yet evaluated).

## Outputs

Rows in `1_market_snapshots` every 15 minutes, each with `snapshot_ts`, `source`, `delay_label` and `raw_ref` pointing at the stored raw response.

## Depends on

VPS access; API credentials in `.env` (never committed).

## Contents

Planned layout:

```
ingestion/
├── adanos/        collector
├── kalshi/        collector
├── etoro/         collector (after evaluation)
├── scheduler      cron / systemd unit definitions
└── README.md
```

## Usage

To be written with the first collector. This section should cover: how to start and stop the job, where logs are, how to check the last successful pull, and how to read the snapshot store.

---

Back to the [project README](../README.md).
