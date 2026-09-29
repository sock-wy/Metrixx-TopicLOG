// Run: node --test templates/cards/
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('./metrixx-cards.js');

const close = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) < tol, `${a} != ${b}`);
const legs = (strategy, params) => C.STRATEGIES[strategy].legs(params);

test('long call: breakeven = strike + premium, unlimited upside', () => {
  const s = C.analyse(legs('long_call', { strike: 250, premium: 6.10 }));
  close(s.breakevens[0], 256.10);
  assert.equal(s.maxProfit, Infinity);
  close(s.maxLoss, -610);
});

test('long straddle: two breakevens at K ± total premium', () => {
  const s = C.analyse(legs('long_straddle', { strike: 250, call_premium: 6.10, put_premium: 5.80 }));
  assert.equal(s.breakevens.length, 2);
  close(s.breakevens[0], 238.10);
  close(s.breakevens[1], 261.90);
  close(s.maxLoss, -1190);
  assert.equal(s.maxProfit, Infinity);
});

test('bull call spread: capped both sides', () => {
  const s = C.analyse(legs('bull_call_spread', { long_strike: 250, short_strike: 260, long_premium: 6.10, short_premium: 2.35 }));
  close(s.maxProfit, 625);
  close(s.maxLoss, -375);
  close(s.breakevens[0], 253.75);
  close(s.netCost, 375);
});

test('bear put spread', () => {
  const s = C.analyse(legs('bear_put_spread', { long_strike: 250, short_strike: 240, long_premium: 5.80, short_premium: 2.20 }));
  close(s.maxProfit, 640);
  close(s.maxLoss, -360);
  close(s.breakevens[0], 246.40);
});

test('iron condor: credit is max profit, wing width minus credit is max loss', () => {
  const s = C.analyse(legs('iron_condor', {
    put_long: 235, put_short: 240, call_short: 260, call_long: 265,
    put_long_premium: 0.95, put_short_premium: 1.85, call_short_premium: 2.35, call_long_premium: 1.20,
  }));
  close(s.maxProfit, 205);
  close(s.maxLoss, -295);
  close(s.breakevens[0], 237.95);
  close(s.breakevens[1], 262.05);
  close(s.netCost, -205);
});

test('covered call: capped upside, loss bounded by stock going to zero', () => {
  const s = C.analyse(legs('covered_call', { entry: 250, strike: 260, premium: 2.35 }));
  close(s.maxProfit, 1235);
  close(s.maxLoss, -24765);
  close(s.breakevens[0], 247.65);
});

test('binary step: stake / price contracts, pays $1 each', () => {
  const s = C.analyse(legs('polymarket_step', { strike: 250, price: 0.55, stake: 610 }));
  close(s.maxProfit, 610 / 0.55 - 610, 1e-6);
  close(s.maxLoss, -610, 1e-6);
  assert.equal(s.breakevens.length, 1);
  close(s.breakevens[0], 250, 1e-3);
  close(s.netCost, 610, 1e-6);
});

test('binary step below: wins when price finishes under strike', () => {
  const L = legs('binary_step', { strike: 250, price: 0.40, stake: 100, direction: 'below' });
  close(C.pnl(L, 240), 100 / 0.40 - 100);
  close(C.pnl(L, 260), -100);
});

test('buildCard returns Plotly figure JSON with meta', () => {
  const fig = C.buildCard({ id: 'x', strategy: 'long_straddle', underlying: 'AAPL', spot: 250,
    params: { strike: 250, call_premium: 6.1, put_premium: 5.8 } });
  assert.ok(Array.isArray(fig.data) && fig.data.length >= 3);
  assert.equal(fig.layout.width, C.THEME.width);
  assert.equal(fig.meta.id, 'x');
  JSON.parse(JSON.stringify(fig)); // serialisable
});

test('buildDeck builds every example', () => {
  const deck = require('../examples/cards.json');
  const out = C.buildDeck(deck);
  assert.equal(Object.keys(out).length, deck.cards.length + deck.comparisons.length);
});

test('unknown strategy gives a clear error', () => {
  assert.throws(() => C.buildCard({ strategy: 'nope', params: {}, spot: 1 }), /Unknown strategy: nope/);
});
