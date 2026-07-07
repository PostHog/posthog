# FireHydrant API inventory

Source: <https://docs.firehydrant.com/reference/firehydrant-api> and the official OpenAPI spec
(<https://raw.githubusercontent.com/firehydrant/firehydrant-typescript-sdk/main/openapi.yaml>).

- **Base URL:** `https://api.firehydrant.io/` (EU: `https://api.eu.firehydrant.io/`). Endpoints live under `/v1/`.
- **Auth:** `Authorization: Bearer <api_key>` (bot token or personal API key). Keys default to Owner-level scope.
- **Pagination:** `?page=<n>&per_page=<n>` (`per_page` max 200). Responses are `{ "data": [...], "pagination": { "count", "page", "items", "pages", "last", "prev", "next" } }`. `pagination.next` is the next page number, or null on the last page. A few endpoints return a single unpaginated response.
- **Rate limit:** 50 requests / 10 s per account (~300/min). 429 responses carry a `Retry-After` header.
- **Incremental:** No uniform server-side `updated_after` cursor across resources. `/v1/incidents` accepts `created_at_or_after` / `updated_after` filters, but these could not be curl-verified without live credentials, so all endpoints ship full refresh (matching Airbyte's connector).

## Endpoints implemented

| Schema name              | Path                            | Primary key | Partition key (created_at?)     |
| ------------------------ | ------------------------------- | ----------- | ------------------------------- |
| incidents                | `/v1/incidents`                 | id          | created_at                      |
| alerts                   | `/v1/alerts`                    | id          | — (no created_at)               |
| changes                  | `/v1/changes`                   | id          | created_at                      |
| change_events            | `/v1/changes/events`            | id          | created_at                      |
| environments             | `/v1/environments`              | id          | created_at                      |
| functionalities          | `/v1/functionalities`           | id          | created_at                      |
| services                 | `/v1/services`                  | id          | created_at                      |
| teams                    | `/v1/teams`                     | id          | created_at                      |
| users                    | `/v1/users`                     | id          | created_at                      |
| incident_roles           | `/v1/incident_roles`            | id          | created_at                      |
| incident_types           | `/v1/incident_types`            | id          | created_at                      |
| incident_tags            | `/v1/incident_tags`             | name        | — (only `name`)                 |
| priorities               | `/v1/priorities`                | slug        | created_at                      |
| severities               | `/v1/severities`                | slug        | created_at                      |
| custom_field_definitions | `/v1/custom_fields/definitions` | field_id    | — (no created_at)               |
| integrations             | `/v1/integrations`              | id          | created_at                      |
| runbooks                 | `/v1/runbooks`                  | id          | created_at                      |
| runbook_executions       | `/v1/runbooks/executions`       | id          | created_at                      |
| webhooks                 | `/v1/webhooks`                  | id          | created_at                      |
| signals_on_call          | `/v1/signals_on_call`           | id          | — (undocumented response shape) |
| post_mortem_reports      | `/v1/post_mortems/reports`      | id          | created_at                      |
| scheduled_maintenances   | `/v1/scheduled_maintenances`    | id          | created_at                      |
| task_lists               | `/v1/task_lists`                | id          | created_at                      |
| checklist_templates      | `/v1/checklist_templates`       | id          | created_at                      |

## Future enhancements

- Incremental sync on `/v1/incidents` via `created_at_or_after` / `updated_after` once the filter behavior and default sort order can be curl-verified against a live account.
- Webhook ingestion: FireHydrant exposes programmatic webhook management (`/v1/webhooks`), so a `WebhookSource` layer could deliver incident/alert deltas event-driven.
