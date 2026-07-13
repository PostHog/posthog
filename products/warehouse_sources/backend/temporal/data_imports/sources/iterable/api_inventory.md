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

## Incremental / partitioning notes

- **No verified server-side timestamp filter.** Per the implementing-warehouse-sources skill, a
  client-side cursor that re-reads every page each run is not real incremental, so all endpoints
  ship full refresh. Airbyte/Fivetran sync `templates` incrementally on `updatedAt` (via the
  `startDateTime`/`endDateTime` params) and `users` on `profileUpdatedAt`, but those filters
  could not be curl-verified without live credentials. Revisit once a key is available.
- **No partition key.** Iterable timestamps (`createdAt`, `updatedAt`) are epoch **milliseconds**.
  The datetime partitioner (`pipelines/pipeline/utils.py`) treats integer partition values as
  epoch **seconds** (`datetime.fromtimestamp`), so partitioning on these fields would map every
  row into far-future buckets (and overflow). Skipped rather than ship an unstable/broken config.

## Deferred (not implemented)

- **Export API** (`/api/export/data.json`, `/api/export/userEvents`) — the high-volume event and
  user streams (email/push/SMS/in-app sends, opens, clicks, bounces, purchases, custom events,
  `users`). Async jobId polling + NDJSON streaming + strict 4 req/min rate limit + adaptive
  date-range slicing. Needs live-credential verification before implementing.
- **Webhooks** — Iterable supports system webhooks for realtime events, but they're configured
  in the UI only (not programmatically), and the payload shapes need verification, so no
  `WebhookSource` integration is included yet.
