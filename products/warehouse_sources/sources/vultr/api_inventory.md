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

All `id` values are unique per account, so `["id"]` is a table-wide unique primary key on every
endpoint (no fan-out children). `id` is an integer on the billing endpoints and a string elsewhere.

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
`snapshot.go`, `load_balancer.go`, `database.go`, `user.go`, `billing.go`) and the API reference.
Live-curl verification against the API was not possible without an account API key; the full-refresh
design is conservative and does not depend on any silently-ignored query params (we send only
`per_page` and the paginator's `cursor`).
