---
name: setting-up-a-custom-rest-source
description: >
  Connect an arbitrary REST API to the PostHog data warehouse as a Custom source by authoring a JSON manifest, with no
  per-source code. Use when the user points at an API that has no built-in PostHog connector — "import data from this
  REST API", "sync my internal API", "connect this API from its docs", "build a custom data warehouse source" — and
  gives a docs URL or a natural-language description of the endpoints. Walks through drafting the RESTAPIConfig manifest
  (auth, pagination, record path, incremental cursor, parent/child fan-out), validating it, test-reading live rows to
  verify the field mappings, and creating the source. For sources that already have a built-in connector (Postgres,
  Stripe, Hubspot, etc.), use setting-up-a-data-warehouse-source instead.
---

# Setting up a Custom REST source

A **Custom source** imports any HTTP REST API into queryable warehouse tables from a JSON **manifest** — no
per-source Python. The manifest is a `RESTAPIConfig`: the same shape that powers PostHog's built-in REST connectors
(Intercom, Attio, Sentry, …), so the generic REST engine handles auth, pagination, JSONPath record extraction, and
incremental cursors for you. Your job is to author a correct manifest and prove it against live data before creating
the source.

This is an **alpha** capability. Caps: at most 50 resources per manifest, and at most 5 Custom sources per project.

## When to use this skill

- The user wants to import an API that has **no built-in connector** — an internal service, a niche SaaS, a public
  API — and can give you its docs URL or describe its endpoints.
- The user explicitly asks for a "custom REST source", "custom source manifest", or to "build a connector from docs".

If a built-in connector exists for the source (Postgres, MySQL, Stripe, Hubspot, Zendesk, BigQuery, …), use
`setting-up-a-data-warehouse-source` — it's simpler and battle-tested. Only fall back to a Custom source when none fits.

## The grammar

Read [references/manifest-reference.md](references/manifest-reference.md) before drafting — it is the full
`RESTAPIConfig` field reference (auth types, the six paginators, incremental cursors, parent/child fan-out) with worked
examples for each. Draft the manifest from that grammar; don't guess field names.

The skeleton:

```json
{
  "client": {
    "base_url": "https://api.example.com/v1",
    "auth": { "type": "bearer" }
  },
  "resources": [
    {
      "name": "users",
      "primary_key": "id",
      "endpoint": {
        "path": "/users",
        "data_selector": "data",
        "paginator": { "type": "json_response", "next_url_path": "next" },
        "incremental": { "cursor_path": "updated_at", "start_param": "since" }
      }
    }
  ]
}
```

**Secrets never go inline in the manifest.** `manifest_json` holds only the non-secret structure. The credential
travels in a separate payload key chosen by the manifest's `client.auth.type`: `auth_token` (bearer), `auth_api_key`
(api_key), or `auth_password` (http_basic). The engine injects it at run time, and PostHog redacts it from every
response. Putting a token inline is rejected at validation.

## Available tools

| Tool                                     | Purpose                                                                                                                                                                |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `external-data-sources-db-schema`        | Validate the manifest + credential and list the resources (tables) it exposes, with detected primary keys and incremental cursors. This is the validate-and-list step. |
| `external-data-sources-preview-resource` | Read a small live sample of rows for one resource — verify `data_selector` / `primary_key` / `cursor_path` against real data before creating anything.                 |
| `data-warehouse-source-setup`            | Create the source. Enables **all** manifest resources with sync defaults in one call.                                                                                  |
| `external-data-sources-create`           | Advanced create — lets the user hand-pick which resources sync via a `schemas` array.                                                                                  |
| `external-data-schemas-list`             | After creation, watch per-table sync status.                                                                                                                           |

## Workflow

### Step 1 — Gather the API shape

Get either a **docs URL** (fetch it and read the auth scheme, the list endpoints, their response envelopes, and any
pagination) or a **natural-language description** of the endpoints. You need, per resource you'll import:

- the **path** (relative to a common `base_url`) and method (GET, or POST for query-style read endpoints),
- the **auth scheme** (bearer token / API key in header or query / HTTP basic),
- the **record path** — where the array of records sits in the JSON response (e.g. `data`, `results`, `items`),
- how the API **paginates** (next-URL, link header, cursor, offset, page number, or single page),
- a **primary key** field, and
- optionally an **incremental cursor** field (`updated_at`-style) so re-syncs only fetch new/changed rows.

Ask the user for the credential value, but tell them you'll only ever place it in the `auth_*` payload key, never in
the manifest.

### Step 2 — Draft the manifest

Author the `RESTAPIConfig` from [references/manifest-reference.md](references/manifest-reference.md). Match the auth
block to the scheme, pick the paginator that matches the docs, set `data_selector` to the record path, and add an
`incremental` block when the API has an `updated_at`-style cursor and a matching query param. For an endpoint whose
rows must be fetched per parent (e.g. `/forms/{form_id}/responses`), use a parent/child **resolve** param — see the
fan-out example. Keep it to one level of nesting.

### Step 3 — Validate and list resources

Call `external-data-sources-db-schema` with `{ source_type: "Custom", manifest_json: "<stringified manifest>", auth_*:
"<credential>" }`. It validates the manifest structure, the fan-out graph, and the credential (a bounded live probe),
then returns one table entry per resource with `detected_primary_keys` and `incremental_fields`. If it returns a 400,
the `message` is plain English (e.g. `resources[0].endpoint.path: must not be empty`) — fix the manifest and retry.
Loop here until it validates.

### Step 4 — Test-read each resource

For each resource, call `external-data-sources-preview-resource` with `{ source_type: "Custom", payload: {
manifest_json, auth_* }, resource_name: "<name>", limit: 10 }`. It returns up to `limit` real rows plus the inferred
`columns`. Check that:

- **`data_selector` is right** — `rows` are the records you expect, not a wrapper object. If `rows` looks like
  `[{ "data": [...] }]` you pointed at the envelope, not the array; fix `data_selector`.
- **`primary_key` exists** in the rows and is unique.
- **the incremental `cursor_path` field is present** in the rows and looks like a sortable timestamp/id.

A live failure (unreachable host, auth rejected) comes back as `error` with empty `rows` — fix credentials or the URL
and retry. Iterate Steps 2–4 until the sample looks right.

### Step 5 — Create the source

Call `data-warehouse-source-setup` with `{ source_type: "Custom", payload: { manifest_json, auth_* }, prefix:
"<short_name>" }`. It enables **every** resource in the manifest with sensible sync defaults (incremental where the
manifest declares a cursor, else full refresh) and creates the source. If the user only wants a subset of resources,
use `external-data-sources-create` with a `schemas` array instead (see `setting-up-a-data-warehouse-source` for the
schemas shape). Pick a short lowercase `prefix` — tables become `{prefix}_{resource_name}` in HogQL.

After creation, call `external-data-schemas-list` to show the user the initial sync status, and tell them how to query:
`SELECT * FROM {prefix}_{resource_name} LIMIT 10`.

## Important notes

- **Always preview before creating.** db-schema proves the manifest parses and the credential works; preview proves the
  field mappings (`data_selector` / `primary_key` / `cursor_path`) against real rows. Skipping preview is the most
  common way to create a source that syncs zero or malformed rows.
- **Secrets only in `auth_*`.** Never inline a token/key/password in `manifest_json` — it's rejected, and the manifest
  is non-secret (it round-trips to the client).
- **One level of fan-out.** A child resource may depend on a top-level parent; a parent can't itself be a child.
- **GET and POST only.** The engine reads upstream data; PUT/PATCH/DELETE are rejected so a manifest can't mutate the
  source API.
- **Pick the cursor carefully.** Prefer an `updated_at`-style field over `created_at` (it catches edits), and set
  `cursor_type` when the cursor isn't a datetime (e.g. an integer id) so it's compared with the right type.
