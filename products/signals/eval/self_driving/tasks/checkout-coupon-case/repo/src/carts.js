// In-memory cart store — good enough for the demo deployment.
const carts = new Map();

function createCart({ items = [], totalCents = 0 } = {}) {
  const id = Math.random().toString(36).slice(2, 10);
  const cart = { id, items, totalCents, couponCode: null };
  carts.set(id, cart);
  return cart;
}

function getCart(id) {
  return carts.get(id) ?? null;
}

module.exports = { createCart, getCart };
