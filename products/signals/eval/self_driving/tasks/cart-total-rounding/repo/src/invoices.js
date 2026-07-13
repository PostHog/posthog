const { computeCartTotalCents } = require("./totals");
const { CURRENCY, TAX_RATE } = require("./config");

let invoiceSeq = 5000;

/** Build an invoice for a priced cart. */
function buildInvoice(items, taxRate = TAX_RATE) {
  return {
    invoiceId: `inv_${invoiceSeq++}`,
    currency: CURRENCY,
    lineItems: items.map((item) => ({
      sku: item.sku,
      unitPriceCents: item.unitPriceCents,
      quantity: item.quantity,
    })),
    totalCents: computeCartTotalCents(items, taxRate),
    issuedAt: new Date().toISOString(),
  };
}

module.exports = { buildInvoice };
