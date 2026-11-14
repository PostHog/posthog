# Vultr API inventory

Source: Vultr API v2 (<https://www.vultr.com/api/>), cross-checked against the official
[govultr](https://github.com/vultr/govultr) Go client for exact response shapes and field names.

- **Base URL:** `https://api.vultr.com` (single global host, no regional variants).
- **Auth:** `Authorization: Bearer <api_key>`. One personal access token per account, generated in the
  customer portal (**Account > API**). Grants full account access (no per-product scopes). The portal
  offers an IP access-control list, so a customer may need to allowlist PostHog egress IPs.
- **Pagination:** cursor in the response body at `meta.links.next` (empty string when exhausted),
  replayed as the `cursor` query param. Page size via `per_page` (default 100, max 500).
- **Rate limit:** ~30 req/s per source IP; HTTP 429 above that.
- **Incremental sync:** none. No list endpoint accepts an updated-since / created-since filter, and
  there are no webhooks. All endpoints are full-refresh (`write_disposition="replace"`).

## Endpoints

| Schema name           | Path                      | Response array key | Primary key | Stable date field |
| --------------------- | ------------------------- | ------------------ | ----------- | ----------------- |
| `instances`           | `/v2/instances`           | `instances`        | `id`        | `date_created`    |
| `bare_metals`         | `/v2/bare-metals`         | `bare_metals`      | `id`        | `date_created`    |
| `kubernetes_clusters` | `/v2/kubernetes/clusters` | `vke_clusters`     | `id`        | `date_created`    |
| `block_storage`       | `/v2/blocks`              | `blocks`           | `id`        | `date_created`    |
| `snapshots`           | `/v2/snapshots`           | `snapshots`        | `id`        | `date_created`    |
| `load_balancers`      | `/v2/load-balancers`      | `load_balancers`   | `id`        | `date_created`    |
| `managed_databases`   | `/v2/databases`           | `databases`        | `id`        | `date_created`    |
| `users`               | `/v2/users`               | `users`            | `id`        | (none)            |
| `billing_history`     | `/v2/billing/history`     | `billing_history`  | `id`        | `date`            |
| `invoices`            | `/v2/billing/invoices`    | `billing_invoices` | `id`        | `date`            |
| `regions`             | `/v2/regions`             | `regions`          | `id`        | (none)            |
| `plans`               | `/v2/plans?type=all`      | `plans`            | `id`        | (none)            |
| `bare_metal_plans`    | `/v2/plans-metal`         | `plans_metal`      | `id`        | (none)            |

All `id` values are unique per account, so `["id"]` is a table-wide unique primary key on every
top-level endpoint. `id` is an integer on the billing endpoints and a string elsewhere.
Region and plan ids are global Vultr catalog ids (`ewr`, `vc2-1c-1gb`, `vbm-4c-32gb`), the values the `region` and `plan` columns of the resource tables hold.
The OpenAPI schema names the bare metal plan array `plans`, but its own example and the govultr client use `plans_metal`.

## Fan-out endpoints

| Schema name          | Path                                     | Parent      | Response key    | Primary key                   |
| -------------------- | ---------------------------------------- | ----------- | --------------- | ----------------------------- |
| `invoice_items`      | `/v2/billing/invoices/{invoice-id}/items` | `invoices`  | `invoice_items` | `invoice_id`, `line_number`   |
| `instance_bandwidth` | `/v2/instances/{instance-id}/bandwidth`   | `instances` | `bandwidth`     | `instance_id`, `date`         |

- `invoice_items` uses the same `meta.links.next` cursor as the list endpoints. Line items have no id,
  so `vultr.py` adds `line_number`, the item's position on its invoice in response order. Both tables are
  full refresh, so the key only has to be unique within one run.
- `instance_bandwidth` is not paginated. Its `bandwidth` value is an object keyed by UTC date
  (`{"2020-07-25": {"incoming_bytes": ..., "outgoing_bytes": ...}}`), and `vultr.py` turns each date into
  one row. The API returns a rolling window of recent days, so days older than the window drop out on the
  next full refresh. An instance destroyed between the instance listing and its bandwidth fetch returns
  404, which the child request ignores.

## Sensitive fields

Some list objects embed live credentials for the resource they describe:
instance and bare-metal objects carry `default_password`,
and managed-database objects carry the admin `password` plus, for Kafka, `access_key` / `access_cert` (sometimes nested under credential sub-objects).
`vultr.py` strips these fields (`SECRET_FIELD_NAMES`) from every row at any depth before it is written to the warehouse,
and the source opts out of HTTP sample capture so raw responses never land in captured samples either.
When adding an endpoint, extend `SECRET_FIELD_NAMES` if its objects expose any new credential-bearing fields.

## Verification note

The endpoint paths, response wrapper keys, and field names above were verified against the govultr
client structs (`instance.go`, `bare_metal_server.go`, `kubernetes.go`, `block_storage.go`,
`snapshot.go`, `load_balancer.go`, `database.go`, `user.go`, `billing.go`, `region.go`, `plan.go`,
`instance.go`) and the API reference.
Live-curl verification against the API was not possible without an account API key; the full-refresh
design is conservative and does not depend on any silently-ignored query params (we send only
`per_page` and the paginator's `cursor`).
