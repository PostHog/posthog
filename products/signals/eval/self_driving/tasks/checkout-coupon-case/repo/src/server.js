const express = require("express");
const { applyCoupon } = require("./coupons");
const { createCart, getCart } = require("./carts");
const { finalizeOrder } = require("./orders");
const analytics = require("./analytics");

const app = express();
app.use(express.json());

app.post("/api/cart", (req, res) => {
  const cart = createCart(req.body);
  analytics.capture(req.headers["x-user-id"] || "anonymous", "checkout_started", {
    cart_id: cart.id,
    item_count: cart.items.length,
  });
  res.json({ cartId: cart.id });
});

app.get("/api/cart/:id", (req, res) => {
  const cart = getCart(req.params.id);
  if (!cart) return res.status(404).json({ error: "cart_not_found" });
  res.json(cart);
});

app.post("/api/cart/:id/coupon", (req, res) => {
  const cart = getCart(req.params.id);
  if (!cart) return res.status(404).json({ error: "cart_not_found" });
  const { code } = req.body;
  const distinctId = req.headers["x-user-id"] || "anonymous";
  analytics.capture(distinctId, "coupon_attempted", { cart_id: cart.id, code });
  try {
    const discounted = applyCoupon(cart.totalCents, code);
    cart.totalCents = discounted;
    cart.couponCode = code;
    analytics.capture(distinctId, "coupon_applied", { code, discounted_total_cents: discounted });
    res.json({ totalCents: discounted });
  } catch (err) {
    analytics.capture(distinctId, "$exception", {
      $exception_type: "Error",
      $exception_message: err.message,
      $exception_source: "src/coupons.js",
      path: req.path,
    });
    res.status(500).json({ error: "coupon_error" });
  }
});

app.post("/api/cart/:id/checkout", (req, res) => {
  const cart = getCart(req.params.id);
  if (!cart) return res.status(404).json({ error: "cart_not_found" });
  const order = finalizeOrder(cart, req.body?.region);
  analytics.capture(req.headers["x-user-id"] || "anonymous", "checkout_completed", {
    order_id: order.orderId,
    total_cents: order.totalCents,
  });
  res.json(order);
});

const port = process.env.PORT || 3000;
if (require.main === module) {
  app.listen(port, () => console.log(`acme-checkout listening on :${port}`));
}

module.exports = app;
