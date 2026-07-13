# acme-checkout

Checkout service for the Acme Store. Handles carts, shipping quotes, coupon redemption, and order placement.

## Endpoints

- `POST /api/cart` — create a cart
- `GET /api/cart/:id` — fetch a cart
- `POST /api/cart/:id/coupon` — apply a coupon code to a cart
- `POST /api/cart/:id/checkout` — place the order

## Development

```
npm install
npm start
```

Set `POSTHOG_API_KEY` to enable product analytics capture.
