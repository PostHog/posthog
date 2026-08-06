# Close API inventory

Source: Close CRM REST API. Base URL: `https://api.close.com/api/v1`.
Spec: <https://api.close.com/api/openapi.json> (version 1.0.0).

## Auth

- HTTP Basic. API key is the **username**, password is empty (`ApiKeyAuth` scheme in the spec).
- OAuth2 (`all.full_access` / `offline_access`) is also offered by Close but not implemented here yet.

## Pagination

- Most list endpoints use offset pagination: `_skip` (offset) + `_limit` (default 100).
  Response body: `{"data": [...], "has_more": <bool>}`.
- Some small dimension endpoints (`/status/lead/`, `/status/opportunity/`, `/pipeline/`) return all
  rows in one response with no pagination params; they may omit `has_more`. The paginator treats a
  missing/false `has_more` as the last page.
- Close caps `_skip` per resource — very large full-refresh tables (leads/contacts on big orgs) can
  hit this cap. This matches the documented offset behavior and the dlt/Airbyte connectors; the
  Advanced Filtering / Export APIs are the long-term answer for huge tables. Noted as a known limit.
- All paths require a trailing slash to avoid a redirect.

## Incremental support (verified against the OpenAPI spec query params)

Only endpoints with a genuine server-side timestamp filter get `supports_incremental=True`:

| Endpoint        | Path                   | Offset pag | Server-side date filter                             | `_order_by` | Incremental                   |
| --------------- | ---------------------- | ---------- | --------------------------------------------------- | ----------- | ----------------------------- |
| Activities      | `/activity/`           | yes        | `date_created__gte/lte/gt/lt`                       | yes         | date_created                  |
| Opportunities   | `/opportunity/`        | yes        | `date_created__*`, `date_updated__*`, `date_won__*` | yes         | date_created (+ date_updated) |
| Tasks           | `/task/`               | yes        | `date_created__*`, `date_updated__*`, `date__*`     | yes         | date_created (+ date_updated) |
| Leads           | `/lead/`               | yes        | **none** (only the search/query API)                | no          | full refresh                  |
| Contacts        | `/contact/`            | yes        | **none**                                            | no          | full refresh                  |
| Users           | `/user/`               | yes        | none                                                | yes         | full refresh                  |
| Lead statuses   | `/status/lead/`        | no         | none                                                | no          | full refresh                  |
| Opp. statuses   | `/status/opportunity/` | no         | none                                                | no          | full refresh                  |
| Pipelines       | `/pipeline/`           | no         | none                                                | no          | full refresh                  |
| Email templates | `/email_template/`     | yes        | none                                                | no          | full refresh                  |

Notes:

- The plain `GET /lead/` list endpoint exposes **no** `date_*` filter param (only `_skip`/`_limit`),
  so despite Airbyte using a `date_updated` cursor for leads (it goes through Close's separate
  search/query API), we ship Leads as full refresh rather than fake incremental. Same for Contacts.
- The Event Log (`/event/`) does support `date_updated__gte` but is capped to ~30 days of history and
  has consolidation/ordering caveats, so it is intentionally left out of v1; it can be added later as
  an append-only stream.

## Primary keys & partition keys

- Every Close object has a string `id` → `primary_keys=["id"]` for all endpoints.
- Stable partition key `date_created` exists on lead/contact/opportunity/activity/task → partition by
  month. Dimension endpoints (users/statuses/pipelines/email templates) have no stable datetime →
  no partitioning.

## Credential validation

- `GET /me/` is a cheap authenticated probe. 200 → valid key. 401 → invalid.
