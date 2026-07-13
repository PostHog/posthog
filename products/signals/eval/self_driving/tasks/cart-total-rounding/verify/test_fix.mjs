// Catches: per-line dollar rounding (toFixed per line, then summed) accumulating cent drift on multi-item carts — tax must be applied once to the integer-cent subtotal with a single final rounding.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { computeCartTotalCents } = require("../src/totals.js");

const RATE = 0.0725;

test("ten 145-cent lines at 7.25% tax total 1555 cents, not 1560", () => {
  const items = Array.from({ length: 10 }, () => ({ sku: "candle-sm", unitPriceCents: 145, quantity: 1 }));
  assert.equal(computeCartTotalCents(items, RATE), 1555);
});

test("seven 105-cent lines at 7.25% tax total 788 cents, not 791", () => {
  const items = Array.from({ length: 7 }, () => ({ sku: "wick-trim", unitPriceCents: 105, quantity: 1 }));
  assert.equal(computeCartTotalCents(items, RATE), 788);
});

test("mixed cart totals 684 cents, not 685", () => {
  const items = [
    { sku: "tealight", unitPriceCents: 89, quantity: 2 },
    { sku: "wick-trim", unitPriceCents: 105, quantity: 3 },
    { sku: "candle-sm", unitPriceCents: 145, quantity: 1 },
  ];
  assert.equal(computeCartTotalCents(items, RATE), 684);
});
