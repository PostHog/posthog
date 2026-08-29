# Shortcut API v3 — endpoint inventory

Base URL: `https://api.app.shortcut.com/api/v3`
Auth: `Shortcut-Token: <token>` header (workspace-scoped token; token dies if the user leaves the workspace).
Rate limit: 200 requests/minute → `429` on excess (no documented rate-limit response headers).

Derived from the authoritative v3 OpenAPI spec (`https://developer.shortcut.com/api/rest/v3/shortcut.openapi.json`).

> **Verification gap:** these notes come from the OpenAPI spec only. We did not have a live workspace
> token to curl-verify behavior (per the implementing-warehouse-sources skill). The flat-list facts below
> are low-risk (the spec defines no filter/pagination params at all). The one item to revisit once a token
> is available is the `stories` incremental filter (see below).

## Flat list endpoints (full refresh)

Each returns the **entire collection in a single un-paginated JSON array** and accepts **no server-side
timestamp filter** — so they are full-refresh only. All carry `created_at` (stable, used as the partition
key) and `updated_at`.

| Schema           | Path                | PK `id` type  |
| ---------------- | ------------------- | ------------- |
| members          | `/members`          | string (UUID) |
| groups           | `/groups`           | string (UUID) |
| projects         | `/projects`         | integer       |
| workflows        | `/workflows`        | integer       |
| epics            | `/epics`            | integer       |
| iterations       | `/iterations`       | integer       |
| labels           | `/labels`           | integer       |
| categories       | `/categories`       | integer       |
| objectives       | `/objectives`       | integer       |
| custom_fields    | `/custom-fields`    | string (UUID) |
| files            | `/files`            | integer       |
| linked_files     | `/linked-files`     | integer       |
| repositories     | `/repositories`     | integer       |
| entity_templates | `/entity-templates` | string (UUID) |

`primary_keys=["id"]` works for all (the field name is uniform; only the value type differs).

## stories (incremental)

There is **no top-level `GET /stories`** list endpoint. Stories are fetched via **`POST /stories/search`**
("Query Stories"), which accepts structured server-side filters including `created_at_start` /
`updated_at_start` and returns a **plain JSON array of `StorySlim`** (no pagination wrapper). We map the
user's chosen incremental field to the matching `*_start` filter.

- Incremental field options: `updated_at` (default) and `created_at`.
- Partition key: `created_at`.

**An empty body returns zero stories.** The request must carry at least one filter, so every request sets a
`created_at_start` floor — an epoch floor (`1970-01-01T00:00:00Z`) on full refresh and the first incremental
run, or the real cursor when the user picks `created_at` incremental.

**The endpoint caps each response and offers no pagination.** The paginated search variant (`GET
/search/stories`) documents that only the first 1000 matches are retrievable; the old POST endpoint behaves
the same way. We page past the cap by advancing `created_at_start` to the newest `created_at` in a full
response and refetching, relying on the endpoint returning stories in `created_at` order. Merge dedup on `id`
drops the boundary stories re-read at the floor.

**Revisit with a live token:** confirm that (a) `updated_at_start` filters server-side rather than being
silently ignored, (b) the accepted date format (we send RFC 3339 `...Z`), and (c) the exact result cap and
whether responses are ordered by `created_at`.

## Webhooks (deferred)

Shortcut supports a single programmatic "generic integration" webhook
(`POST`/`GET`/`DELETE /integrations/webhook[/{id}]`) with optional HMAC-SHA-256 `Payload-Signature`
verification. It is **not** wired up here because the webhook payload is a **change log** (`actions[]` with
partial diffs and `entity_type`), not full entity records — it doesn't map onto the per-table row model the
`WebhookSource` base expects without an extra per-event entity refetch, and we couldn't validate the payload
shape against a live workspace. Pull-based sync is the alpha scope.
