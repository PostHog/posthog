# Persona API inventory

Reference: <https://docs.withpersona.com/reference> · Base URL: `https://api.withpersona.com/api/v1`

- **Auth:** `Authorization: Bearer <api_key>`. Sandbox and production use separate keys.
- **Format:** JSON:API — each record is `{ "type", "id", "attributes": {...} }`; lists wrap rows in `data`
  with a `links.next` cursor URL (null on the last page).
- **Pagination:** cursor via `page[after]=<object id>`, `page[size]` 1–100 (default 10).
- **Ordering:** reverse-chronological (newest first) on `created-at` → we sync with `sort_mode="desc"`.
- **Incremental:** server-side `filter[created-at-start]` / `filter[created-at-end]` on the immutable
  `created-at`. No `updated-at` filter exists, so only `created_at` is advertised as an incremental cursor
  (updates to existing records are captured on full refresh, not incrementally).
- **Rate limit:** 300 req/min; `429` with reset headers on excess (handled by retry + backoff).

## Endpoints synced

| Endpoint            | Path                | Sync mode      | Primary key | Partition key |
| ------------------- | ------------------- | -------------- | ----------- | ------------- |
| `inquiries`         | `/inquiries`        | Incremental    | `id`        | `created_at`  |
| `accounts`          | `/accounts`         | Incremental    | `id`        | `created_at`  |
| `cases`             | `/cases`            | Incremental    | `id`        | `created_at`  |
| `transactions`      | `/transactions`     | Incremental    | `id`        | `created_at`  |
| `events`            | `/events`           | Append only    | `id`        | `created_at`  |
| `inquiry_templates` | `/inquiry-templates`| Full refresh   | `id`        | —             |

Object ids are globally unique and type-prefixed (`inq_`, `acc_`, `case_`, `txn_`, `evt_`, `itmpl_`), so
`id` is a safe standalone primary key. Persona kebab-case attributes (`created-at`) normalize to the
snake_case warehouse columns (`created_at`).

## Verification note

Endpoint paths and semantics are taken from the public Persona docs. They could **not** be curl-verified
against the live API because Persona's auth middleware returns `401` for every request (including bogus
paths) without a valid key, so route existence and the cross-page behavior of `filter[created-at-start]`
were not confirmed empirically. As a safeguard the paginator stops client-side once rows predate the
incremental watermark (newest-first ordering), so even if the created-at filter failed to persist past
page one we would not re-walk full history on every sync.
