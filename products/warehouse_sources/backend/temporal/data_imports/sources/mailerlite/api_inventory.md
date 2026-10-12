# MailerLite API inventory

Base URL: `https://connect.mailerlite.com/api` (current date-versioned API, released 2022-03-22).
Auth: `Authorization: Bearer <api-key>` (account-wide API key; the simple API-key model has no
granular per-resource scopes). `Accept: application/json`.

## Verified with curl (2026-06-02)

Without a live key only auth behavior and endpoint existence were verifiable:

- `GET /subscribers` with no/invalid token → `401 {"message":"Unauthenticated."}`.
- All endpoints below return `401` (not `404`) for an invalid token, confirming the paths exist.

The response **shapes, pagination cursors, and field names below are taken from the public API
docs** and could not be exercised against live data without credentials. Parsing is kept
conservative (follow `links.next`, yield rows verbatim, merge on `id`).

## Endpoints implemented

| Schema          | Path             | Pagination  | Primary key | Partition key |
| --------------- | ---------------- | ----------- | ----------- | ------------- |
| subscribers     | /subscribers     | cursor      | id          | created_at    |
| campaigns       | /campaigns       | page number | id          | created_at    |
| groups          | /groups          | page number | id          | created_at    |
| segments        | /segments        | page number | id          | created_at    |
| fields          | /fields          | page number | id          | (none)        |
| automations     | /automations     | page number | id          | created_at    |
| forms_popup     | /forms/popup     | page number | id          | created_at    |
| forms_embedded  | /forms/embedded  | page number | id          | created_at    |
| forms_promotion | /forms/promotion | page number | id          | created_at    |
| webhooks        | /webhooks        | page number | id          | created_at    |

### Fan-out endpoints

Each child is fetched once per parent row from the parent list, so the parent id is part of the
primary key. A 404 on a child (parent deleted mid-sync) is skipped.

| Schema                       | Path                                                 | Parent                    | Pagination  | Primary key       | Partition key |
| ---------------------------- | ---------------------------------------------------- | ------------------------- | ----------- | ----------------- | ------------- |
| campaign_subscriber_activity | /campaigns/{campaign_id}/reports/subscriber-activity | campaigns (status `sent`) | page number | campaign_id, id   | (none)        |
| group_subscribers            | /groups/{group_id}/subscribers                       | groups                    | cursor      | group_id, id      | created_at    |
| segment_subscribers          | /segments/{segment_id}/subscribers                   | segments                  | cursor      | segment_id, id    | created_at    |
| automation_activity          | /automations/{automation_id}/activity                | automations × status      | page number | automation_id, id | (none)        |

- `campaign_subscriber_activity` sends `include=subscriber`; without it a row carries only its
  counts. Reports exist only for sent campaigns, so the parent list is filtered to `sent`.
- The membership endpoints default `filter[status]` to `active`, so they hold active members only.
- `automation_activity` requires `filter[status]` and takes one value per request, so each
  automation is fetched four times (`active`, `completed`, `canceled`, `failed`). Its `date`
  field moves as a run progresses, so the table is not partitioned.
- The `filter[date_from]` / `filter[date_to]` filters on automation activity don't apply to the
  `active` status, so the table stays full refresh like the rest of the source.

## Pagination

All list endpoints wrap rows in `{"data": [...], "links": {...}, "meta": {...}}`. Both the
cursor-based `subscribers` endpoint and the page-number endpoints expose an absolute next-page URL
at `links.next` (or `null` on the last page), so a single "follow `links.next`" loop covers both.
Page size capped at 100 (default 25); we request `limit=100`.

## Incremental sync

None. The current API exposes **no server-side timestamp filter** (`updated_after`, `since`, etc.)
on any list endpoint — `created_at` / `updated_at` are returned in responses but cannot be filtered
on. A client-side cursor would still page through the entire collection every run, so per the
warehouse-source guidance every endpoint ships **full refresh only** (`supports_incremental=False`).
This matches the Airbyte MailerLite connector, which is also full-refresh only.

Pagination is still resumable (the source is a `ResumableSource`): the next-page URL is persisted to
Redis after each page so Temporal can resume mid-collection after a heartbeat timeout.

## API versioning

The new API is date-versioned via the optional `X-Version: YYYY-MM-DD` header and serves the
latest version when it's absent. Framework version `v1` sends no header (legacy default-tracking
behaviour); `v2` — the default for new sources — pins `X-Version: 2038-01-19`, the version-pin
value MailerLite's docs and official SDK publish. Mapping lives in `settings.API_VERSION_HEADERS`.

## Rate limits

120 requests/minute globally (5/minute for bulk import/upsert, which this source does not use).
`429` responses are retried with exponential backoff via `tenacity`.
