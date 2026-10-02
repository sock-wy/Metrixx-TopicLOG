# backtest

**Status:** v0 — studies `crypto_indices` and `adanos_crypto` complete · **results: open [`results.html`](results.html) in a browser**

## Purpose

Checks whether the Topic Log selection procedure picks the tickers that turn out to be newsworthy. Each version replays the daily run on history: build the board from data available at the pick time, apply the playbook rules exactly as `scoring/` implements them, and compare the pick with what happened next.

This folder is self-contained. It reads `ingestion/` (collectors), `scoring/` (rules) and `config/` (parameters) and writes nothing outside `backtest/`.

## Inputs

- Snapshot tables in `snapshots/<universe>/` (committed), built from raw API responses
- A study config in `studies/<study>/` (one YAML per version)
- `config/weights_w0.yaml`, with per-study overrides

## Outputs

- **`results.html`** — the results page: every study's conclusion, charts and tables in one place. Open it in a browser.
- `runs/<study>/<date>_<version>_<commit>/` — the raw record of each run: `config.yaml`, `summary.json`, `daily_log.csv`, `pool_log.csv`.
- `runs/INDEX.md` — plain-text table of the latest run of every version.

## Depends on

`ingestion/`, `scoring/`, `config/`. Python packages in `/requirements.txt`.

## Contents

| Path | What it is |
|---|---|
| `run.py` | Entry point: runs one version or every version of a study, refreshes `runs/INDEX.md` |
| `engine.py` | Daily selection replay: cooldown from its own picks, catalysts, scoring, sanity modes |
| `labels.py` | Post-pick outcome per ticker: abs move / trailing sigma |
| `evaluate.py` | IC, pick percentile, top-1 hit, momentum benchmark, permutation and bootstrap tests, Holm correction |
| `adanos_study.py` | Study `adanos_crypto` (Adanos signals only, Binance prices), implementing its `PREREG.md` |
| `results_page.py` | Builds `results.html` from the latest runs |
| `results.html` | The results page |
| `build_snapshots.py` | Raw API responses → snapshot tables (4 snapshots a day reconstructed from hourly candles) |
| `universes/` | Ticker sets and how each maps to Kalshi, Adanos and Yahoo |
| `catalysts/` | Scheduled events (CPI, FOMC) used by tier T1 |
| `studies/` | One folder per study: one YAML per version (`crypto_indices`) or a `PREREG.md` (`adanos_crypto`); `sanity/` versions run only inside pytest |
| `snapshots/` | Committed snapshot tables (small; raw responses stay out of git) |
| `runs/` | Results |
| `tests/` | Bias checks (look-ahead, past-only rolling statistics, sanity modes) |

## Usage

From the repository root:

```bash
pip install -r requirements.txt

# reproduce every version of a study from the committed snapshots (no API calls)
python -m backtest.run --study backtest/studies/crypto_indices
python -m backtest.adanos_study run

# rebuild the results page from the latest runs
python -m backtest.results_page

# one version
python -m backtest.run backtest/studies/crypto_indices/base.yaml

# bias checks + the playbook worked example
python -m pytest -q backtest/tests scoring/tests
```

**Add a version:** first write it into the study's pre-registration (question, rule, decision). Then create a YAML with `inherits: base.yaml`, a new `name`, and only the keys that differ. Every version run is listed and counted in the Holm correction.

**Add a study** (e.g. single stocks): add `universes/<name>.yaml`, pull and build its snapshots, then create `studies/<name>/base.yaml`.

**Refresh the data** (needs `ADANOS_API_KEY` in `.env`; Kalshi and Yahoo need no key):

```bash
python -m ingestion.pull kalshi --universe backtest/universes/crypto_indices.yaml --start 2026-08-03 --end 2026-10-01
python -m ingestion.pull adanos --universe backtest/universes/crypto_indices.yaml --start 2026-07-20 --end 2026-10-01
python -m ingestion.pull yahoo  --universe backtest/universes/crypto_indices.yaml
python -m backtest.build_snapshots --universe backtest/universes/crypto_indices.yaml \
    --start 2026-08-03 --end 2026-10-01 --adanos-from 2026-07-20 --adanos-to 2026-10-01   # add --incremental on the VPS
python -m backtest.adanos_study build     # adanos_crypto: Adanos + Binance, universe fixed from the formation period
```

Kalshi serves event-level candles only for events settled after its historical cutoff (2026-08-02 at the time of writing); longer histories need the VPS collector running.

## How a `crypto_indices` version is evaluated

| Step | Rule |
|---|---|
| Pick time | 15:00 ET each day (crypto every day; indices on trading days) |
| Kalshi features | The live daily ladder's state at the four snapshots up to the pick (15:00, 21:00, 03:00, 09:00 ET), from candles closed by then |
| Adanos features | Complete UTC days only: day t-1 vs t-2 (day t is still open at 15:00 ET) |
| Scoring | `scoring.scoring.score_day` with `config/weights_w0.yaml` plus the study's overrides |
| Cooldown | From the replay's own earlier picks |
| Label | Abs log return 15:00 ET t → 15:00 ET next session (Kalshi settlement values), divided by trailing 20-day sigma from Yahoo returns dated before t |
| Benchmarks | Random pick; momentum (the pool's biggest mover into the pick) |
| Tests | Permutation p-values (pick vs random, IC vs within-day shuffle), bootstrap 95% CIs over days, Holm across versions |

Sanity versions (`studies/<study>/sanity/`, run by pytest, nothing written) must give: oracle IC = 1 and top-1 hit = 1; placebos indistinguishable from random. If they don't, the harness is wrong and no result counts.

## How `adanos_crypto` is evaluated

See [`studies/adanos_crypto/PREREG.md`](studies/adanos_crypto/PREREG.md): 25 Reddit-discussed tokens fixed from a formation period, daily decision at 00:00 UTC on complete days, label = next-day abnormal high-low range (Binance), versions A0–A3 plus momentum, discovery/holdout split, Holm within families.

## Fields not used in this study (kept in the raw data)

Raw responses are stored whole, so these can be added later without re-pulling:

- **Kalshi:** hourly and 15-minute up/down series, range-bucket series, perpetual funding and open interest
- **Adanos:** `bullish_pct`, `bearish_pct`, positive/negative/neutral counts, `trend`, `total_upvotes`, `unique_posts`, `subreddit_count`, `top_subreddits`, `top_mentions`; Polymarket `unique_traders`

---

Back to the [project README](../README.md).
