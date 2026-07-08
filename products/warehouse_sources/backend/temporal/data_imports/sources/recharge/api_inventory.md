# Recharge API inventory

Source: Recharge Payments — subscription management for e-commerce.

- **API version:** `2021-11` (sent via `X-Recharge-Version` header).
- **Base URL:** `https://api.rechargeapps.com`
- **Auth:** API token in the `X-Recharge-Access-Token` header (read scopes per resource).
- **Docs:** <https://developer.rechargepayments.com/2021-11>
- **Pagination:** cursor-based. List responses return `next_cursor` / `previous_cursor` in
  the body. Following a cursor accepts **only** `cursor` + `limit` — the original sort and
  filters are baked into the cursor (re-sending them returns a 422). `limit` max is 250.
- **Incremental:** server-side `updated_at_min` / `created_at_min` filters (ISO 8601, no
  offset). We sort `<field>-asc` so the pipeline watermark advances monotonically.
- **Rate limiting:** leaky bucket — 40 request burst, ~2 req/s sustained. 429s are retried
  with exponential backoff.

> ⚠️ **Unverified against a live store.** Endpoint params below come from the public 2021-11
> docs; they were not curl-verified during implementation (no test credentials). Treat the
> incremental-filter and response-shape assumptions as conservative until confirmed against a
> real account.

## Endpoints

| Schema            | Path               | Primary key | Partition key | Incremental | Notes                                                                              |
| ----------------- | ------------------ | ----------- | ------------- | ----------- | ---------------------------------------------------------------------------------- |
| `customers`       | `/customers`       | `id`        | `created_at`  | ✅          |                                                                                    |
| `subscriptions`   | `/subscriptions`   | `id`        | `created_at`  | ✅          |                                                                                    |
| `orders`          | `/orders`          | `id`        | `created_at`  | ✅          |                                                                                    |
| `charges`         | `/charges`         | `id`        | `created_at`  | ✅          | 90-day retention for `processed_at` filtering (we use `updated_at`/`created_at`).  |
| `addresses`       | `/addresses`       | `id`        | `created_at`  | ✅          |                                                                                    |
| `discounts`       | `/discounts`       | `id`        | `created_at`  | ✅          |                                                                                    |
| `onetimes`        | `/onetimes`        | `id`        | `created_at`  | ✅          |                                                                                    |
| `products`        | `/products`        | `id`        | `created_at`  | ➖ full     | 2021-11 list endpoint takes only cursor + `limit`/`ids` — no `sort_by` or `*_min`. |
| `payment_methods` | `/payment_methods` | `id`        | `created_at`  | ✅          | Requires Recharge Pro / Custom plan.                                               |
| `collections`     | `/collections`     | `id`        | `created_at`  | ➖ full     | Server-side timestamp filter not reliably documented — full refresh.               |

## Possible future work

- **Webhooks.** Recharge supports programmatically managed webhooks (`/webhooks`) with HMAC
  validation via `X-Recharge-Hmac-Sha256` (signed with the API client secret). Recharge
  webhooks are **per-topic** (one webhook per `subscription/created`, `charge/created`, …),
  which doesn't map cleanly onto the one-webhook-per-source `create_webhook` / `delete_webhook`
  contract — so realtime webhook ingestion is intentionally deferred from this initial alpha.
- **Metafields / plan-specific resources** (bundle selections, credit adjustments) require a
  fan-out or a Pro/Custom plan and are omitted from the initial endpoint set.
