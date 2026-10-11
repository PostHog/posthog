# Veeqo API inventory

Source: Veeqo — multichannel ecommerce inventory, order and shipping management (Amazon-owned).

- **API version:** unversioned (no version path segment, header, or param).
- **Base URL:** `https://api.veeqo.com`
- **Auth:** API key in the `x-api-key` header. Keys carry full account access (no scopes) and
  must be enabled by Veeqo support before they appear in account settings. OAuth2 exists but is
  only required for public Appstore apps.
- **Docs:** <https://developers.veeqo.com/api>
- **Pagination:** page-number (`page`, 1-based, + `page_size`). Responses carry
  `X-Total-Count`, `X-Total-Pages-Count`, `X-Page-Index` and `X-Per-Page` headers. Defaults are
  tiny (12 on most endpoints, 10 on warehouses); `/products` documents a max `page_size` of 100,
  the rest document no max — we send 100 everywhere.
- **Incremental:** server-side `updated_at_min` / `created_at_min` (format
  `YYYY-MM-DD HH:MM:SS`) and `since_id` filters on orders and products. No sort param is
  documented on any list endpoint, so ordering is undeclared — the source uses
  `sort_mode="desc"` semantics (watermark commits only after a successful sync).
- **Rate limiting:** leaky bucket — 5 requests/second sustained with burst capacity up to 100;
  exceeding returns HTTP 429 (retried by the tracked transport honoring `Retry-After`).
- **Response shape:** bare JSON arrays on list endpoints (no wrapper key); enforced with
  `data_selector_required` so a shape change fails loud.

> ⚠️ **Unverified against a live account.** Endpoint params below come from the public docs at
> developers.veeqo.com; they were not curl-verified during implementation (Veeqo API keys must
> be enabled by their support team, and no test credentials were available). Only the 401 error
> shape was probed live. Treat the incremental-filter and pagination assumptions as
> conservative until confirmed against a real account.

## Endpoints

| Schema             | Path                | Primary key | Partition key | Incremental | Notes                                                           |
| ------------------ | ------------------- | ----------- | ------------- | ----------- | --------------------------------------------------------------- |
| `orders`           | `/orders`           | `id`        | `created_at`  | ✅          | `updated_at_min` / `created_at_min` / `since_id`.               |
| `products`         | `/products`         | `id`        | `created_at`  | ✅          | `updated_at_min` / `created_at_min` / `since_id`; max page 100. |
| `customers`        | `/customers`        | `id`        | —             | ➖ full     | Only `page`/`page_size`/`query`/`customer_type` documented.     |
| `purchase_orders`  | `/purchase_orders`  | `id`        | `created_at`  | ➖ full     | `show_complete=true` sent so completed POs are included.        |
| `suppliers`        | `/suppliers`        | `id`        | —             | ➖ full     |                                                                 |
| `warehouses`       | `/warehouses`       | `id`        | —             | ➖ full     |                                                                 |
| `stores`           | `/channels`         | `id`        | —             | ➖ full     | Veeqo calls stores "channels" in the API.                       |
| `tags`             | `/tags`             | `id`        | —             | ➖ full     | No pagination params documented; fetched as a single page.      |
| `delivery_methods` | `/delivery_methods` | `id`        | `created_at`  | ➖ full     |                                                                 |

## Possible future work

- **Nested resources.** Order allocations/shipments, product sellables and per-warehouse stock
  entries are nested in the orders/products payloads today; dedicated fan-out endpoints
  (`/sellables/{id}/warehouses/{id}/stock_entry`) exist if flattened tables are ever needed.
- **Webhooks.** Veeqo has no webhook API, so `WebhookSource` is not applicable.
