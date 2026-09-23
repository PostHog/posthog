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

**`StorySlim` omits `description` unless asked.** The field is optional in the response schema, so every request
sets `includes_description: true` to get the `description` column the canonical schema advertises.

**The endpoint documents no result cap, no result order, and no pagination.**
The v3 OpenAPI spec gives `POST /stories/search` (`queryStories`) an empty parameter list and a bare `StorySlim` array response.
The "first 1000 matches" limit and the ranking-decay ordering note belong to the separate `GET /search/stories` endpoint, so neither is assumed here.
We read stories in closed `created_at_start` / `created_at_end` windows instead, which relies only on filters the spec documents:
a response with `STORY_SEARCH_SPLIT_THRESHOLD` or more stories is treated as possibly truncated and its window is split in half and fetched again;
once every window is fetched, the largest accepted windows are fetched again in halves, and when the halves hold more distinct stories than the parent response did, the endpoint truncated at that count and the threshold drops to it.
Row order never matters. Neighbouring windows overlap by a second or two, so no story is lost whether either bound is inclusive or exclusive, and `_dedupe_pages_by_id` drops stories read twice.
A window under three seconds wide cannot split; if it still hits the threshold, the sync logs a warning that stories in those seconds may be missing.

**Revisit with a live token:** confirm that (a) `updated_at_start` filters server-side rather than being
silently ignored, (b) the accepted date format (we send RFC 3339 `...Z`), and (c) whether the `created_at_*`
bounds are inclusive (the windows overlap either way, so this only affects request count).

## Webhooks (deferred)

Shortcut supports a single programmatic "generic integration" webhook
(`POST`/`GET`/`DELETE /integrations/webhook[/{id}]`) with optional HMAC-SHA-256 `Payload-Signature`
verification. It is **not** wired up here because the webhook payload is a **change log** (`actions[]` with
partial diffs and `entity_type`), not full entity records — it doesn't map onto the per-table row model the
`WebhookSource` base expects without an extra per-event entity refetch, and we couldn't validate the payload
shape against a live workspace. Pull-based sync is the alpha scope.
