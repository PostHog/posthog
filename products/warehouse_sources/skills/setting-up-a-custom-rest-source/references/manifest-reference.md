# Custom REST source manifest reference

The manifest is a JSON `RESTAPIConfig`. The generic REST engine consumes it directly, so every field below maps to a
real engine behavior. Only the fields the engine reads are documented here; unknown keys are ignored.

## Top-level shape

```json
{
    "client": { "base_url": "...", "auth": { ... }, "headers": { ... }, "paginator": { ... } },
    "resource_defaults": { "endpoint": { ... } },
    "resources": [ { "name": "...", "primary_key": "...", "endpoint": { ... } } ]
}
```

- **`client.base_url`** (required) — every resource path resolves against this. On PostHog Cloud it must be `https://`.
  Internal/private hosts are rejected (SSRF guard).
- **`client.headers`** (optional) — static headers sent on every request.
- **`client.paginator`** (optional) — a default paginator for all resources; override per resource on the endpoint.
- **`resource_defaults.endpoint`** (optional) — endpoint fields merged into every resource (e.g. a shared paginator or
  `data_selector`).
- **`resources`** (required, 1–50) — one entry per table you want to import. Each has a unique `name` (becomes the
  table name) and an `endpoint`.

## Auth

The auth **type** lives in the manifest; the secret value travels in a separate payload key and is injected at run
time. Never put the secret in the manifest.

| `client.auth` block                                                | Secret payload key(s)                                                                          | Sends                                         |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `{ "type": "bearer" }`                                             | `auth_token`                                                                                   | `Authorization: Bearer <token>`               |
| `{ "type": "api_key", "name": "X-Api-Key", "location": "header" }` | `auth_api_key`                                                                                 | the key in header / query param `name`        |
| `{ "type": "api_key", "name": "api_key", "location": "query" }`    | `auth_api_key`                                                                                 | `?api_key=<key>`                              |
| `{ "type": "http_basic", "username": "user" }`                     | `auth_password`                                                                                | HTTP Basic with the given username + password |
| `{ "type": "oauth2", ... }` (see below)                            | `auth_oauth2_client_secret` (+ `auth_oauth2_refresh_token` for the `refresh_token` grant only) | `Authorization: Bearer <minted access token>` |

`location` is one of `header`, `query`, `param`, `cookie`. `query` and `param` are **synonyms** — both append
`name=<key>` to the URL query string, so use either (prefer `query`); they differ only in spelling, not behavior. For
an API with no auth, omit `auth` entirely.

### OAuth2

For APIs where the customer brings their own OAuth2 client, the engine mints access tokens itself from the token
endpoint declared in the manifest:

```json
{
  "type": "oauth2",
  "client_id": "my-client-id",
  "token_url": "https://auth.example.com/oauth/token",
  "grant_type": "refresh_token",
  "scopes": "read:orders read:users"
}
```

- **`grant_type`** — `client_credentials` (machine-to-machine; default) or `refresh_token` (the user supplies a
  pre-obtained refresh token). The interactive `authorization_code` flow is **not supported** — for providers that
  only issue tokens that way, the user must obtain a refresh token out of band first.
- **Secrets** travel in `auth_oauth2_client_secret` (the client secret) and, for the `refresh_token` grant,
  `auth_oauth2_refresh_token`. Never inline them in the manifest.
- **Optional knobs** for non-standard token endpoints: `access_token_name` / `expires_in_name` (response fields when
  they aren't `access_token` / `expires_in`), `expiry_date_format` (strptime format for absolute-datetime expiries),
  `extra_token_request_params` (extra form params, e.g. `audience`), `token_request_headers`, and
  `client_auth_method` (`body`, the default, or `basic` for HTTP Basic client auth).

PostHog **adopts the OAuth2 secrets into a server-managed credential store** on the first validation, preview, or
create call — they are never kept in the source's stored config, and any rotated single-use refresh token the provider
returns is persisted server-side. Two practical consequences:

- **Keep the entire `client.auth` block identical across the db-schema → preview → create calls of one setup.**
  The stored credential is found again by matching `client_id` + `token_url` + `grant_type`, but changing _any_
  auth-block field (`scopes`, token-request knobs, `client_auth_method`, …) makes PostHog treat the re-submitted
  refresh token as a deliberately new credential and discard the stored rotation — with a single-use-rotating
  provider the next mint then fails with `invalid_grant`. Only change the auth block mid-setup together with a
  freshly issued refresh token.
- **`auth_oauth2_integration_id`** may appear in a stored source's config — it is the server-owned pointer to the
  credential store. Never set or copy it yourself; on create it is ignored, and to reconnect a broken credential you
  update the source with re-entered `auth_oauth2_client_secret` / `auth_oauth2_refresh_token` instead.

## Endpoint fields

```json
{
    "path": "/users",
    "method": "GET",
    "params": { "status": "active" },
    "json": { ... },
    "data_selector": "data",
    "paginator": { "type": "json_response", "next_url_path": "next" },
    "incremental": { "cursor_path": "updated_at", "start_param": "since" }
}
```

- **`path`** (required) — appended to `base_url`.
- **`method`** — `GET` (default) or `POST`. POST is for read/query-style endpoints; `PUT`/`PATCH`/`DELETE` are
  rejected.
- **`params`** — static query params, or the engine's incremental/resolve specs (see below).
- **`json`** — request body (for POST query endpoints).
- **`data_selector`** — JSONPath to the array of records inside the response. For `{ "data": [ ... ] }` use `"data"`;
  for `{ "results": { "items": [ ... ] } }` use `"results.items"`. Omit only if the response body **is** the array.
- **`paginator`** — see below. **Required for any paginated endpoint.** Omitting it (or `{ "type": "auto" }`) fetches
  only the first response — there is no auto-detection — so a paginated API would silently import just page one.
- **`incremental`** — see below.

`primary_key` sits on the **resource**, not the endpoint: `"primary_key": "id"` or `"primary_key": ["org_id", "id"]`.

## Paginators

Set `endpoint.paginator` (or `client.paginator`) to one of:

| Type            | Config keys                                                                                  | Use when                                                                        |
| --------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `json_response` | `next_url_path` (JSONPath to the next-page URL in the body)                                  | response carries a next-page URL/path                                           |
| `header_link`   | `links_next_key` (rel, default `next`)                                                       | pagination via the `Link` response header                                       |
| `cursor`        | `cursor_path` (JSONPath to the next cursor), `cursor_param`                                  | response returns an opaque cursor you pass back as a query param                |
| `offset`        | `limit`, `offset_param`, `limit_param`, `total_path`, `maximum_offset`                       | classic `?offset=&limit=` pagination                                            |
| `page_number`   | `base_page` (first page number, e.g. `0` or `1`), `page_param`, `total_path`, `maximum_page` | classic `?page=N` pagination                                                    |
| `single_page`   | —                                                                                            | endpoint returns everything in one response                                     |
| `auto`          | —                                                                                            | fetches only the first response — no auto-detection; single-page endpoints only |

## Incremental sync

`endpoint.incremental` makes re-syncs fetch only new/changed rows:

```json
{
  "cursor_path": "updated_at",
  "start_param": "since",
  "end_param": "until",
  "cursor_type": "datetime",
  "datetime_format": "%Y-%m-%dT%H:%M:%SZ"
}
```

- **`cursor_path`** — JSONPath to the cursor field on each record (the high-watermark).
- **`start_param`** — query param the engine sets to the last-seen cursor value on the next sync.
- **`end_param`** (optional) — upper-bound param if the API supports a window.
- **`cursor_type`** (optional) — `datetime` (default), `date`, `timestamp`, `integer`, `numeric`, or `objectid`. Set
  it when the cursor is not a datetime (e.g. an autoincrement id) so it's stored and compared correctly.
- **`datetime_format`** (optional) — strftime pattern for how the watermark is serialized into `start_param`. Defaults
  to ISO-8601. Set it for strict APIs that reject the default.

Prefer an `updated_at`-style cursor over `created_at`: `created_at` misses edits to existing rows.

## Parent/child fan-out

When a resource's rows must be fetched per parent row (`/forms/{form_id}/responses`), bind the parent field into the
child path with a `resolve` param:

```json
{
  "resources": [
    { "name": "forms", "primary_key": "id", "endpoint": { "path": "/forms", "data_selector": "items" } },
    {
      "name": "responses",
      "primary_key": "token",
      "endpoint": {
        "path": "/forms/{form_id}/responses",
        "data_selector": "items",
        "params": { "form_id": { "type": "resolve", "resource": "forms", "field": "id" } }
      }
    }
  ]
}
```

Rules: the `{form_id}` placeholder must sit **within** the path (not start it, so a parent value can't redirect the
request off `base_url`); the parent must be a **top-level** resource; only **one level** of nesting is supported; and a
resource may have at most one resolve param.

## Worked examples

### Bearer + next-URL pagination + incremental

```json
{
  "client": { "base_url": "https://api.acme.com/v2", "auth": { "type": "bearer" } },
  "resources": [
    {
      "name": "orders",
      "primary_key": "id",
      "endpoint": {
        "path": "/orders",
        "data_selector": "data",
        "paginator": { "type": "json_response", "next_url_path": "links.next" },
        "incremental": { "cursor_path": "updated_at", "start_param": "updated_since" }
      }
    }
  ]
}
```

Credential: `auth_token`.

### API key in query + offset pagination + integer cursor

```json
{
  "client": {
    "base_url": "https://data.example.org",
    "auth": { "type": "api_key", "name": "api_key", "location": "query" }
  },
  "resources": [
    {
      "name": "events",
      "primary_key": "event_id",
      "endpoint": {
        "path": "/events",
        "data_selector": "results",
        "paginator": { "type": "offset", "limit": 200, "total_path": "meta.total" },
        "incremental": { "cursor_path": "sequence", "start_param": "after_id", "cursor_type": "integer" }
      }
    }
  ]
}
```

Credential: `auth_api_key`.

### HTTP basic + single page

```json
{
  "client": {
    "base_url": "https://reports.example.net",
    "auth": { "type": "http_basic", "username": "svc_account" }
  },
  "resources": [
    {
      "name": "daily_summary",
      "primary_key": "date",
      "endpoint": { "path": "/summary/today", "data_selector": "rows", "paginator": { "type": "single_page" } }
    }
  ]
}
```

Credential: `auth_password`.

### OAuth2 refresh-token grant + page-number pagination

```json
{
  "client": {
    "base_url": "https://api.example.com/v2",
    "auth": {
      "type": "oauth2",
      "client_id": "warehouse-import",
      "token_url": "https://auth.example.com/oauth/token",
      "grant_type": "refresh_token"
    }
  },
  "resources": [
    {
      "name": "invoices",
      "primary_key": "id",
      "endpoint": {
        "path": "/invoices",
        "data_selector": "items",
        "paginator": { "type": "page_number", "page_param": "page", "total_path": "total_pages" },
        "incremental": { "cursor_path": "updated_at", "start_param": "modified_since" }
      }
    }
  ]
}
```

Credentials: `auth_oauth2_client_secret` + `auth_oauth2_refresh_token`.

### Bearer + cursor pagination + incremental

`paginator.cursor_path` and `incremental.cursor_path` are independent and easily confused: the **paginator's**
`cursor_path` reads the _next-page cursor_ from the response envelope (drives pagination within a sync); the
**incremental's** `cursor_path` reads the _watermark_ from each record (drives what a re-sync re-fetches).

```json
{
  "client": { "base_url": "https://api.acme.com/v1", "auth": { "type": "bearer" } },
  "resources": [
    {
      "name": "tickets",
      "primary_key": "id",
      "endpoint": {
        "path": "/tickets",
        "data_selector": "data",
        "paginator": { "type": "cursor", "cursor_path": "meta.next_cursor", "cursor_param": "cursor" },
        "incremental": { "cursor_path": "updated_at", "start_param": "since" }
      }
    }
  ]
}
```

Credential: `auth_token`.
