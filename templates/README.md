# templates

**Status:** v0: card library for option and prediction-market payoff charts

## Purpose

One reusable chart template for MYCAST payoff cards. Each card (straddle, condor, covered call, spread, prediction-market step…) is a **config object**, not a new HTML file. The library turns a config into Plotly figure JSON, which renders live in a browser and exports to PNG for video (see [`../visuals/`](../visuals/)).

## Inputs

A card config, or a deck of them (`examples/cards.json`):

```json
{
  "id": "aapl_long_straddle",
  "strategy": "long_straddle",
  "underlying": "AAPL",
  "spot": 250,
  "params": { "strike": 250, "call_premium": 6.10, "put_premium": 5.80 }
}
```

Optional fields: `title`, `subtitle` (override the defaults), `range` (`[lo, hi]` for the x axis).

A **comparison** overlays several strategies on one chart (the scenario chart, e.g. the `updown_vs_option` angle):

```json
{
  "id": "aapl_updown_vs_call",
  "underlying": "AAPL",
  "spot": 250,
  "title": "AAPL · $610 on UP vs $610 on a call",
  "members": [
    { "label": "UP contract", "strategy": "polymarket_step", "params": { "strike": 250, "price": 0.55, "stake": 610 } },
    { "label": "250 call", "strategy": "long_call", "params": { "strike": 250, "premium": 6.10 } }
  ]
}
```

## Outputs

`{ data, layout, meta }`: a Plotly figure plus `meta` with max profit, max loss, breakevens and net cost (computed exactly, not sampled).

## Depends on

Nothing at runtime. The browser preview loads Plotly.js from cdnjs.

## Contents

| File | Purpose |
|---|---|
| `cards/metrixx-cards.js` | The library: theme, payoff engine, strategy registry, `buildCard`, `buildComparison`, `buildDeck`. Works as a `<script>` tag and as a Node module. |
| `cards/cards.test.js` | Unit tests for payoffs, breakevens and max profit/loss of every strategy. |
| `examples/cards.json` | Example deck (illustrative AAPL prices). |
| `preview.html` | Gallery of the example deck plus a live editor. Renders at the exact export size, scaled to fit. |

### Strategies and their params

| `strategy` | `params` |
|---|---|
| `long_call` / `long_put` | `strike`, `premium`, `qty`? |
| `long_straddle` | `strike`, `call_premium`, `put_premium`, `qty`? |
| `long_strangle` | `put_strike`, `call_strike`, `put_premium`, `call_premium`, `qty`? |
| `bull_call_spread` / `bear_put_spread` | `long_strike`, `short_strike`, `long_premium`, `short_premium`, `qty`? |
| `iron_condor` (short) | `put_long`, `put_short`, `call_short`, `call_long` and a `…_premium` for each |
| `covered_call` | `entry`, `strike`, `premium`, `shares`? (default 100) |
| `polymarket_step` (alias `binary_step`) | `strike`, `price` (0–1), `stake` ($), `direction`? (`above` \| `below`) |

Options use a 100 multiplier; P/L is in dollars at expiry. A prediction-market contract pays $1 if the condition holds; `stake / price` contracts are bought. For an up/down market, `strike` is the reference price.

## Usage

**Preview in a browser.** From the repo root run `python3 -m http.server` and open `http://localhost:8000/templates/preview.html`. (Opening the file directly blocks loading the example deck.) On GitHub Pages it works as is.

**Use in code.**

```js
// Node
const Cards = require('./templates/cards/metrixx-cards.js');
const fig = Cards.buildCard(config);          // { data, layout, meta }

// Browser
// <script src="templates/cards/metrixx-cards.js"></script>
Plotly.react(el, fig.data, fig.layout);
```

**Add a strategy.** Add one entry to `STRATEGIES` in `metrixx-cards.js` with `label`, `legs(params)` and `describe(params)`, then a test in `cards.test.js`. Legs are `call`, `put`, `stock` or `binary`, each `long` or `short`.

**Change the look.** Edit the `THEME` block at the top of `metrixx-cards.js` only: colours, fonts and frame size (default 1280×720). This is where the cards get aligned with the existing P/L panel style.

**Run tests.** `npm test` from the repo root.

---

Back to the [project README](../README.md).
