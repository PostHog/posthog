# Scalr API inventory

The source uses the current v3 API at `https://<host>/api/iacp/v3/`.
All requests use a customer token with Bearer authentication and an account ID filter.
Connections use HTTPS. The host check rejects internal addresses under the shared cloud policy.
The source rejects redirects and reads page numbers from `meta.pagination.next-page`.

| Table          | GET path                                 | Required access                       | Key  | Sync                        | Partition    |
| -------------- | ---------------------------------------- | ------------------------------------- | ---- | --------------------------- | ------------ |
| environments   | `/environments`                          | Read environments in the account      | `id` | Full refresh                | `created_at` |
| workspaces     | `/workspaces`                            | Read workspaces in the account        | `id` | Incremental on `updated_at` | `created_at` |
| runs           | `/runs`                                  | Read runs in the account              | `id` | Full refresh                | `created_at` |
| users          | `/users`                                 | Read users in the account             | `id` | Full refresh                | `created_at` |
| plans          | `/runs?include=plan`                     | Read runs in the account              | `id` | Full refresh                | None         |
| state_versions | `/state-versions?filter[workspace]=<id>` | Read state versions of each workspace | `id` | Full refresh                | `created_at` |

Workspace requests use `sort=updated-at` and `filter[updated-at]=gte:<timestamp>` after the first sync.
Full refresh omits the time filter. Environment requests use `sort=created-at`.
The runs endpoint documents a creation filter but no update filter or sort parameter.
Runs use full refresh because a creation watermark would miss later status changes.
Users and state versions use `sort=created-at`. Neither route documents an account filter, so their requests send none.
Plans have only a by-ID route (`/plans/{plan}`), so the source reads them from the `included` part of the run list.
State versions require a workspace filter, so the source lists the workspaces and then reads each one.
A workspace that returns 404 during this fan-out is skipped. A resumed fan-out skips the workspaces it finished.
State version requests are left out of HTTP sample capture, because the response holds the state file.
The source removes the base64 `state` attribute and the values of sensitive outputs, because they can hold secrets.

The billing usage report (`/reports/billing`) is not a table.
Its rows have no ID and no period, and a required date range sets what each row counts.
The runs table holds the same run counts per workspace and period.

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
- [User list](https://docs.scalr.io/reference/get_users)
- [Plan](https://docs.scalr.io/reference/get_plan)
- [State version list](https://docs.scalr.io/reference/list_state_versions)
- [Billing usage report](https://docs.scalr.io/reference/list_billing_usage)
- [API tokens](https://docs.scalr.io/reference/api-tokens)
