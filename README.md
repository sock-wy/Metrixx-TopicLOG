# Metrixx Topic Log

The Topic Log decides which ticker each daily MYCAST episode covers, and records enough history to check whether that choice was any good. This repo holds the playbook that defines the procedure, and the configuration that holds every tunable number.

| File | What it is |
|---|---|
| [`index.html`](index.html) | The playbook as a website: the full procedure plus an interactive worked example. Open it in a browser, or enable GitHub Pages. |
| [`config/weights_w0.yaml`](config/weights_w0.yaml) | Every gate threshold, weight, multiplier and tier rule. The single source of truth for scoring. |
| [`CHANGELOG.md`](CHANGELOG.md) | One entry per change to the config, with the reason and the evidence. |
| `README.md` | This file: the playbook explained in full. |

> **Status: v0 draft.** All thresholds and weights are starting values, to be tuned through the review loop. Numbers in the worked example are illustrative, not live data.

---

## Contents

1. [The Topic Log](#1-the-topic-log)
2. [The Daily Run](#2-the-daily-run)
3. [Hard Gates](#3-hard-gates)
4. [demand_score](#4-demand_score)
5. [Priority Tiers](#5-priority-tiers)
6. [Worked Example](#6-worked-example)
7. [Angle Mapping](#7-angle-mapping)
8. [Overrides](#8-overrides)
9. [Review Loop](#9-review-loop)
10. [Using the config and changelog](#10-using-the-config-and-changelog)
11. [Source Coverage and Open Items](#11-source-coverage-and-open-items)
12. [Glossary](#12-glossary)

**The logic in four moves:** *Gate* (remove rows that cannot be trusted) → *Score* (turn today's changes into one number) → *Tier* (pick from the highest group that has anyone in it) → *Close* (decide the angle, then review whether the pick was right).

---

## 1. The Topic Log

Three sheets, one for each stage data passes through.

| Sheet | Grain | Role |
|---|---|---|
| `1_market_snapshots` | one row per contract per pull (every 15 min) | **Raw layer.** Is this quote a usable price? |
| `2_topic_log` | one row per ticker per day | **Decision layer.** Signals rolled up per ticker, ending in `demand_score` and `rank`. |
| `3_episode_log` | one row per published episode | **Feedback layer.** The call at the time, whether the editor agreed, whether it was producible, how the audience responded, how the market resolved. |

**Why keep the raw layer.** Some Sheet 2 fields can only be computed from it: `mkt_prob_range_1d` (the intraday high-to-low swing) and the day-over-day change in volume and open interest. Store only a daily summary and that information is lost. The raw layer also lets derived fields be recomputed after a schema change.

**Why the feedback layer.** Sheet 3 is what tunes Sheet 2's weights (Chapter 9).

**Reading rule.** An implied probability is never read alone. Read it with:

- **Spread**: the error bar. A 0.15 spread means "62%" is really somewhere between 55% and 70%.
- **Volume**: whether anyone traded. A zero-volume contract still shows a quote but carries no information. In the sample, 325 of 420 open contracts had zero volume.
- **Contract type**: what the number means. 0.62 is "finishes up" in an `up_down`, "finishes above a strike" in an `above_below`, "touches a level" in a `hit_target`. They cannot be added or compared directly.

Chapter 3's gates check spread and volume; Chapter 7's angle mapping relies on contract type.

---

## 2. The Daily Run

Six steps in a fixed order. Each step depends on the one before it, and a repeatable routine is what makes days comparable in the review loop. Times are proposed, US Eastern, and assume the VPS snapshot job ran overnight.

| Step | Time (ET) | What happens | Writes to |
|---|---|---|---|
| 1 · Pull | 06:30 | Latest Adanos and Kalshi snapshots land. Settled contracts are dropped. | `1_market_snapshots` |
| 2 · Gate | 07:00 | Candidates failing any hard gate are removed; the gate is recorded. | `2_topic_log.data_quality_flag` |
| 3 · Score | 07:00 | Compute `demand_score` and assign a tier to each surviving ticker. | `2_topic_log.demand_score`, `rank` |
| 4 · Pick | 07:15 | Editor takes the top of the highest non-empty tier, or overrides with a reason code. | `3_episode_log.selection_mode` |
| 5 · Angle | 07:20 | Read the angle off the contract structure; confirm material exists. | `3_episode_log.angle` |
| 6 · Close | +7 days | Fill audience metrics, editor rating and market resolution. | `3_episode_log.views_7d` … |

**Why this order**

- **Gate before Score.** Scores are percentiles within the pool. A broken row left in the pool would shift everyone else's percentile.
- **Score and Tier together.** Tiers use the same percentiles as the score.
- **Pick before Angle.** The angle is read off the chosen ticker's contracts.
- **Close at +7 days.** Audience numbers need about a week to settle; some markets take that long to resolve.

**Dependency.** Step 1 only works if the VPS snapshot job runs continuously. Without an overnight history there are no day-over-day deltas, so `money_flow` and `money_stock` cannot be computed.

---

## 3. Hard Gates

Fail any one gate and the ticker is out for the day. Gates answer "can this row be trusted at all", a different question from "how interesting is it".

**Why gates instead of penalties.** A score is compensatory: strength in one component can offset weakness in another. That is fine for interest but not for trust. A ticker with huge buzz and no live market should not be rescued by its buzz. The failed gate is written to `data_quality_flag`.

| Gate | Test | Rationale |
|---|---|---|
| G1 Freshness | `now − as_of ≤ 24h` | Stale rows rank yesterday's news. |
| G2 Market evidence | ≥ 1 open contract with `volume_24h > 0` | Buzz alone is talk; MYCAST's story is what the market is pricing. |
| G3 Liquidity floor | `zero_trade_market_pct ≤ 0.80` and `avg_spread ≤ 0.30` | Beyond these, the implied probability is mostly noise. |
| G4 Cooldown | `days_since_covered > N`, N = 3 | Stops one name dominating the feed. Just past the window: scored at 0.85×. |
| G5 Not settled | `status = open`, `0.01 ≤ p ≤ 0.99` | A quote at 0.0005 or 0.9995 is an answer, not a forecast. Removed in step 1. |

**About the thresholds.** They are set to reject only clearly broken rows. For reference, the Adanos AAPL sample had zero-trade 0.506 and average spread 0.151; the Kalshi sample averaged a 0.17 spread. If gates reject too much or too little in practice, the `DATA_SUSPECT` override code will reveal it.

---

## 4. demand_score

One number per ticker, built from **what changed today**. A name that is always hot is not today's news; a name that just got hot is.

```
demand_score = quality × cooldown × Σ wᵢ · pctrank(xᵢ) / Σ wᵢ

quality      = spread_f × zero_trade_f × source_f
spread_f     = clamp(1 − max(0, avg_spread − 0.05) / 0.5, 0.6, 1)
zero_trade_f = 1 − 0.4 × zero_trade_market_pct
source_f     = 1.0 if sources_available ≥ 2 else 0.9
cooldown     = 0.85 if N < days_since_covered ≤ N + 4 else 1.0
```

**Term by term**

1. `pctrank(xᵢ)` converts each raw input to its percentile among today's surviving tickers (0 = lowest, 1 = highest).
2. `Σ wᵢ · pctrank / Σ wᵢ` is a weighted average. Dividing by the weight sum means weights need not add to 1, and missing components drop out cleanly.
3. `quality` discounts rows whose data is weaker but still passed the gates.
4. `cooldown` softly penalises names covered just outside the gate window.

**Why percentiles**

- **No common unit.** Buzz points, contract counts and probabilities cannot be added.
- **Robust to outliers.** A 1,000% volume spike on a tiny base counts as "highest", not 50× more important.
- **Relative to today.** MYCAST publishes every day, so the question is "which is best today". On a quiet day, the best of a quiet pool still wins.

**Components (w0)**

| Component | Raw input | w0 | Captures |
|---|---|---|---|
| `attention_shift` | `buzz_delta_1d` | 0.25 | A name that just got hot. Highest weight: change in attention is the core "today's news" signal. |
| `activity_shift` | trade count Δ% 1d | 0.10 | More people trading, not only talking. Lower weight: overlaps with attention. |
| `money_flow` | `mkt_volume_24h` Δ% 1d | 0.20 | New money arriving today. Betting has a cost, so it is more credible than talk. |
| `money_stock` | `mkt_open_interest` Δ% 1d | 0.10 | Positions held overnight. Kalshi only for now. |
| `market_move` | `max(|prob Δ1d|, range_1d / 2)` | 0.20 | The market changed its mind. The range term catches a swing that ended flat. |
| `sentiment_shift` | `|sentiment Δ1d|` | 0.15 | Opinion moved, either way. Absolute value on purpose. |

Split: 35% attention, 30% money, 20% market move, 15% sentiment.

**Why direction is excluded.** A sharp bearish turn is as newsworthy as a bullish one. Rewarding positive sentiment would bias MYCAST toward good news. Direction belongs to the angle (Chapter 7).

**Missing data: renormalise, never zero.** Single stocks have no Kalshi data, so `money_stock` is missing. Counting it as zero would punish a ticker for a gap in our coverage. Instead it is dropped and weights renormalised. Example (AAPL, Chapter 6): available weights 0.90; weighted percentiles 0.25×0 + 0.10×0 + 0.20×0.25 + 0.20×0.50 + 0.15×0.75 = 0.2625; raw score 0.2625 / 0.90 = **0.292**. The single-source cost is charged once, openly, via `source_f = 0.9`.

**Quality multiplier, worked**

| Ticker | avg_spread | spread_f | zero_trade | zero_trade_f | source_f | quality |
|---|---|---|---|---|---|---|
| NDX | 0.09 | 0.920 | 0.35 | 0.860 | 1.0 | **0.791** |
| AAPL | 0.151 | 0.798 | 0.506 | 0.798 | 0.9 | **0.573** |
| TSLA | 0.19 | 0.720 | 0.48 | 0.808 | 0.9 | **0.524** |

Spreads up to 0.05 are free; each point beyond costs 2%; floor 0.6. An all-zero-trade pool keeps 60% (G3 removes the extremes). The factors multiply because they are independent weaknesses.

---

## 5. Priority Tiers

Pick from the highest tier that has anyone in it, then order by `demand_score` within that tier.

**Why tiers on top of a score.** The score is compensatory. Tiers lock in the one ordering that must not be traded away by weights: an event with money behind it beats attention alone. The ranking is lexicographic: tier first, then score.

| Tier | Condition | Meaning |
|---|---|---|
| **T1** | catalyst within 2 trading days AND (`market_move ≥ p70` OR `money_flow ≥ p70`) | Event with money behind it: a reason, a date and a number that moved. |
| **T2** | `money_flow ≥ p70` AND `attention_shift ≥ p50` | Money moving, attention following. |
| **T3** | `attention_shift ≥ p80` | Attention only. Fine for a direction story, weak for a market story. |
| **T4** | everything else | Baseline. Ranked by score alone. |

**Reading "p70".** Percentile ≥ 0.70 within today's pool. With five survivors, possible percentiles are 0, 0.25, 0.50, 0.75, 1.00, so p70 means "second-highest or better".

**Tie-breakers, in order**

1. More `sources_available`: two confirming sources beat one.
2. Higher `unique_traders`: guards against a few accounts manufacturing heat.
3. Deeper `mkt_ladder_depth`: more strikes, more angles.
4. Asset class not covered in the last two episodes.

T1 requires new `catalyst` and `catalyst_date` columns in Sheet 2, filled by hand until an event calendar is connected.

---

## 6. Worked Example

Chapters 3–5 applied to eight sample tickers, w0 weights, N = 3. **Illustrative numbers.**

**Step A — gates remove three**

| Ticker | Gate | Why |
|---|---|---|
| SPX | G4 | Covered 2 days ago, inside the window, despite excellent data. |
| MSFT | G3 | `zero_trade_market_pct` 0.82 > 0.80. |
| AMZN | G2 | Buzz only; no live prediction-market quote. |

**Step B — score and tier the rest**

| # | Ticker | Tier | Raw | Quality | Cooldown | Score | Why this tier |
|---|---|---|---|---|---|---|---|
| 1 | NDX | T1 | 0.737 | 0.791 | 1.00 | **0.584** | Catalyst in 1 day; market_move and money_flow p100 |
| 2 | NVDA | T1 | 0.736 | 0.665 | 0.85 | **0.416** | Earnings in 1 day; market_move and money_flow p75 |
| 3 | TSLA | T3 | 0.667 | 0.524 | 1.00 | **0.349** | Attention p100, money_flow only p50 |
| 4 | AAPL | T4 | 0.292 | 0.573 | 1.00 | **0.167** | Buzz fell; no trigger |
| 5 | DJI | T4 | 0.087 | 0.671 | 1.00 | **0.059** | Quiet on every component |

**What it teaches**

- **NDX vs NVDA is decided by the multipliers, not the signals.** Raw scores are nearly identical (0.737 vs 0.736). NDX wins on two sources and tighter spreads (quality 0.791 vs 0.665), and because NVDA, covered 5 days ago, sits in the 0.85 cooldown band.
- **Tier beats score.** TSLA has the most attention in the pool but ranks below both T1 names.
- **Gates change everyone's score.** With N = 1, SPX re-enters, the pool grows to six, every percentile shifts, and NDX's score rises from 0.584 to 0.625 with none of its own data changing.
- **Weights move scores more easily than ranks.** Raising `attention_shift` to 0.50 puts NVDA's raw score above NDX's (0.739 vs 0.690), yet NDX still ranks first. Moderate weight changes don't flip the pick, which is desirable.

**Step C — the pick.** NDX, T1, 0.584. Dominant contract is an `above_below` ladder of depth 8, so the angle is **distribution**: the implied distribution of the Nasdaq-100 close across strikes ahead of the catalyst.

The interactive version in `index.html` lets you move the weights and cooldown and watch the ranking change.

---

## 7. Angle Mapping

Chapters 3–6 decide *who*. This decides *what to say*. The contract structure limits what can honestly be said.

| Structure | Condition | Angle | The episode says | Needs |
|---|---|---|---|---|
| `up_down` | depth = 1 | `direction` | "The market puts 62% on AAPL closing up today." | Price chart, prob history |
| `above_below` / `close_above` | depth ≥ 5 | `distribution` | Implied distribution across strikes, most likely close range | Strike ladder snapshot |
| `hit_target` | any | `touch` | Probability of touching a level intraday or this week | Intraday high / low |
| `up_down` + options | chain available | `updown_vs_option` | An UPDOWN bet vs an option position of similar cost: payoff and breakeven | Options chain, payoff chart |
| range buckets | `cap_strike` set | `range` | Which bucket the market favours, how concentrated | Bucket probabilities |

- A single `up_down` gives one probability; there is no distribution to show.
- A deep ladder gives points on a curve, so the episode can show where the market expects the close and how wide the uncertainty is.
- `updown_vs_option` is the comparison MYCAST is meant to support: the same view as a binary bet or an option. It needs an options chain, often the missing piece.

**Fallback.** If material is missing, drop to the simpler angle and record it in `production_note`. Two fallbacks in a row for the same ticker lowers its `material_sufficiency`.

---

## 8. Overrides

The editor can overrule the board. Overrides are the fastest feedback the system gets, available the same day. Each is logged in Sheet 3 with `selection_mode = override`, one reason code, and one line of text. The code makes overrides countable; the text makes them understandable.

| Code | Use when | What it says about the system |
|---|---|---|
| `BREAKING_NEWS` | Material news broke after the 07:00 build | Snapshot timing, not weights |
| `SIMILAR_RECENT` | A related ticker or theme was covered recently | Cooldown should be theme-level |
| `MATERIAL_GAP` | Top pick can't be produced well today | `material_sufficiency` should enter the score or become a gate |
| `DATA_SUSPECT` | A number looks wrong on inspection | A gate is missing or too loose |
| `EDITORIAL_MIX` | Too many recent episodes on one asset class | Tie-breaker 4 should become a gate |

**Rule of three.** The same code three times within 14 days triggers a weight or gate review at the next weekly check.

---

## 9. Review Loop

At about one episode a day, the sample is too small for regression for months, so review is by hand, weekly.

**Look at**

- **Override rate and codes**: where the board and the editor disagree.
- **`avg_view_duration_pct` and `editor_rating` by tier**: if T1 doesn't beat T3, the tiers aren't capturing what the audience values.
- **Skipped rank-1 days**: did the replacement do better or worse?
- **Calibration**: implied probability at selection vs `market_resolved_as`. Events priced at 70% should happen about 70% of the time.

**Why `avg_view_duration_pct`.** It is closest to "was this the right topic" because it depends least on title and thumbnail. `views_7d` mostly measures packaging. GSC impressions and CTR are independent of the platform's recommendation algorithm.

**Change control**

- Any change to a weight, threshold or tier rule bumps `weights_version`.
- Never recompute `demand_score_at_selection` under new weights; the frozen value is what makes before/after comparison possible.
- Change one thing per week, so its effect can be read.
- Record every change in `CHANGELOG.md`.

---

## 10. Using the config and changelog

### `config/weights_w0.yaml`

Holds every number in Chapters 3–8: gate thresholds, component weights, quality and cooldown parameters, tier conditions, angle rules and override codes. Scoring code should read from this file rather than hard-coding values, so the playbook and the code can't drift apart.

```python
import yaml

cfg = yaml.safe_load(open("config/weights_w0.yaml"))
weights = {k: v["weight"] for k, v in cfg["components"].items()}
max_spread = cfg["gates"]["G3_liquidity_floor"]["max_avg_spread"]
version = cfg["version"]          # write this into 2_topic_log.weights_version
```

**To change a parameter:**

1. Copy `weights_w0.yaml` to `weights_w1.yaml`. Old versions are never edited, because past episodes were selected with them.
2. Change **one** value in the new file and set `version: w1`.
3. Add an entry to `CHANGELOG.md`.
4. Point the scoring job at the new file. From then on, new Sheet 2 rows carry `weights_version = w1`.

> `index.html` currently mirrors the w0 values by hand. When the config changes, update the numbers in the page too, until the page is wired to read the YAML directly.

### `CHANGELOG.md`

One entry per config change, newest first. Each entry states the new version, the date it takes effect, what changed (old → new), the evidence behind it (override codes, episode IDs, weekly review findings), and the effect you expect to see next week. A commented template sits at the bottom of the file.

### Viewing `index.html`

Open it locally in any browser, or publish it with GitHub Pages: **Settings → Pages → Deploy from a branch → `main` / root**. The page will be served at `https://<owner>.github.io/<repo>/`. Note that Pages on a private repo requires a paid GitHub plan.

---

## 11. Source Coverage and Open Items

| Component | Adanos | Kalshi | eToro |
|---|---|---|---|
| `attention_shift` | yes | — | pending |
| `activity_shift` | yes | — | pending |
| `money_flow` | Polymarket volume | indices only | pending |
| `money_stock` | — | indices only | — |
| `market_move` | Polymarket probability | indices only | — |
| `sentiment_shift` | yes | — | `net_position_delta` |

**Open items**

- The Kalshi free sample covers only KXINXU (S&P 500), KXNASDAQ100U and KXDJI. Single stocks rely on Adanos.
- Kalshi deltas need a continuous snapshot history from the VPS.
- Sheet 2 needs new columns: `mkt_volume_delta_1d`, `mkt_oi_delta_1d`, `weights_version`, `catalyst`, `catalyst_date`.
- Rename `buzz_trend` → `buzz_trend_7d`. Adanos's trend label uses a 7-day window while `buzz_delta_1d` is one day, so they can legitimately disagree.
- At 15-minute cadence Sheet 1 grows by about 40,000 rows a day and reaches Excel's row limit within weeks. It belongs in a database, with Excel as a view.
- eToro not yet evaluated.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| `implied_prob` | Mid of bid and ask; the market's price-implied probability. |
| `spread` | Ask minus bid; the error bar on `implied_prob`. |
| `open_interest` | Contracts still held open; money that stays in the market. |
| `ladder_depth` | Number of strikes for one underlying and expiry. |
| `buzz_score` | Adanos's attention measure: how much, not which way. |
| percentile (`pctrank`) | Position within today's pool, 0 (lowest) to 1 (highest). |
| catalyst | A scheduled event likely to move price: earnings, FOMC, CPI. |
| compensatory | A score where strength in one input can offset weakness in another. |
| lexicographic | Sort by the first key; use the second only to break ties. |
| calibration | Whether events priced at X% happen about X% of the time. |
| `weights_version` | Label of the config used for a ranking, e.g. `w0`. |
