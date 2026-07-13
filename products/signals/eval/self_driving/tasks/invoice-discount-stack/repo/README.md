# Acme Billing Engine

Generates invoices for Acme orders: subtotal, discount, regional tax, total.

Discount policy (see pricing page): discounts never stack - when an account
holds several codes, the single best one for the order is applied
automatically.

## Running

```bash
npm install
npm start
# server on http://localhost:4900
```

## API

- `POST /api/invoices` - `{ customerId, items, discountCodes?, region? }` returns the computed invoice

## Layout

- `src/invoice.js` - invoice assembly
- `src/discounts.js` - eligibility + best-discount selection
- `src/tax.js` - regional tax
- `src/money.js` - currency formatting
- `data/discounts.js` - active discount definitions
