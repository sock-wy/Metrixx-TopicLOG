# Topic Log archive

Append-only record of every Topic Log pull, written by `dashboard/archive.py` (branch `feat/dashboard`).
Nothing here is ever rewritten; backtests read it together with the backfill.

| Path | Written | Content |
|---|---|---|
| `YYYY/MM/DD/HHMM_kalshi_markets.json.gz` | every pull | every Kalshi market with volume or open interest: bid, ask, last, 24h volume, OI, topic |
| `YYYY/MM/DD/HHMM_kalshi_perps.json.gz` | every pull | Kalshi perpetual futures: price, OI, 24h volume; funding rates of the last 2 days |
| `YYYY/MM/DD/HHMM_polymarket.json.gz` | every pull | Polymarket finance events: volume, OI, prices |
| `YYYY/MM/DD/HHMM_us_movers.json.gz` | every pull | Yahoo gainers, losers, most active |
| `YYYY/MM/DD/HHMM_topic_log.json.gz` | every pull | the topic log as computed live (every input, w0 and w1 scores) |
| `YYYY/MM/DD/HHMM_events.json.gz` | every pull | every event with its topic |
| `YYYY/MM/DD/daily_*.json.gz` | first pull at/after 17:00 ET | US stocks (price, volume), crypto spot, earnings calendar |
| `adanos/YYYY-MM-DD.json.gz` | once per complete UTC day | Adanos buzz, mentions, sentiment for the whole universe, every platform |

Times in paths are US Eastern. Each file is `{"run_ts": ..., "rows": [...]}`.
