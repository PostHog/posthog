# Amplitude API inventory

Auth: HTTP Basic with the project **API key** + **secret key** (`base64(api_key:secret_key)`).
Regional hosts: US `https://amplitude.com`, EU `https://analytics.eu.amplitude.com`.

Verified with unauthenticated / bad-credential curls (no live project credentials were available):

- No credentials → `401`.
- Bad credentials → `403` with body `{"error": {..., "metadata": {"details": "Invalid API Key"}}}`.
- Both US and EU hosts reachable; both `401` without auth.

So `401`/`403` are permanent auth failures (wired into `get_non_retryable_errors`).

## Endpoints

### `events` — `/api/2/export`

- Grain: one event. Primary key: `uuid`. Sync mode: incremental (append-only).
- Export API. Returns a **zip of gzipped JSON-lines** archives, not a JSON body.
- `start`/`end` are hour-granular `YYYYMMDDTHH` and filter on **server upload time**.
- ~2h ingestion latency; max 365-day window; max 4GB per response.
- Returns **404 (not an empty 200)** for windows with no events.

### `cohorts` — `/api/3/cohorts`

- Grain: one cohort. Primary key: `id`. Sync mode: full refresh.
- Behavioral Cohorts API. Response wrapped in `{"cohorts": [...]}`.

### `annotations` — `/api/2/annotations`

- Grain: one annotation. Primary key: `id`. Sync mode: full refresh.
- Dashboard REST API. Response wrapped in `{"data": [...]}`.

### `event_types` — `/api/2/taxonomy/event`

- Grain: one event type in the tracking plan. Primary key: `event_type`. Sync mode: full refresh.
- Taxonomy API. Response wrapped in `{"success": true, "data": [...]}`.
- Hidden events are omitted; deleted ones need `?showDeleted=true`, which we do not pass.

### `event_properties` — `/api/2/taxonomy/event-property`

- Grain: one property definition on one event type. Primary key: `["event_type", "event_property"]`.
  Sync mode: full refresh.
- Only lists properties for a single event type at a time, so the table is built by fanning out over
  `/api/2/taxonomy/event` and querying `?event_type=<name>` per event type. Each child row is stamped
  with the event type we queried, so the composite key is always populated.
- A property name is only unique within its event type, which is why the key is composite.
- Amplitude answers `400` with `"Not found"` for a parent it cannot resolve; those parents are skipped
  with a warning rather than failing the whole table.

### `user_properties` — `/api/2/taxonomy/user-property`

- Grain: one user property definition. Primary key: `user_property`. Sync mode: full refresh.
- Taxonomy API. Response wrapped in `{"success": true, "data": [...]}`.
- Custom group properties appear with a `gp:` prefix.

### `event_categories` — `/api/2/taxonomy/category`

- Grain: one event category. Primary key: `id`. Sync mode: full refresh.
- Taxonomy API. Response wrapped in `{"success": true, "data": [...]}`.
- Resolves the `category` object carried on each event type.

## Incremental design (events)

The Export API's only server-side filter is the `start`/`end` window on **server upload time**, so
`server_upload_time` is the incremental cursor — an event's `event_time` can be backdated by offline/late
clients, but the window is bounded by when Amplitude received the event. We page forward in 24h windows from
the stored cursor (or a 30-day lookback on first sync) to `now - 2h`, saving the next window start to the
resumable state after each window. Re-fetched windows dedupe on `uuid` via merge semantics. Partitioning uses
the stable `event_time` field.

## Incremental design (taxonomy)

No Taxonomy endpoint documents a timestamp filter, a cursor, or any pagination parameter — each "get all"
call returns the complete array. So all four taxonomy tables are full refresh, and none advertise an
incremental field.

## Unverified (no credentials to curl)

- Exact wrapper keys for `cohorts` (`cohorts`) and `annotations` (`data`) come from the public docs, not a
  live 200 response. `_fetch_list` falls back to treating a bare-list body as the row list if the wrapper
  key is absent.
- Amplitude's Taxonomy docs show `event_type` sent to `/api/2/taxonomy/event-property` as a urlencoded
  request body on a `GET`, while the single-property examples on the same page use a query string. We send
  it as a query string.
- The Export JSON field set (timestamp field names, `uuid` presence) is taken from Amplitude's documented
  export schema. Timestamp normalization tolerates both `%Y-%m-%d %H:%M:%S.%f` and `%Y-%m-%d %H:%M:%S`.
