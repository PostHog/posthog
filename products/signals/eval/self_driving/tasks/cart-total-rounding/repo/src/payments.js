const analytics = require("./analytics");

/** Capture payment for an invoice via the PSP (stubbed in the demo deployment). */
async function capturePayment(invoice, customerId) {
  analytics.capture(customerId, "payment_captured", {
    invoice_id: invoice.invoiceId,
    amount_cents: invoice.totalCents,
  });
  return { invoiceId: invoice.invoiceId, status: "captured", amountCents: invoice.totalCents };
}

module.exports = { capturePayment };
