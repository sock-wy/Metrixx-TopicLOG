# Topic Log dashboard

**Status:** v2 · scoring w1 (default) · live on claude.ai (refreshed eight times a day) and as the desktop app `Topic Log.app` v0.3

## What it is for

Agenda item 1 (10/16): one place to see, every few hours, which market topics people are paying attention to and trading on, rank them for the day's MYCAST episode, and tune the ranking by hand. The pick of record is the first pull at or after 15:00 ET.

The page has three columns on the **Workbench** tab:

```
1 · IN  Data sources        2 · SCORE  Algorithm          3 · OUT  Output
switch each source on/off   weights, gates, quality,      your pick, the ranked table,
choose which topics compete tiers: all adjustable         one topic's breakdown, score vs momentum
```

Every change in columns 1 and 2 re-ranks column 3 at once, in the browser. Nothing you change is written back to the data; the stored ranks (`w0 #`, daily picks) stay as the pipeline computed them.

## The overall logic

```
every pull (cloud: every 3 h; desktop: your interval)
  1. collect      Kalshi · Polymarket · Adanos (Reddit, X, News) · prices (Yahoo, Binance → Coinbase → Kraken)
                  + supporting: Nasdaq stocks list, Nasdaq earnings, Yahoo movers
  2. topics       every item is put under a topic automatically (registry.py)
  3. inputs       per topic, each source fills its own columns (no source is counted twice)
  4. combine      the source columns become 7 components
  5. gates        G2 · G3 remove topics that cannot carry an episode
  6. score        within-pull percentile of each component → weighted mean (× quality if on)
  7. rank         by score (or by tier first, if tiers are set to rank)
```

### 2 · Topics

A **topic** is what an episode would be about (a stock, a coin, an index, the Fed, CPI, a private company…). An **event** is one market or item that belongs to a topic (a Kalshi event, a Polymarket event, a Yahoo mover). Assignment is automatic, in this order:

1. Kalshi rules in `symbols.py` (KPI, point-of-sale and app-download series roll up to the stock; Economics series to FED, CPI, JOBS, GDP, HOUSING…)
2. a ticker in the text (`$NVDA`, `(KO)`) or a known ticker symbol
3. a known name or alias (macro terms, indices, commodities, coins, private companies, the 1,500 largest US companies by name)
4. nothing matched → the item becomes a **new topic** of its own (marked `new`)

No manual mapping is needed. New topics are listed in **Topics & events** (filter "New only").

### 3 · Who supplies what (source of record)

| Component | Sources | Raw value |
|---|---|---|
| Money flow | Kalshi + Polymarket, weighted by each venue's 24h volume | Kalshi: 24h volume vs the pull 24h earlier. Polymarket: 24h volume vs its 1-week daily average |
| Money stock | Kalshi + Polymarket, weighted by open interest | open interest vs 24h earlier |
| Market move | Kalshi + Polymarket, weighted by volume | volume-weighted \|probability change\| over 24h, two-sided traded markets only |
| Attention | Adanos, platforms switched on | **w1:** mentions yesterday vs the topic's own mean over the 19 days before (log ratio, platforms summed). **w0:** 1-day buzz change |
| Activity | Adanos | **w1:** mentions over the last 3 days vs the 3 before. **w0:** 1-day mention change |
| Sentiment | Adanos | \|1-day sentiment change\| (weight 0 in w1) |
| Momentum | prices | \|24h price change\| ÷ the month's daily volatility |

Adanos uses complete UTC days only (yesterday and earlier). Crypto has Reddit only. Coinbase and Kraken supply prices for coins Binance does not list and the "On Coinbase / On Kraken" flags.

### 5 · Gates

| Gate | Rule | Default |
|---|---|---|
| G2 | topic needs prediction-market volume (Kalshi or Polymarket) in the last 24h | on ("prediction-market volume") |
| G3 | on the 3 Kalshi strikes nearest 50% of the topic's most traded event: share with no trade ≤ 80%, average bid-ask ≤ $0.30 | on |

G4 (cooldown after an episode) is defined in the playbook but inactive until there is an episode log.

### 6 · Score

`score = quality × Σ wᵢ · pctrank(xᵢ) / Σ wᵢ`. In w1 a component the topic lacks counts as 0.5 (the median); in w0 it is left out and the other weights are rescaled. `pctrank` is the topic's percentile among the topics that passed the gates this pull, so a score of 0.8 means "higher than about 80% of today's pool on the weighted inputs".

**Quality multiplier** (off in w1): `spread factor × zero-trade factor × source factor`. Spread factor = 1 up to the free spread, then falls by `(spread − free) / slope`, never below the floor. Zero-trade factor = 1 − penalty × zero-trade share. Source factor = 1 with both market and social data, else the single-source factor.

**Tiers**: T1 a catalyst (earnings, KPI market, CPI/FOMC) within N trading days and a strong move or flow; T2 strong flow and attention; T3 strong attention; T4 the rest.

### w0 and w1

| | w0 (playbook) | w1 (default, from the backtest) |
|---|---|---|
| Weights attention / activity / flow / OI / move / sentiment / momentum | .25 / .10 / .20 / .10 / .20 / .15 / 0 | .30 / .10 / .15 / .10 / .10 / 0 / .25 |
| Attention | 1-day buzz change | mentions vs 20-day normal |
| Activity | 1-day mention change | 3 days vs 3 before |
| Missing input | left out, weights rescaled | counts as the pool median (0.5) |
| Quality multiplier | on | off |
| Tiers | rank by tier first | labels only |

Why: study `broad_v2` (`backtest/broad_*.py`, results page `backtest/broad/results.html`). Over 41 trading days w0 and v2 as shipped ranked no better than chance; w1 beat them on the next session's price move and on next-day attention, tied momentum on price moves and beat it on attention. The pipeline stores both: `rank` / `demand_score` = w0, `w1_rank` / `w1_score` = w1. Daily picks use w1 from Oct 23 on.

## Every control

### Top of the page
- **Take line**: the latest pull time, your pick with the current settings, the stored w0 pick and the momentum pick.
- **Tabs**: Workbench · Daily picks · Daily steps · Raw data · Market data · Topics & events.

### 1 · Data sources (left)
- **Kalshi / Polymarket switch**: take that venue out of money flow, money stock and market move. With both off, G2 "prediction-market volume" removes every topic.
- **Adanos · Reddit / X / News chips**: which platforms feed attention, activity and sentiment.
- **Prices switch**: momentum on or off.
- **View** (on a card): opens that source's raw table in the Raw data tab.
- Status dot: green ok, amber partial / no key / empty, red error, for the latest pull.
- **Supporting sources**: Yahoo movers (adds topics), Nasdaq earnings (T1 catalysts), Nasdaq US stocks (tickers and names for matching), Binance · Coinbase · Kraken (coin list and prices). They are not scored directly.
- **eToro / Metrixx AI upload**: placeholders (eToro needs a key; Metrixx upload is agenda item 2).
- **Universe · Topic sources**: keep only topics that came from the chosen sources (Kalshi, Polymarket, Adanos trending, US movers). A topic with several sources stays while any of them is on.
- **Universe · Asset classes**: chips per class (equity, macro, crypto, theme, commodity, index, private, fx, rates); a chip switched off removes that class.
- **Inputs with data**: share of topics in this pull that have a value for each component.

### 2 · Algorithm (middle)
- **Reset to w1**: back to the default settings. **Load w0**: the playbook's original settings. **Export as YAML**: the current settings as a `weights_wN.yaml` draft to paste into `config/`.
- **Weights**: one slider per component; the bar under each shows its share of the total. **Attention measure** and **Activity measure** switch between the w1 and w0 constructions. **Missing input**: a topic without a value for a component either gets the pool median for it (w1) or has that component left out with the other weights rescaled (w0).
- **Hard gates**: G2 mode (prediction-market volume · any market or social activity · off); G3 maximum zero-trade share and maximum spread.
- **Quality multiplier**: on/off switch, then free spread, slope, floor, zero-trade penalty and single-source factor.
- **Priority tiers**: rank by tier first · labels only · off; then the T1 catalyst window and the percentile thresholds for T1–T3.

### 3 · Output (right)
- **Your pick / Pool / Top 10 shared with w0**: rank 1 with your settings; how many topics passed the gates and how many were gated; overlap with the stored w0 top 10.
- **Search** and **Show gated** (include gated topics, with the gate that removed them).
- **Table**: `#` your rank (▲▼ = places versus w0), `w0 #`, Topic (`new` = created this pull), Name, Class, From (K Kalshi · P Polymarket · A Adanos · M movers), Tier, Score, the seven component percentiles, Quality, Gate. Click a header to sort; click a row to open it below.
- **Topic breakdown**: score arithmetic, catalyst, each component's percentile and points added, the raw inputs from every source (Kalshi, Polymarket, Adanos per platform, price), the topic's w0 rank over the last 10 days and its most traded events.
- **Your score vs momentum**: every scored topic; right = higher score, up = larger abnormal price move.

### Other tabs
- **Daily picks**: the rank-1 pick of each day's 15:00 ET pull (chart) and the top 5 per day (table).
- **Daily steps**: one row per pull: when, how many topics scored and gated, status of each source, Adanos days on hand.
- **Raw data**: every collected source as a searchable, sortable table.
- **Market data**: price, 24h and 5-day change and abnormal move per priced topic (agenda item 2 will add the Metrixx upload here).
- **Topics & events**: tiles per asset class; every topic with its sources, how it was matched (rule, ticker, name, new) and its number of events; click a topic to filter the events table; every Kalshi series and the topic it rolls up to.

## Desktop app (`Topic Log.app`)

- **App bar**: last and next pull · **Pull every** (15 min, 30 min, 1 h, 3 h; changing it also pulls at once) · **Pull now** (fetch every source now, a few minutes) · **Refresh view** (reload the page from data already on the Mac) · **Adanos key…** (stored in `~/Library/Application Support/TopicLog/settings.json`, mode 600) · **Quit**.
- Data and history live in `~/Library/Application Support/TopicLog/data/`, separate from the cloud dashboard. Settings you change on the page are kept per Mac.
- First start after an update replaces the data with the pull shipped in the app, then pulls on schedule.
- Build: `SEED=<dir of a pull> ./desktop/build.sh [ADANOS_API_KEY]` → `desktop/dist/Topic Log.app`. Build without a key for anyone else; they can enter their own key in the app bar.

## Outputs (one JSON file per dataset)

| File | Rows |
|---|---|
| `topic_log.json` | one per topic, latest pull: source columns, components, w0 and w1 score / rank / tier, gates |
| `events.json` | every Kalshi event, Polymarket event and Yahoo mover with its topic |
| `score_history.json` | one per topic per pull, last 10 days (also the 24h-earlier baseline for flow and OI) |
| `daily_log.json` | the 15:00 ET pull of each day, last 45 days |
| `runs.json` | one per pull: status of each step |
| `adanos_daily.json` | Adanos cache: daily values and window totals per symbol and platform, last 10 days |
| `symbol_appendix.json` | every open Kalshi series → topic, price symbol, Adanos symbol |
| `market_data.json` | price, changes, abnormal move per priced topic |
| `us_stocks.json`, `earnings_calendar.json`, `us_movers.json`, `polymarket.json`, `crypto_spot.json` | raw supporting sources |

## Usage

```bash
python -m dashboard.pipeline --state STATE_DIR --out OUT_DIR --adanos-key "$ADANOS_API_KEY"   # or ADANOS_KEY in the environment
```

`STATE_DIR` holds the previous `score_history.json`, `daily_log.json`, `runs.json` and `adanos_daily.json` (any may be missing). The cloud scheduled task downloads them from the dashboard, runs this, uploads the 13 outputs and repoints the datasets. `page/index.html` is the page stored in the artifact and bundled in the app.

Files: `pipeline.py` (steps 1–7, w1 ranking), `registry.py` (automatic topics), `symbols.py` (Kalshi rules, aliases, topic metadata), `sources.py` (free sources), `catalysts.yaml` (CPI/FOMC dates), `backfill/` (history pulls for backtests).

## Known limits

- Money flow and OI change need a pull from about 24h earlier; after a fresh start they are empty for a day.
- Polymarket enters through 24h volume, open interest and price moves; its volume history is not stored, so its flow is measured against its own 1-week average.
- G4 cooldown is inactive until an episode log exists.
- The backtest covers 41 trading days; re-run `backtest/broad_features.py` and `backtest/broad_eval.py` after a new backfill before changing weights again.

---

Back to the [project README](../README.md).
