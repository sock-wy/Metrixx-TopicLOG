# Topic Log backfill, pulled 2026-10-22 (16:03–16:41 CT)

History for Topic Log backtests. All timestamps are UTC (`ts`). See CATALOG.md for row counts, time ranges and columns.

## kalshi/
- `events.parquet`: every event in Financials / Crypto / Commodities / Companies that settled after Kalshi's historical cutoff (2026-08-23) or is still open: 147,871 events, with total volume, open interest, results and the Topic Log `topic` / `asset_class` mapping. `selected` = events that have candles.
- `candles_1h.parquet`: hourly candles for 3,401 events (2.5M rows, 45,741 markets). Only markets that traded. For series with several events per day (hourly ladders), only the most traded event per series per ET day is kept; 15-minute series are skipped. Long-lived events are capped at the last 30 days of hourly bars. Fields: volume per hour, open interest, yes bid/ask close, last price close/high/low (dollars).
- Before 2026-08-23 Kalshi only serves settled events through its historical endpoints, which have no event-level candles. The repo's `backtest/snapshots/` covers crypto/indices for Aug–Oct.

## yahoo/
- `topics_1h.parquet`: hourly OHLCV for every Topic Log topic with a price symbol (212 symbols, about 2–3 years).
- `topics_1m.parquet`: 1-minute OHLCV, last ~28 days (215 symbols). Yahoo only serves 1m data for about 30 days.
- `topics_1d.parquet`: daily OHLCV, full history.
- `us_stocks_1d.parquet`: daily OHLCV + adjusted close for 6,629 of the 6,999 US-listed stocks in today's Nasdaq screener (2 years), with sector.

## binance/
- Top 50 USDT pairs by 24h quote volume (stablecoins excluded; includes Binance's tokenized stocks such as TSLAB, MSTRB).
- `klines_1h.parquet`: 2 years. `klines_1m.parquet`: last 30 days. Includes taker-buy volume (order-flow proxy).

## polymarket/
- `markets.parquet`: up to 5 most traded markets for each of ~800 active events in the finance, economy, stocks, earnings, fed-rates, commodities, ipos, business and crypto tags. `token` is the YES (first-outcome) token.
- `prices_1h.parquet`: hourly YES price, last 30 days (the API caps hourly history at about a month).
- `prices_1d.parquet`: daily YES price over each market's whole life.

## Not included
- Adanos (needs the API key; history is limited to 90 days on the hobby account, so pull it soon after the key is in).
- eToro, minute-level Kalshi (too large for one pass; easy to add for chosen series).

Scripts: `dashboard/backfill/` on branch `feat/dashboard` of sock-wy/Metrixx-TopicLOG.
