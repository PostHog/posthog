# ChartMogul API inventory

- **API:** ChartMogul REST API v1 — <https://dev.chartmogul.com/reference>
- **Base URL:** `https://api.chartmogul.com`
- **Auth:** HTTP Basic. The API key is the username, the password is empty (`auth=(api_key, "")`).
- **Pagination:** cursor-based. List responses wrap rows under a per-resource key and expose
  `has_more` (bool) + `cursor` (opaque string). Pass `?cursor=<cursor>&per_page=200` for the next page;
  stop when `has_more` is `false`.
- **Rate limit:** 40 req/sec globally, max 20 parallel connections (we sync serially per schema).

## Verification status

The pagination, sort order, and filter behavior below are taken from the public docs.
They could **not** be smoke-tested with curl against the live API during implementation because no
ChartMogul API key was available in the build environment. The conservative choices (full refresh on
every endpoint except activities; `start-date` server-side filter only on activities) reflect that:
only the activities endpoint documents a genuine server-side date filter on a field that cannot move.

## Endpoints

| Schema                 | Path                                          | Data key              | Primary key              | Partition key | Incremental                  |
| ---------------------- | --------------------------------------------- | --------------------- | ------------------------ | ------------- | ---------------------------- |
| customers              | `/v1/customers`                               | `entries`             | `uuid`                   | —             | full refresh (no timestamp)  |
| customer_subscriptions | `/v1/customers/{customer_uuid}/subscriptions` | `entries`             | `customer_uuid` + `uuid` | —             | full refresh (no filter)     |
| plans                  | `/v1/plans`                                   | `plans`               | `uuid`                   | —             | full refresh                 |
| plan_groups            | `/v1/plan_groups`                             | `plan_groups`         | `uuid`                   | —             | full refresh                 |
| invoices               | `/v1/invoices`                                | `invoices`            | `uuid`                   | `date`        | full refresh                 |
| activities             | `/v1/activities`                              | `entries`             | `uuid`                   | `date`        | `start-date` server filter   |
| subscription_events    | `/v1/subscription_events`                     | `subscription_events` | `id`                     | `created_at`  | full refresh (no range)      |
| opportunities          | `/v1/opportunities`                           | `entries`             | `uuid`                   | `created_at`  | full refresh (no range)      |
| metrics                | `/v1/metrics/all`                             | `entries`             | `date`                   | `date`        | full refresh (recalculated)  |
| metrics_mrr            | `/v1/metrics/mrr`                             | `entries`             | `date`                   | `date`        | full refresh (recalculated)  |
| data_sources           | `/v1/data_sources`                            | `data_sources`        | `uuid`                   | `created_at`  | full refresh (not paginated) |

Notes:

- **Customers** expose no update timestamp and no server-side creation/update date filter, so true
  incremental sync is impossible — Airbyte's connector also only supports full refresh here.
- **customer_subscriptions** is only reachable per customer, so it fans out over the customers
  listing. The subscription object carries no reference back to its customer, so the parent's `uuid`
  is injected as `customer_uuid`: without it the rows cannot be joined to anything, and the docs do
  not commit to `uuid` being unique outside its own customer, so it is part of the primary key. The
  child accepts only `cursor` and `per_page`, with no filters, so it is full refresh. Every date on the
  object is hyphenated (`start-date`, `end-date`), unlike every partition key this source uses, so
  the table is left unpartitioned.
- **Activities** is the only endpoint with a documented server-side `start-date` / `end-date` filter,
  and is documented to return rows in ascending chronological order, so it is synced incrementally on
  the `date` field with `sort_mode="asc"`.
- **subscription_events** takes `event_date` and `effective_date` as **exact-timestamp** filters, not
  ranges, so there is nothing for an incremental cursor to bind to. Its id is ChartMogul's own
  integer, not a uuid. `created_at` is the only date on the object that cannot move, so it is the
  partition key.
- **Opportunities** filters only on `estimated_close_date_on_or_after` / `_on_or_before`, and a deal's
  estimated close date moves in either direction, so it cannot serve as an incremental cursor.
- **metrics / metrics_mrr** return one entry per interval and take no pagination params, so each is a
  single request. Both require `start-date` and `end-date`, built at request time from a floor set
  well before ChartMogul existed (so no imported billing history is cut off) to the sync date, at
  `interval=day`, because a warehouse query can roll days up to months but not the reverse. They are full
  refresh despite that range filter being a real server-side one: ChartMogul recalculates past
  intervals when invoices and events are backfilled or edited, so an incremental window anchored on
  the newest `date` would freeze every revised historical value. A full refresh is the same single
  request, so the incremental option would save nothing and lose the revisions.
- **data_sources** returns the full list in a single response (no cursor), so it is fetched once.

## Endpoints deliberately not synced

- `/v1/metrics/arr`, `/arpa`, `/asp`, `/ltv`, `/customer-count`, `/churn-rate`, `/mrr-churn-rate`
  each return entries of `{date, <one metric>, percentage-change}`. `/v1/metrics/all` already carries
  every one of those metrics as a column, with its own `*-percentage-change`, so syncing them would
  add seven single-metric tables duplicating the `metrics` table and seven requests per sync.
  `/v1/metrics/mrr` is the one sibling kept, because it is the only one with columns `/all` does not
  have: the MRR movement breakdown (`mrr-new-business`, `mrr-expansion`, `mrr-contraction`,
  `mrr-churn`, `mrr-reactivation`).
