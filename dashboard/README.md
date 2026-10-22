# dashboard

**Status:** v0 — live on claude.ai, refreshed by a scheduled task eight times a day

## Purpose

Agenda item 1 (10/16): a password-protected dashboard of the daily Topic Log. Every pull ranks every topic that has an open Kalshi market in Financials, Crypto, Commodities or Companies, using the playbook gates and `demand_score` (w0), with momentum reported next to it as the benchmark. It also holds placeholders for agenda items 2 (Metrixx market-data upload) and 3 (symbol appendix).

The dashboard is a private claude.ai artifact; access is controlled by who it is shared with.

## Inputs

| Source | What | Cadence |
|---|---|---|
| Kalshi public API | every open market in the four categories (~17,000 markets, ~260 topics) | every pull |
| Adanos `/reddit/{stocks,crypto}/v1/compare` | buzz, mentions, sentiment per mapped symbol, complete UTC days t−1 and t−2 | once per UTC day (cached) |
| Yahoo Finance spark | hourly prices, 1 month, for every topic with a listed symbol | every pull |
| `config/weights_w0.yaml` + `scoring/scoring.py` | gates, weights, tiers | unchanged |
| `dashboard/catalysts.yaml` | macro calendar for T1 (copy of `backtest/catalysts/macro_2026.yaml`, extended to December, applied to index, rates and FX) | manual |

## Outputs

Seven JSON files, each one dataset on the dashboard:

| File | Rows |
|---|---|
| `topic_log.json` | one per topic, latest pull (Sheet 2 for this pull) |
| `score_history.json` | one per topic per pull, last 10 days; also the 24h-earlier baseline for volume and OI deltas |
| `daily_log.json` | the 15:00 ET pull of each day, last 45 days |
| `runs.json` | one per pull: status of each step |
| `adanos_daily.json` | Adanos metrics per symbol per UTC day, last 21 days |
| `symbol_appendix.json` | every open Kalshi series → topic, price symbol, Adanos symbol |
| `market_data.json` | price, 24h / 5d change, abnormal move per priced topic |

## Raw data (free sources, not scored yet)

`sources.py` pulls these on every run. They appear under the dashboard's Raw data tab and in the left-hand source panel, and do not change `demand_score`.

| Dataset | Source | Rows (10/22) |
|---|---|---|
| `us_stocks.json` | Nasdaq screener: every US-listed stock, price, change, volume, market cap, sector | ~7,000 |
| `earnings_calendar.json` | Nasdaq earnings calendar, next 10 weekdays, EPS forecast | ~2,000 |
| `us_movers.json` | Yahoo screeners: top 100 gainers, losers, most active | 300 |
| `polymarket.json` | Polymarket gamma API: active events tagged finance, economy, stocks, earnings, fed-rates, commodities, ipos, business, crypto (top 200 per tag by 24h volume) | ~800 |
| `crypto_spot.json` | Binance (`data-api.binance.vision`) 24h stats per USDT pair, flagged if Coinbase lists the coin against USD | ~700 |

Not reachable without a key: eToro, Alpha Vantage, Finnhub, Polygon, FMP. Not reachable from the cloud environment: Stooq, FRED, CBOE, `api.binance.com`.

## How a topic is built

- **Topic** = what an episode would be about. `symbols.py` maps each Kalshi series to one topic: crypto tokens, indices, commodities, FX pairs, Treasury tenors, listed companies (all KPI, credit-card, foot-traffic, point-of-sale and app-download series roll up to the stock), private companies (Anthropic, OpenAI, SpaceX…) and a few themes. Unmapped series fall back to their own ticker and are flagged in the appendix.
- **G2** any open market with 24h volume. **G3** on the 3 two-sided strikes nearest 50% of the topic's most-traded event (playbook v2 / proposed w1). **G5** markets outside 0.01–0.99 are ignored.
- **money_flow / money_stock**: % change of the topic's total 24h volume / open interest against the stored pull nearest to 24h earlier (±3.5h). Empty until a day of pulls exists. The v2 volume floor applies once 10 daily rows exist.
- **market_move**: volume-weighted |mid − mid 24h ago| over traded, two-sided markets that existed 24h ago, preferring markets that close more than 24h out (short-dated ladders drift to 0/1 as expiry nears). `mkt_prob_range_1d` is not computed yet.
- **Adanos**: day t−1 vs t−2 (complete UTC days only, as in the playbook). Unsupported symbols are missing, not zero.
- **Catalyst** (T1): macro calendar for index/rates/FX; for companies, a KPI market with volume that resolves within 2 trading days.
- **days_since_covered**: not filled until the episode log exists, so G4 and the cooldown multiplier are inactive.
- **Momentum** (benchmark, not in the score): |24h price change| / the month's daily volatility, as a percentile within the surviving pool.

## Usage

```bash
python -m dashboard.pipeline --state STATE_DIR --out OUT_DIR --adanos-key "$ADANOS_API_KEY"
```

`STATE_DIR` holds the previous run's `score_history.json`, `daily_log.json`, `runs.json` and `adanos_daily.json` (any may be missing). The scheduled task downloads them from the dashboard, runs this, uploads the seven outputs and repoints the datasets. `page/index.html` is the dashboard page as stored in the artifact.

---

Back to the [project README](../README.md).
