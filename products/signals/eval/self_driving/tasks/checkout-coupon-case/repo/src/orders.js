const { quoteShipping } = require("./shipping");

let orderSeq = 1000;

/** Turn a cart into an order ready for payment capture. */
function finalizeOrder(cart, region = "us") {
  const shippingCents = quoteShipping(cart.totalCents, region);
  return {
    orderId: `ord_${orderSeq++}`,
    cartId: cart.id,
    itemCount: cart.items.length,
    subtotalCents: cart.totalCents,
    shippingCents,
    totalCents: cart.totalCents + shippingCents,
    placedAt: new Date().toISOString(),
  };
}

module.exports = { finalizeOrder };
