# Omnisend API inventory

Reference for the `omnisend` warehouse source. Verify against the live API before
changing endpoint behavior — see the `implementing-warehouse-sources` skill.

- **API version:** v3 (`https://api.omnisend.com/v3`). v3 is the stable resource-based
  REST surface for contacts/orders/products/carts/categories/campaigns. (v5 / v2026-03-15
  reshape several of these into event-centric endpoints; v3 is the right fit for a
  list-and-sync warehouse source.)
- **Auth:** API key in the `X-API-KEY` header.
- **Pagination:** offset/limit with a fully-formed next-page URL at `paging.next`
  (`null` when exhausted). We follow `paging.next` directly, which makes pagination
  resumable. `limit` default 100, max 250.
- **Rate limits:** 400 req/min general; 100 req/min segment reads; 15 req/min segment
  writes. We only read general list endpoints. 429s carry `Retry-After`.

## List endpoints

| Schema     | Path          | Response array key | Primary key  | Partition (stable) |
| ---------- | ------------- | ------------------ | ------------ | ------------------ |
| contacts   | `/contacts`   | `contacts`         | `contactID`  | `createdAt`        |
| campaigns  | `/campaigns`  | `campaigns`        | `campaignID` | `createdAt`        |
| carts      | `/carts`      | `carts`            | `cartID`     | `createdAt`        |
| orders     | `/orders`     | `orders`           | `orderID`    | `createdAt`        |
| products   | `/products`   | `products`         | `productID`  | `createdAt`        |
| categories | `/categories` | `categories`       | `categoryID` | —                  |

Endpoint existence confirmed against the live API (all return non-404 without a key).
Primary-key / response-key names follow Omnisend's consistent `<resource>` /
`<resource>ID` v3 convention (the create-contact response returns `contactID`); exact
shapes of the list responses were not re-verified with a live key.

## Sync mode

All endpoints ship **full refresh (replace)**.

Omnisend documents `updatedAtFrom` as a server-side filter on `/contacts`, but with hard
restrictions (it cannot be combined with `email`, `phone`, `status`, `segmentID`, or
`tag`). The skill requires confirming a server-side timestamp filter actually filters via
a live curl smoke test (future-date cutoff) before advertising incremental sync. Without
API credentials to run that check, we conservatively ship full refresh everywhere. Once a
key is available, `/contacts` is the candidate to flip to incremental on `updatedAt`.

## Caveats

- `/orders`: orders that Omnisend auto-syncs from e-commerce platforms (Shopify,
  BigCommerce, WooCommerce) are **not** exposed through v3 — only orders pushed via the
  API are returned.
