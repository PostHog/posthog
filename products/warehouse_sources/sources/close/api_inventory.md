# Close API inventory

Source: Close CRM REST API. Base URL: `https://api.close.com/api/v1`.
Spec: <https://api.close.com/api/openapi.json> (version 1.0.0).

## Auth

- HTTP Basic. API key is the **username**, password is empty (`ApiKeyAuth` scheme in the spec).
- OAuth2 (`all.full_access` / `offline_access`) is also offered by Close but not implemented here yet.

## Pagination

- Most list endpoints use offset pagination: `_skip` (offset) + `_limit` (default 100).
  Response body: `{"data": [...], "has_more": <bool>}`.
- Some small dimension endpoints (`/status/lead/`, `/status/opportunity/`, `/pipeline/`,
  `/custom_field/shared/`) return all rows in one response with no pagination params; they may omit
  `has_more`. The paginator treats a missing/false `has_more` as the last page.
- The event log (`/event/`) rejects `_skip` entirely. It pages with `_cursor` and returns the next
  cursor as `cursor_next` (null on the last page) — see below.
- Close caps `_skip` per resource. Every endpoint except Leads and Contacts exposes a server-side
  date filter (or is a single-page dimension table), so an incremental sync never accumulates a
  deep enough offset to reach the cap.
- Leads and Contacts have no date filter on their list endpoints, so offset was the only option and
  a big org's table stopped syncing at the cap. Both now read through Advanced Filtering instead —
  see below.
- All paths require a trailing slash to avoid a redirect.

## Advanced Filtering (`POST /data/search/`) — Leads and Contacts

Advanced Filtering is the only read path that exposes `date_created`/`date_updated` filters for
leads and contacts. It is cursor-paginated, but the cursor has limits of its own: it expires after
30s, and one cursor walk returns at most 10,000 objects.

We therefore page by **keyset**, not by cursor: sort ascending on the cursor field and re-query
`<field> on_or_after <last value emitted>` for each page. Every request is a fresh, shallow query,
so neither the `_skip` cap, the 10k cursor cap, nor the 30s TTL applies. The cursor is used only to
step over a run of rows sharing one exact timestamp, where the keyset filter cannot advance.

Notes:

- Only `lead` and `contact` are documented as searchable object types, and they are also the only
  two that need this — everything else already filters server-side.
- Search returns bare IDs unless each field is named in `_fields`, so `settings.py` carries an
  explicit field list per object type. A single `custom` selector is added at request time to
  return every custom field as a flat `custom.cf_*` key. Naming each custom field instead grows
  `_fields` one entry per field, which Close rejects with 400 "List is too long." once an org has
  enough of them.
- The `moment_range` condition (`on_or_after` / `before` with `{"type": "fixed_utc"}` moments) is
  what the Close app itself emits; the public docs describe date-range filtering without naming
  the condition type.
- Resuming re-reads rows tied to the checkpointed anchor timestamp; they dedupe on `id`.

## Incremental support (verified against the OpenAPI spec query params)

Only endpoints with a genuine server-side timestamp filter get `supports_incremental=True`:

| Endpoint          | Path                           | Offset pag | Server-side date filter                             | `_order_by` | Incremental                   |
| ----------------- | ------------------------------ | ---------- | --------------------------------------------------- | ----------- | ----------------------------- |
| Activities        | `/activity/`                   | yes        | `date_created__gte/lte/gt/lt`                       | yes         | date_created                  |
| Opportunities     | `/opportunity/`                | yes        | `date_created__*`, `date_updated__*`, `date_won__*` | yes         | date_created (+ date_updated) |
| Tasks             | `/task/`                       | yes        | `date_created__*`, `date_updated__*`, `date__*`     | yes         | date_created (+ date_updated) |
| Leads             | `/data/search/`                | keyset     | `date_created`, `date_updated` (Advanced Filtering) | sort        | date_created (+ date_updated) |
| Contacts          | `/data/search/`                | keyset     | `date_created`, `date_updated` (Advanced Filtering) | sort        | date_created (+ date_updated) |
| Events            | `/event/`                      | cursor     | `date_updated__gt/gte/lt/lte`                       | no          | date_updated                  |
| Users             | `/user/`                       | yes        | none                                                | yes         | full refresh                  |
| Lead statuses     | `/status/lead/`                | no         | none                                                | no          | full refresh                  |
| Opp. statuses     | `/status/opportunity/`         | no         | none                                                | no          | full refresh                  |
| Pipelines         | `/pipeline/`                   | no         | none                                                | no          | full refresh                  |
| Email templates   | `/email_template/`             | yes        | none                                                | no          | full refresh                  |
| Outcomes          | `/outcome/`                    | yes        | none                                                | no          | full refresh                  |
| Organizations     | `/organization/{id}/`          | n/a        | none                                                | no          | full refresh                  |
| Custom fields     | `/custom_field/{object_type}/` | yes        | none                                                | no          | full refresh                  |
| Shared cust. flds | `/custom_field/shared/`        | no         | none                                                | no          | full refresh                  |

Notes:

- The plain `GET /lead/` and `GET /contact/` list endpoints expose **no** `date_*` filter param
  (only `_skip`/`_limit`/`_fields`, plus `lead_id` on contacts). Both resources go through
  Advanced Filtering instead, which is also how Airbyte reaches a `date_updated` cursor for leads.
- Organizations has no list endpoint. `/me/` returns the organizations the API key belongs to, and
  each one is then read from `/organization/{id}/`. The default response already carries
  `memberships` with `user_*` fields, so no `_expand` is needed.
- Custom field definitions are what resolve the opaque `custom.cf_*` keys on synced leads, contacts
  and opportunities. `/custom_field_schema/{object_type}/` is deliberately not synced: it is a
  single-object read per object type whose `fields` array is the same rows the per-type
  `/custom_field/{object_type}/` tables already carry, ordered for display.

## Event log (`/event/`)

- Retention is about 30 days, so the table is a rolling window rather than full history.
- Rows arrive newest-first and there is no sort param, hence `sort_mode="desc"`. The pipeline only
  commits the watermark once a descending run finishes.
- Pagination is `_cursor` + `cursor_next`; `_limit` is capped at and defaults to 50.
- Close documents that a cursor request must re-send every other filter **except** `date_updated`,
  so `date_updated__gte` only bounds the first request. Later pages would walk back through the
  whole retention window, so `CloseEventCursorPaginator` stops as soon as an entire page predates
  the watermark.
- Events are consolidated: repeated updates to one object reuse the event, moving `date_updated`
  forward while `date_created` stays put. Merging on `id` is therefore correct, and `date_created`
  stays a stable partition key.

## Primary keys & partition keys

- Every Close object has a string `id` → `primary_keys=["id"]` for all endpoints.
- Stable partition key `date_created` exists on lead/contact/opportunity/activity/task → partition by
  month. Dimension endpoints (users/statuses/pipelines/email templates) have no stable datetime →
  no partitioning.

## Credential validation

- `GET /me/` is a cheap authenticated probe. 200 → valid key. 401 → invalid.
