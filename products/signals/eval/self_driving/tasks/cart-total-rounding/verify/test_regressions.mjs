// Catches: regressions in cart totals that were already correct — zero-tax carts, single-line taxed carts, empty carts, and invoice shape.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { computeCartTotalCents } = require("../src/totals.js");
const { buildInvoice } = require("../src/invoices.js");

test("zero-tax multi-line cart sums exactly", () => {
  const items = [
    { sku: "gift-card", unitPriceCents: 500, quantity: 2 },
    { sku: "sticker", unitPriceCents: 250, quantity: 1 },
  ];
  assert.equal(computeCartTotalCents(items, 0), 1250);
});

test("single-line taxed cart keeps its total", () => {
  assert.equal(computeCartTotalCents([{ sku: "candle-lg", unitPriceCents: 1999, quantity: 1 }], 0.0725), 2144);
});

test("empty cart totals zero", () => {
  assert.equal(computeCartTotalCents([], 0.0725), 0);
});

test("invoices carry integer-cent totals and the line items", () => {
  const items = [{ sku: "candle-lg", unitPriceCents: 1999, quantity: 1 }];
  const invoice = buildInvoice(items, 0.0725);
  assert.equal(invoice.totalCents, 2144);
  assert.ok(Number.isInteger(invoice.totalCents));
  assert.equal(invoice.currency, "usd");
  assert.equal(invoice.lineItems.length, 1);
  assert.equal(invoice.lineItems[0].sku, "candle-lg");
});
