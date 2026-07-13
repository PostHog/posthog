const analytics = require("./analytics");

/** Handle asynchronous PSP notifications (disputes, refunds). */
function handlePspEvent(event) {
  if (event.type === "charge.dispute.created") {
    analytics.capture(event.customerId || "unknown", "payment_disputed", {
      invoice_id: event.invoiceId,
      reason: event.reason || "amount_mismatch",
      item_count: event.itemCount,
      amount_cents: event.amountCents,
    });
    return { handled: true };
  }
  return { handled: false };
}

module.exports = { handlePspEvent };
