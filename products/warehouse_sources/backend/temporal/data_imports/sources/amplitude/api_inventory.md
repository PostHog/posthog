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

## Incremental design (events)

The Export API's only server-side filter is the `start`/`end` window on **server upload time**, so
`server_upload_time` is the incremental cursor — an event's `event_time` can be backdated by offline/late
clients, but the window is bounded by when Amplitude received the event. We page forward in 24h windows from
the stored cursor (or a 30-day lookback on first sync) to `now - 2h`, saving the next window start to the
resumable state after each window. Re-fetched windows dedupe on `uuid` via merge semantics. Partitioning uses
the stable `event_time` field.

## Unverified (no credentials to curl)

- Exact wrapper keys for `cohorts` (`cohorts`) and `annotations` (`data`) come from the public docs, not a
  live 200 response. `_get_list_rows` falls back to treating a bare-list body as the row list if the wrapper
  key is absent.
- The Export JSON field set (timestamp field names, `uuid` presence) is taken from Amplitude's documented
  export schema. Timestamp normalization tolerates both `%Y-%m-%d %H:%M:%S.%f` and `%Y-%m-%d %H:%M:%S`.
