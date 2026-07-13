const { TAX_RATE } = require("./config");

function lineTotal(item, taxRate) {
  const gross = (item.unitPriceCents * item.quantity) / 100;
  const taxed = gross * (1 + taxRate);
  return Number(taxed.toFixed(2));
}

/** Price a cart: returns the charge amount in integer cents. */
function computeCartTotalCents(items, taxRate = TAX_RATE) {
  let totalDollars = 0;
  for (const item of items) {
    totalDollars += lineTotal(item, taxRate);
  }
  return Math.round(totalDollars * 100);
}

module.exports = { computeCartTotalCents };
