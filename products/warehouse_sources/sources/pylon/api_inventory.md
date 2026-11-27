# Pylon API endpoint inventory

These contracts come from the [Pylon API v1 OpenAPI spec](https://api.usepylon.com/openapi.json). No live requests ran with a Pylon API token.

Each endpoint uses the configured Pylon API token as a bearer token. The spec declares no endpoint-specific scopes. Each returns its records in `data` with no pagination on the endpoint itself.

| Table                   | Endpoint                                   | Row grain                                                             | Primary key              | Incremental candidate                                         | Rate limit          |
| ----------------------- | ------------------------------------------ | --------------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------- | ------------------- |
| `surveys`               | `GET /surveys`                             | One survey                                                            | `id`                     | `updated_at` via the separate `POST /surveys/search` endpoint | 300 requests/minute |
| `account_relationships` | `GET /accounts/{account_id}/relationships` | One row per relationship. An account can have multiple relationships. | `child_account_id`, `id` | None. The endpoint does not filter on `updated_at`.           | 300 requests/minute |
| `issue_threads`         | `GET /issues/{id}/threads`                 | One row per internal thread. An issue can have multiple threads.      | `issue_id`, `id`         | None. The endpoint has no timestamp filter.                   | 120 requests/minute |

- `surveys` uses full refresh. `GET /surveys` has no time filter.
- `account_relationships` uses opt-in full refresh. It follows cursors from `GET /accounts` and requests relationships for each account.
- `issue_threads` uses opt-in full refresh. Each refresh follows cursors from `GET /issues` in windows of up to 30 days across a rolling 365-day lookback.
