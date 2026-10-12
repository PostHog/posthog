# Omnisend API inventory

Reference for the `omnisend` warehouse source. Verify against the live API before
changing endpoint behavior — see the `implementing-warehouse-sources` skill.

Two API versions are supported. New sources default to `2026-03-15`; `v3` is deprecated by
Omnisend (no sunset date announced) and existing `v3` pins keep working unchanged.

|                 | `v3` (deprecated)             | `2026-03-15` (default)                                                                                        |
| --------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Base URL        | `https://api.omnisend.com/v3` | `https://api.omnisend.com/api`                                                                                |
| Auth            | `X-API-KEY: {key}`            | `Authorization: Omnisend-API-Key {key}`                                                                       |
| Version header  | none                          | `Omnisend-Version: 2026-03-15` (required)                                                                     |
| Pagination      | `paging.next` full URL        | contacts, campaigns: cursor (`paging.cursors.after`, `?after=`); products, categories: `paging.next` full URL |
| Retired version | —                             | `410 Gone`                                                                                                    |

The same API key works for both versions; only the header changes. `limit` default 100, max 250.

- **Rate limits:** 400 req/min general; 100 req/min segment reads; 15 req/min segment
  writes. We only read general list endpoints. 429s carry `Retry-After`.

## List endpoints

| Schema     | v3 path / key / PK                          | 2026-03-15 path / key / PK                          | Partition (stable) |
| ---------- | ------------------------------------------- | --------------------------------------------------- | ------------------ |
| contacts   | `/contacts` / `contacts` / `contactID`      | `/contacts` / `contacts` / `id`                     | `createdAt`        |
| campaigns  | `/campaigns` / `campaign` / `campaignID`    | `/campaigns` / `campaigns` / `id`                   | `createdAt`        |
| carts      | `/carts` / `carts` / `cartID`               | — (write-only events)                               | `createdAt`        |
| orders     | `/orders` / `orders` / `orderID`            | — (write-only events)                               | `createdAt`        |
| products   | `/products` / `products` / `productID`      | `/products` / `products` / `id`                     | `createdAt`        |
| categories | `/categories` / `categories` / `categoryID` | `/product-categories` / `categories` / `categoryID` | —                  |

v3 endpoint existence was confirmed against the live API (all return non-404 without a key).
v3 response array keys follow the plural `<resource>` convention **except `/campaigns`, which
nests rows under the singular `campaign`** (confirmed against the live response body).
2026-03-15 shapes come from Omnisend's reference and its "Migrate from v3 to v2026-03-15" guide.
Other 2026-03-15 changes visible in synced rows: product and variant prices are floats in the
store currency (v3: integer cents), product `images` are URL strings, and campaign statistics
moved off the campaign object into the Analytics API.

## Sync mode

All endpoints ship **full refresh (replace)**.

Omnisend documents `updatedAtFrom` as a server-side filter on `/contacts`, but with hard
restrictions (it cannot be combined with `email`, `phone`, `status`, `segmentID`, or
`tag`). The skill requires confirming a server-side timestamp filter actually filters via
a live curl smoke test (future-date cutoff) before advertising incremental sync. Without
API credentials to run that check, we conservatively ship full refresh everywhere. Once a
key is available, `/contacts` is the candidate to flip to incremental on `updatedAt`.

## Caveats

- `/orders` (v3 only): orders that Omnisend auto-syncs from e-commerce platforms (Shopify,
  BigCommerce, WooCommerce) are **not** exposed through v3 — only orders pushed via the
  API are returned.
