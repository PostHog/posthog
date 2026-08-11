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

| Endpoint            | Path                                    | Sync mode    | Primary key | Partition key        |
| ------------------- | --------------------------------------- | ------------ | ----------- | -------------------- |
| `inquiries`         | `/inquiries`                            | Incremental  | `id`        | `created_at`         |
| `verifications`     | `/inquiries/{id}?include=verifications` | Incremental  | `id`        | `inquiry_created_at` |
| `accounts`          | `/accounts`                             | Incremental  | `id`        | `created_at`         |
| `cases`             | `/cases`                                | Incremental  | `id`        | `created_at`         |
| `transactions`      | `/transactions`                         | Incremental  | `id`        | `created_at`         |
| `events`            | `/events`                               | Append only  | `id`        | `created_at`         |
| `inquiry_templates` | `/inquiry-templates`                    | Full refresh | `id`        | —                    |

Object ids are globally unique and type-prefixed (`inq_`, `ver_`, `acc_`, `case_`, `txn_`, `evt_`,
`itmpl_`), so `id` is a safe standalone primary key. Persona kebab-case attributes (`created-at`)
normalize to the snake_case warehouse columns (`created_at`).

## Verifications are a fan-out, not a list endpoint

Persona's Verifications API exposes no cross-inquiry list — only `GET /verifications/{id}` plus
per-type retrieves ([API index](https://docs.withpersona.com/api-reference/llms.txt)). Related
resources are hydrated with the `include` query parameter, and
[Response Body](https://docs.withpersona.com/serialization) states that `include` **cannot be used on
"list all" endpoints**, so `/inquiries?include=verifications` is not an option either. From API
version `2025-10-27` the `included` array is empty unless `include` is passed explicitly.

So `verifications` walks `/inquiries` like any other list endpoint and re-fetches each inquiry as
`/inquiries/{id}?include=verifications`, reading the rows out of `included`. That costs one extra
request per inquiry in the window, which is why the table is off by default.

Because the window is applied to the inquiry list, the advertised incremental cursor is the parent's
`inquiry_created_at`, not the verification's own `created_at` — filtering the parent list on a child
timestamp would skip inquiries created before the watermark that gained a verification after it.
Retries added to an already-synced inquiry are therefore picked up on a full refresh, consistent with
how this source treats updates elsewhere.

## Verification note

Endpoint paths and semantics are taken from the public Persona docs and the OpenAPI-derived API index
they publish. They could **not** be curl-verified against the live API because Persona's auth
middleware returns `401` for every request (including bogus paths) without a valid key, so route
existence and the cross-page behavior of `filter[created-at-start]` were not confirmed empirically. As a safeguard the paginator stops client-side once rows predate the
incremental watermark (newest-first ordering), so even if the created-at filter failed to persist past
page one we would not re-walk full history on every sync.
