# Pipedrive API inventory

Reference: <https://developers.pipedrive.com/docs/api/v1>

## Auth

- API token, passed via the `x-api-token` request header (the query-param form leaks the
  token into logged URLs, so we use the header instead).
- All requests go to the company domain: `https://{company_domain}.pipedrive.com`.
  v1 resources live under `/api/v1/...`, v2 resources under `/api/v2/...`.

## Pagination

- **v2 (cursor):** `?limit=500&cursor=<cursor>`. Response carries
  `additional_data.next_cursor`; a falsy/absent cursor ends the chain.
- **v1 (offset):** `?start=<n>&limit=500`. Response carries
  `additional_data.pagination.{more_items_in_collection,next_start}`; pagination object is
  absent for single-page endpoints (e.g. `users`).
- Both wire styles return rows under the top-level `data` key.

## Endpoints synced

| Schema              | Path                                            | Pagination | Primary key              | Partition key |
| ------------------- | ----------------------------------------------- | ---------- | ------------------------ | ------------- |
| deals               | `/api/v2/deals`                                 | cursor     | id                       | add_time      |
| archived_deals      | `/api/v2/deals/archived`                        | cursor     | id                       | add_time      |
| persons             | `/api/v2/persons`                               | cursor     | id                       | add_time      |
| organizations       | `/api/v2/organizations`                         | cursor     | id                       | add_time      |
| products            | `/api/v2/products`                              | cursor     | id                       | add_time      |
| pipelines           | `/api/v2/pipelines`                             | cursor     | id                       | add_time      |
| stages              | `/api/v2/stages`                                | cursor     | id                       | add_time      |
| activities          | `/api/v2/activities`                            | cursor     | id                       | add_time      |
| notes               | `/api/v1/notes`                                 | offset     | id                       | add_time      |
| leads               | `/api/v1/leads`                                 | offset     | id                       | add_time      |
| users               | `/api/v1/users`                                 | offset     | id                       | —             |
| deal_fields         | `/api/v1/dealFields`                            | offset     | id                       | —             |
| person_fields       | `/api/v1/personFields`                          | offset     | id                       | —             |
| organization_fields | `/api/v1/organizationFields`                    | offset     | id                       | —             |
| lead_labels         | `/api/v1/leadLabels`                            | none       | id                       | —             |
| activity_types      | `/api/v1/activityTypes`                         | none       | id                       | —             |
| deal_products       | `/api/v2/deals/products`                        | cursor     | deal_id, id              | add_time      |
| deal_changelog      | `/api/v1/deals/{id}/changelog`                  | cursor     | deal_id, field_key, time | time          |
| mail_threads        | `/api/v1/mailbox/mailThreads`                   | offset     | id                       | add_time      |
| mail_messages       | `/api/v1/mailbox/mailThreads/{id}/mailMessages` | none       | id                       | add_time      |
| projects            | `/api/v2/projects`                              | cursor     | id                       | add_time      |
| archived_projects   | `/api/v2/projects/archived`                     | cursor     | id                       | add_time      |
| project_tasks       | `/api/v1/tasks`                                 | cursor     | id                       | add_time      |
| project_boards      | `/api/v1/projects/boards`                       | none       | id                       | —             |
| project_phases      | `/api/v1/projects/phases`                       | none       | id                       | —             |

`lead_labels` and `activity_types` are documented as unpaginated and always return every row, so they are read in one request.

`deal_products` and `deal_changelog` fan out over every deal in `/api/v2/deals` and `/api/v2/deals/archived`, so a deal keeps its line items and history after it is archived.
`deal_products` sends up to 100 deal ids per request in the `deal_ids` param.
`deal_changelog` sends one request chain per deal, because the changelog has no batched form.
Changelog rows carry neither an id nor the deal id, so the source adds the `deal_id` it requested.
The resume state holds the deal list and page, the last finished deal id, and the cursor of the deal group in progress, so it does not grow with the account.
`archived_deals` and `archived_projects` read the archived lists, which `/api/v2/deals` and `/api/v2/projects` leave out.

`mail_threads` reads `/mailbox/mailThreads` once per folder (`inbox`, `sent`, `archive`, `drafts`).
A thread is listed in every folder that holds one of its messages, so a thread already read from an earlier folder is skipped.
`mail_messages` reads `/mailbox/mailThreads/{id}/mailMessages` for every thread in the same walk, without message bodies.
Threads come newest message first, so the resume state is the folder, the page, and the ids of the threads of that page that are done.
A resume lists the earlier folders and pages again to rebuild the threads already read, so the state does not grow with the mailbox.
The mailbox only holds mail synced by the user who owns the API token.

`project_tasks`, `project_boards` and `project_phases` stay on v1, because their v2 endpoints (`/api/v2/tasks`, `/api/v2/boards`, `/api/v2/phases`) are still in beta.
`project_phases` reads `/projects/phases` once per board, because the endpoint requires a `board_id`.
Its resume state is the ids of the boards done, so a board deleted between attempts does not shift the rest.

`/pipelines/{id}/conversion_statistics` and `/pipelines/{id}/movement_statistics` are not synced: they return one aggregate for a required date range and a single user, not a collection of rows, and `deals` with `deal_changelog` hold the data they summarize.

`/deals/{id}/flow` is not synced: it mixes activities, notes, files and field changes in one timeline, and the changelog and existing tables already cover those.

## Source versions

The source declares two versions (`ExternalDataSource.api_version`), `v1` and `v2`, differing
only in the `activities` endpoint — Pipedrive deprecated `/api/v1/activities` (sunset
2025-12-31) in favour of the cursor-paginated `/api/v2/activities`. New sources default to `v2`.
The other endpoints don't change: `notes`, `leads`, `users`, and the `*_fields` endpoints have
no v2 replacement and stay on v1 under both labels; the rest were already on v2.

## Incremental sync

Shipped as **full refresh for every endpoint**. Pipedrive's v2 collection endpoints
document an `updated_since` (RFC 3339) server-side filter plus `sort_by=update_time`, which
would make those endpoints incremental — but the implementing-warehouse-sources skill
requires a live curl smoke test (future-date cutoff) to confirm the filter actually filters
before enabling it, and no Pipedrive credentials were available at implementation time. The
v1 collection endpoints have no per-resource `updated_after` filter at all (only the 30-day
`/recents` endpoint), so they would stay full refresh regardless. Enabling incremental on the
v2 endpoints is a verified follow-up.
