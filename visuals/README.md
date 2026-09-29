# visuals

**Status:** v0: PNG export pipeline for payoff cards. Price panel (Lightweight Charts) not started.

## Purpose

Turn Topic Log charts into static frames that Shotstack can composite into the MYCAST video.

| Tool | Role |
|---|---|
| **Plotly.js** | Renders payoff cards and scenario charts (via [`../templates/`](../templates/)). |
| **Kaleido** (Python) | Exports the same Plotly figures to PNG/SVG. Plotly.js alone only renders in a browser. |
| **Lightweight Charts** | Price / candlestick panel. Separate from the payoff cards. *Not built yet.* |

## Inputs

A deck of card configs (default `templates/examples/cards.json`).

## Outputs

One image per card in `visuals/out/png/`, at the frame size set in `THEME` (default 1280×720). `visuals/out/` is git-ignored.

## Depends on

- Node 18+ (no npm packages needed)
- Python 3 with `plotly` and `kaleido` (`pip install -r visuals/requirements.txt`)
- Chrome or Chromium for Kaleido 1.x: run `plotly_get_chrome` once, or set `BROWSER_PATH` to an existing binary

## Contents

| File | Purpose |
|---|---|
| `build_figures.js` | Step 1: card configs → Plotly figure JSON (`out/figures/<id>.json`) |
| `export_png.py` | Step 2: figure JSON → PNG with Kaleido (`out/png/<id>.png`) |
| `requirements.txt` | Python dependencies |

The split is deliberate: figures are defined once, in JavaScript, and the JSON is the hand-off. The browser preview and the exported PNG render the same JSON, so what you see in `templates/preview.html` is what lands in the video.

## Usage

From the repo root:

```bash
npm run build:figures        # or: node visuals/build_figures.js [deck.json] [out_dir]
npm run export:png           # or: python3 visuals/export_png.py [--scale 2] [--format svg]
```

or both at once with `npm run render`.

To render your own deck: `node visuals/build_figures.js path/to/deck.json`, then `python3 visuals/export_png.py`.

`--scale 2` doubles resolution (2560×1440 for the default frame).

## Next

- Lightweight Charts price panel for the `direction` angle
- Strike-ladder chart for the `distribution` angle (implied distribution across strikes)
- Pick cards automatically from the angle chosen in `3_episode_log`
- Hand the PNGs to Shotstack (upload + timeline JSON)

---

Back to the [project README](../README.md).
