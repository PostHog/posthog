# Iterable API inventory

Reference for the `iterable` data warehouse source. Iterable is a cross-channel marketing
automation platform (email, SMS, push, in-app). REST/JSON API.

- **Docs:** <https://api.iterable.com/api/docs> (US), <https://api.eu.iterable.com/api/docs> (EU)
- **Base URLs:** `https://api.iterable.com` (US), `https://api.eu.iterable.com` (EU). A key only
  works against the data center that issued it.
- **Auth:** `Api-Key: <server-side key>` header. (JWT-enabled keys use `Authorization: Bearer <jwt>`
  — not currently supported here.)
- **Rate limits:** ~100 req/s for most list endpoints; the Export API is far stricter
  (~4 req/min per project, max 4 concurrent exports per org). Returns `429` when exceeded.
- **Errors:** JSON envelope `{"code": "...", "msg": "...", "params": {...}}`. `401 BadApiKey`,
  `403`, `404`, `429 RateLimitExceeded`, `5xx`.

## Implemented endpoints (full refresh)

| Schema          | Path                | Data key       | Primary key  |
| --------------- | ------------------- | -------------- | ------------ |
| `campaigns`     | `/api/campaigns`    | `campaigns`    | `id`         |
| `channels`      | `/api/channels`     | `channels`     | `id`         |
| `lists`         | `/api/lists`        | `lists`        | `id`         |
| `message_types` | `/api/messageTypes` | `messageTypes` | `id`         |
| `templates`     | `/api/templates`    | `templates`    | `templateId` |

These return their full result set in a single response wrapped under the named array. The
transport still follows `nextPageUrl` if present (with a `MAX_PAGES` safety cap) so the source
keeps working if Iterable paginates large result sets in the future.

## Fan-out endpoints (full refresh)

| Schema             | Path                                                   | Response                      | Primary key       |
| ------------------ | ------------------------------------------------------ | ----------------------------- | ----------------- |
| `campaign_metrics` | `/api/campaigns/metrics?campaignId=…` (100 ids a call) | CSV, one row per campaign     | `id`              |
| `list_users`       | `/api/lists/getUsers?listId=…` (one call per list)     | Plain text, one user per line | `listId`, `email` |

`campaign_metrics` returns lifetime totals. `startDateTime`/`endDateTime` change the aggregation
window rather than filtering rows, so there is no incremental mode.

## Export API endpoints (full refresh or append)

`/api/export/data.json?dataTypeName=…&startDateTime=…&endDateTime=…` streams NDJSON. One table per
`dataTypeName` (every documented type except `unknownSession`): events filter on `createdAt`, the
`users` table on `profileUpdatedAt`. The source walks 30-day windows, waits 15 seconds between
requests (the limit is about 4 a minute per project), and stores the next window start as its resume
state. The cursor field is parsed from `yyyy-MM-dd HH:mm:ss +00:00` into a datetime so it can drive
incremental sync and (for events) monthly partitioning.

- Rows carry no unique id, so the tables support append, not merge.
- First sync and full refresh start 365 days back.
- Tables start disabled because they share the project's export rate limit.

## Incremental / partitioning notes

- **No verified server-side timestamp filter on the list endpoints.** Per the
  implementing-warehouse-sources skill, a client-side cursor that re-reads every page each run is
  not real incremental, so the list endpoints ship full refresh. Airbyte/Fivetran sync `templates` incrementally on `updatedAt` (via the
  `startDateTime`/`endDateTime` params) and `users` on `profileUpdatedAt`, but those filters
  could not be curl-verified without live credentials. Revisit once a key is available.
- **No partition key on the list endpoints.** Iterable timestamps (`createdAt`, `updatedAt`) are epoch **milliseconds**.
  The datetime partitioner (`pipelines/core/partitioning.py`) treats integer partition values as
  epoch **seconds** (`datetime.fromtimestamp`), so partitioning on these fields would map every
  row into far-future buckets (and overflow). Skipped rather than ship an unstable/broken config.

## Deferred (not implemented)

- **Per-user endpoints** (`/api/export/userEvents`, `/api/users/getSentMessages`) — both need an
  `email` or `userId` on every call, so a table would mean one request per user. The same events
  and sends are in the Export API tables above.
- **Async export jobs** (`/api/export/start`) — the synchronous `data.json` stream covers the same
  data types without job polling.
- **Webhooks** — Iterable supports system webhooks for realtime events, but they're configured
  in the UI only (not programmatically), and the payload shapes need verification, so no
  `WebhookSource` integration is included yet.
