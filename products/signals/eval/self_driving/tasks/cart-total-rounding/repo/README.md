# acme-billing

Billing service for the Acme Store: prices carts, issues invoices, captures payments, and handles PSP webhooks.

## Pricing rules

All amounts are integer cents. Sales tax (`TAX_RATE` in `src/config.js`) is applied **once to the order subtotal**; the only rounding happens when the taxed total is converted back to whole cents.

## Endpoints

- `POST /api/orders/price` — price a cart (`{ items: [{ sku, unitPriceCents, quantity }] }`)
- `POST /api/invoices` — build an invoice and capture payment (`{ items, customerId }`)
- `POST /api/psp/webhook` — payment provider notifications (disputes, refunds)

## Development

```
npm install
npm start
```

Set `POSTHOG_API_KEY` to enable billing analytics capture.
