# Pipedrive API inventory

Reference: <https://developers.pipedrive.com/docs/api/v1>

## Auth

- API token, passed via the `x-api-token` request header (the query-param form leaks the
  token into logged URLs, so we use the header instead).
- All requests go to the company domain: `https://{company_domain}.pipedrive.com`.
  v1 resources live under `/api/v1/...`, v2 resources under `/api/v2/...`.

## Pagination

- **v2 (cursor):** `?limit=500&cursor=<cursor>`. Response carries
  `additional_data.next_cursor`; a falsy/absent cursor ends the chain.
- **v1 (offset):** `?start=<n>&limit=500`. Response carries
  `additional_data.pagination.{more_items_in_collection,next_start}`; pagination object is
  absent for single-page endpoints (e.g. `users`).
- Both wire styles return rows under the top-level `data` key.

## Endpoints synced

| Schema              | Path                         | Pagination | Primary key | Partition key |
| ------------------- | ---------------------------- | ---------- | ----------- | ------------- |
| deals               | `/api/v2/deals`              | cursor     | id          | add_time      |
| persons             | `/api/v2/persons`            | cursor     | id          | add_time      |
| organizations       | `/api/v2/organizations`      | cursor     | id          | add_time      |
| products            | `/api/v2/products`           | cursor     | id          | add_time      |
| pipelines           | `/api/v2/pipelines`          | cursor     | id          | add_time      |
| stages              | `/api/v2/stages`             | cursor     | id          | add_time      |
| activities          | `/api/v1/activities`         | offset     | id          | add_time      |
| notes               | `/api/v1/notes`              | offset     | id          | add_time      |
| leads               | `/api/v1/leads`              | offset     | id          | add_time      |
| users               | `/api/v1/users`              | offset     | id          | —             |
| deal_fields         | `/api/v1/dealFields`         | offset     | id          | —             |
| person_fields       | `/api/v1/personFields`       | offset     | id          | —             |
| organization_fields | `/api/v1/organizationFields` | offset     | id          | —             |

## Incremental sync

Shipped as **full refresh for every endpoint**. Pipedrive's v2 collection endpoints
document an `updated_since` (RFC 3339) server-side filter plus `sort_by=update_time`, which
would make those endpoints incremental — but the implementing-warehouse-sources skill
requires a live curl smoke test (future-date cutoff) to confirm the filter actually filters
before enabling it, and no Pipedrive credentials were available at implementation time. The
v1 collection endpoints have no per-resource `updated_after` filter at all (only the 30-day
`/recents` endpoint), so they would stay full refresh regardless. Enabling incremental on the
v2 endpoints is a verified follow-up.
