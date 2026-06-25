# ChartMogul API inventory

- **API:** ChartMogul REST API v1 — <https://dev.chartmogul.com/reference>
- **Base URL:** `https://api.chartmogul.com`
- **Auth:** HTTP Basic. The API key is the username, the password is empty (`auth=(api_key, "")`).
- **Pagination:** cursor-based. List responses wrap rows under a per-resource key and expose
  `has_more` (bool) + `cursor` (opaque string). Pass `?cursor=<cursor>&per_page=200` for the next page;
  stop when `has_more` is `false`.
- **Rate limit:** 40 req/sec globally, max 20 parallel connections (we sync serially per schema).

## Verification status

The pagination, sort order, and `start-date` filter behavior below are taken from the public docs.
They could **not** be smoke-tested with curl against the live API during implementation because no
ChartMogul API key was available in the build environment. The conservative choices (full refresh on
every endpoint except activities; `start-date` server-side filter only on activities) reflect that:
only the activities endpoint documents a genuine server-side date filter, so it is the single endpoint
marked incremental.

## Endpoints

| Schema       | Path               | Data key       | Primary key | Partition key | Incremental                  |
| ------------ | ------------------ | -------------- | ----------- | ------------- | ---------------------------- |
| customers    | `/v1/customers`    | `entries`      | `uuid`      | —             | full refresh (no timestamp)  |
| plans        | `/v1/plans`        | `plans`        | `uuid`      | —             | full refresh                 |
| plan_groups  | `/v1/plan_groups`  | `plan_groups`  | `uuid`      | —             | full refresh                 |
| invoices     | `/v1/invoices`     | `invoices`     | `uuid`      | `date`        | full refresh                 |
| activities   | `/v1/activities`   | `entries`      | `uuid`      | `date`        | `start-date` server filter   |
| data_sources | `/v1/data_sources` | `data_sources` | `uuid`      | `created_at`  | full refresh (not paginated) |

Notes:

- **Customers** expose no update timestamp and no server-side creation/update date filter, so true
  incremental sync is impossible — Airbyte's connector also only supports full refresh here.
- **Activities** is the only endpoint with a documented server-side `start-date` / `end-date` filter,
  and is documented to return rows in ascending chronological order, so it is synced incrementally on
  the `date` field with `sort_mode="asc"`.
- **data_sources** returns the full list in a single response (no cursor), so it is fetched once.
