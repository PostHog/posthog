# Trigger.dev API inventory

Both endpoints use a secret API key for one Trigger.dev environment. They return rows in `data`, newest first.
Pass `pagination.next` as `page[after]` until the response has no next cursor. Each request can return up to 100 rows.

| Table          | Endpoint                                                                            | Row                                 | Primary key        | Incremental sync                                                                      |
| -------------- | ----------------------------------------------------------------------------------- | ----------------------------------- | ------------------ | ------------------------------------------------------------------------------------- |
| `sessions`     | [`GET /api/v1/sessions`](https://trigger.dev/docs/management/sessions/list)         | One session                         | `id` (`session_…`) | `createdAt` with a seven-day lookback. The first page uses `filter[createdAt][from]`. |
| `bulk_actions` | [`GET /api/v1/bulk-actions`](https://trigger.dev/docs/management/bulk-actions/list) | One bulk cancel or replay operation | `id` (`bulk_…`)    | Full refresh. The endpoint has no time filter, and status and counts can change.      |

The [`@trigger.dev/core` 4.8.10 SDK](https://www.npmjs.com/package/@trigger.dev/core/v/4.8.10) sends the session filter as epoch milliseconds. It uses an integer schema for the query parameter, although the API reference shows a date-time string.

Unauthenticated requests to both endpoints returned HTTP 401. Ordering, cursor termination, and the session time filter still need an authenticated check.
