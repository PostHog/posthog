# AppFollow API inventory

Reference for the endpoints this source syncs. AppFollow API v2, base URL `https://api.appfollow.io/api/v2`,
auth via the `X-AppFollow-API-Token` header. Docs: <https://docs.api.appfollow.io/reference/overview>.

> **Verification status:** the response shapes below are reconstructed from the public API docs and the
> open-source Airbyte `source-appfollow` connector (which confirms `app_collections`, `app_lists`,
> `users`, and `ratings` shapes). We did **not** have an API token to curl-verify the `reviews` and
> `ratings_history` request/response details live, so a few field names and the `last_modified` format
> are best-effort — see the inline notes in `appfollow.py`.

## Cost & limits

- Rate limits: 1000 requests/hour per token, 10000 requests/hour per account.
- Credit-based cost model: 1–100 credits per request. Reviews cost 10 credits/request; ratings history
  costs 10 credits plus a recurring per-30-day charge. Hence `reviews` default-syncs but
  `ratings_history` and `users` are opt-in.
- Pagination only functions when filtering by `ext_id` (not `collection_name`), so every per-app
  fan-out request passes `ext_id`.

## Endpoints

| Schema            | Path                                                                    | Shape                                 | Rows under | Primary key                   | Incremental                   | Default sync |
| ----------------- | ----------------------------------------------------------------------- | ------------------------------------- | ---------- | ----------------------------- | ----------------------------- | ------------ |
| `app_collections` | `/account/apps`                                                         | single request                        | `apps`     | `[id]`                        | — (full refresh)              | ✅           |
| `app_lists`       | `/account/apps/app?apps_id=<id>`                                        | fan-out over collections              | `apps_app` | `[app_collection_id, app_id]` | — (full refresh)              | ✅           |
| `users`           | `/account/users`                                                        | single request                        | root list  | `[id]`                        | — (full refresh)              | ❌           |
| `reviews`         | `/reviews?ext_id=<ext_id>&from=&to=&page=`                              | fan-out over apps, page/`pages_count` | `reviews`  | `[ext_id, review_id]`         | `updated` via `last_modified` | ✅           |
| `ratings_history` | `/meta/ratings/history?ext_id=<ext_id>&store=&from=&to=&offset=&limit=` | fan-out over apps, offset/limit       | `ratings`  | `[ext_id, store, date]`       | `date` via `from`             | ❌           |

## Discovery chain

AppFollow is app-centric: most data is queried per app by its store `ext_id`, and the only way to
enumerate a workspace's apps is:

```text
/account/apps            -> collections (id, title, title_normalized)
  /account/apps/app?apps_id=<id>  -> apps (ext_id, store, app_id) per collection
```

`reviews` and `ratings_history` iterate the discovered apps. `reviews` keys on `ext_id`;
`ratings_history` also needs `store` (and passes `collection_name` from the parent collection).

## Incremental notes

- `reviews`: the `updated` field is the review's last-modified timestamp; the server-side `last_modified`
  filter drives the delta. `from`/`to` are required and filter the publication `date`, so we open the
  window to `DEFAULT_START_DATE`..today and let `last_modified` do the incremental work.
- `ratings_history`: `type=total` returns one dated snapshot per day; the `from` date filter is the
  incremental cursor (past snapshots don't change, so `from`=watermark is safe).
