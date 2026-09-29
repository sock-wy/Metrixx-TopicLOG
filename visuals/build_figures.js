#!/usr/bin/env node
/*
 * Step 1 of the video export: card configs -> Plotly figure JSON.
 *
 *   node visuals/build_figures.js [deck.json] [out_dir]
 *
 * Defaults: templates/examples/cards.json -> visuals/out/figures/
 * Each card or comparison becomes <id>.json containing { data, layout, meta }.
 * Step 2 (export_png.py) renders these to PNG with Kaleido.
 */
const fs = require('fs');
const path = require('path');
const Cards = require('../templates/cards/metrixx-cards.js');

const root = path.resolve(__dirname, '..');
const deckPath = path.resolve(process.argv[2] || path.join(root, 'templates/examples/cards.json'));
const outDir = path.resolve(process.argv[3] || path.join(__dirname, 'out/figures'));

const deck = JSON.parse(fs.readFileSync(deckPath, 'utf8'));
fs.mkdirSync(outDir, { recursive: true });

const figures = Cards.buildDeck(deck);
for (const [id, fig] of Object.entries(figures)) {
  if (!id || id === 'undefined') throw new Error('Every card and comparison needs an "id".');
  // Infinity is not valid JSON; meta uses strings for unbounded values.
  const meta = JSON.parse(JSON.stringify(fig.meta, (k, v) =>
    v === Infinity ? 'unlimited' : v === -Infinity ? '-unlimited' : v));
  fs.writeFileSync(path.join(outDir, `${id}.json`), JSON.stringify({ data: fig.data, layout: fig.layout, meta }));
  console.log(`built ${id}`);
}
console.log(`${Object.keys(figures).length} figures -> ${path.relative(process.cwd(), outDir) || outDir}`);
