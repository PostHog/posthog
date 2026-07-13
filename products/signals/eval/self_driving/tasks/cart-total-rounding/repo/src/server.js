const express = require("express");
const { computeCartTotalCents } = require("./totals");
const { buildInvoice } = require("./invoices");
const { capturePayment } = require("./payments");
const { handlePspEvent } = require("./webhooks");
const analytics = require("./analytics");

const app = express();
app.use(express.json());

app.post("/api/orders/price", (req, res) => {
  const { items = [] } = req.body;
  const totalCents = computeCartTotalCents(items);
  analytics.capture(req.headers["x-customer-id"] || "anonymous", "order_priced", {
    total_cents: totalCents,
    item_count: items.length,
  });
  res.json({ totalCents });
});

app.post("/api/invoices", async (req, res) => {
  const { items = [], customerId = "anonymous" } = req.body;
  const invoice = buildInvoice(items);
  const payment = await capturePayment(invoice, customerId);
  res.status(201).json({ invoice, payment });
});

app.post("/api/psp/webhook", (req, res) => {
  const result = handlePspEvent(req.body);
  res.status(result.handled ? 200 : 202).json(result);
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => console.log(`acme-billing listening on :${port}`));
}

module.exports = app;
