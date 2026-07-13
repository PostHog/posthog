const COUPONS = {
  SAVE10: { type: "percent", amount: 10 },
  SAVE25: { type: "percent", amount: 25 },
  FREESHIP: { type: "shipping", amount: 0 },
  WELCOME5: { type: "fixed", amount: 500 },
};

/** Look up a coupon by its code. Returns null for unknown codes. */
function getCoupon(code) {
  const normalized = code.trim();
  return COUPONS[normalized] ?? null;
}

/**
 * Apply a coupon to a cart total (in cents). Returns the discounted total.
 * Throws if the coupon doesn't exist.
 */
function applyCoupon(totalCents, code) {
  const coupon = getCoupon(code);
  if (!coupon) {
    throw new Error(`Unknown coupon: ${code}`);
  }
  if (coupon.type === "percent") {
    return Math.round(totalCents * (1 - coupon.amount / 100));
  }
  if (coupon.type === "fixed") {
    return Math.max(0, totalCents - coupon.amount);
  }
  return totalCents;
}

module.exports = { getCoupon, applyCoupon, COUPONS };
