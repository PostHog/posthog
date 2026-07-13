// Catches: regressions in pre-existing coupon behavior — uppercase codes, fixed-amount floor, shipping coupons, and unknown codes erroring cleanly.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { applyCoupon, getCoupon } = require("../src/coupons.js");

test("uppercase SAVE10 still applies a 10% discount", () => {
  assert.equal(applyCoupon(8400, "SAVE10"), 7560);
});

test("fixed-amount WELCOME5 subtracts 500 cents and floors at zero", () => {
  assert.equal(applyCoupon(1000, "WELCOME5"), 500);
  assert.equal(applyCoupon(300, "WELCOME5"), 0);
});

test("FREESHIP leaves the cart total unchanged", () => {
  assert.equal(applyCoupon(2000, "FREESHIP"), 2000);
});

test("unknown codes throw a clean error instead of applying", () => {
  assert.equal(getCoupon("BOGUS99"), null);
  assert.throws(() => applyCoupon(8400, "BOGUS99"), /Unknown coupon/);
});
