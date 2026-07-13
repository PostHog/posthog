// Catches: coupon codes typed lowercase (as printed in the campaign email) failing lookup — coupon application must be case-insensitive.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { applyCoupon, getCoupon } = require("../src/coupons.js");

test("applying 'save10' (lowercase, as printed in the campaign email) discounts the cart", () => {
  assert.equal(applyCoupon(8400, "save10"), 7560);
});

test("coupon lookup accepts mixed case", () => {
  assert.ok(getCoupon("Save10"), "getCoupon('Save10') should resolve the SAVE10 coupon");
  assert.equal(applyCoupon(1000, "welcome5"), 500);
});

test("lowercase code with surrounding whitespace still applies", () => {
  assert.equal(applyCoupon(8400, "  save10 "), 7560);
});
