# Scalr API inventory

The source uses the current v3 API at `https://<host>/api/iacp/v3/`.
All requests use a customer token with Bearer authentication and an account ID filter.
Connections use HTTPS. The host check rejects internal addresses under the shared cloud policy.
The source rejects redirects and reads page numbers from `meta.pagination.next-page`.

| Table        | GET path        | Required access                  | Key  | Sync                        | Partition    |
| ------------ | --------------- | -------------------------------- | ---- | --------------------------- | ------------ |
| environments | `/environments` | Read environments in the account | `id` | Full refresh                | `created_at` |
| workspaces   | `/workspaces`   | Read workspaces in the account   | `id` | Incremental on `updated_at` | `created_at` |
| runs         | `/runs`         | Read runs in the account         | `id` | Full refresh                | `created_at` |

Workspace requests use `sort=updated-at` and `filter[updated-at]=gte:<timestamp>` after the first sync.
Full refresh omits the time filter. Environment requests use `sort=created-at`.
The runs endpoint documents a creation filter but no update filter or sort parameter.
Runs use full refresh because a creation watermark would miss later status changes.
JSON:API attributes become columns with underscores. Relationship references remain in the `relationships` column.

The shared REST framework handles retries and stores page checkpoints through its resume hook.
Page pagination can shift when records change during a sync.
The API documents a limit of 500 requests per minute.

The public API returned a JSON:API 401 response without credentials.
Authenticated pagination, ordering, and timestamp filtering still need verification with a real account.

Sources:

- [API overview and version](https://docs.scalr.io/reference/overview-1)
- [Official OpenAPI specification](https://scalr.io/api/iacp/v3/openapi-public.yml)
- [Environment list](https://docs.scalr.io/reference/list_environments)
- [Workspace list](https://docs.scalr.io/reference/get_workspaces)
- [Run list](https://docs.scalr.io/reference/get_runs)
- [API tokens](https://docs.scalr.io/reference/api-tokens)
