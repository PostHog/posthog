# AppFollow API inventory

Reference for the endpoints this source syncs. AppFollow API v2, base URL `https://api.appfollow.io/api/v2`,
auth via the `X-AppFollow-API-Token` header. Docs: <https://docs.api.appfollow.io/reference/overview>.

> **Verification status:** every path and query parameter below was checked against the published v2
> OpenAPI definition for that endpoint. Response shapes are a different matter: AppFollow publishes an
> **empty 200 schema for every v2 endpoint**, so no envelope key or row field is documented anywhere.
> Those columns are reconstructed from the docs, the open-source Airbyte `source-appfollow` connector
> (which confirms `app_collections`, `app_lists`, `users`, and `ratings`), and the shape of the
> product's own UI. We did **not** have an API token to curl-verify anything live, so field names, the
> `last_modified` format, and the envelope keys marked "unpublished" below are best-effort — see the
> inline notes in `appfollow.py`. `_extract_rows` takes candidate envelope keys and falls back to a
> root list for those endpoints, so a wrong guess yields an empty table rather than a wrong one.

## Cost & limits

- Rate limits: 1000 requests/hour per token, 10000 requests/hour per account.
- Credit-based cost model: 1–100 credits per request. Reviews cost 10 credits/request; ratings history
  costs 10 credits plus a recurring per-30-day charge. Hence `reviews` default-syncs but
  `ratings_history` and `users` are opt-in.
- Pagination only functions when filtering by `ext_id` (not `collection_name`), so every per-app
  fan-out request passes `ext_id`.

## Endpoints

| Schema            | Path                                                                    | Shape                                 | Rows under  | Primary key                                 | Incremental                   | Default sync |
| ----------------- | ----------------------------------------------------------------------- | ------------------------------------- | ----------- | ------------------------------------------- | ----------------------------- | ------------ |
| `app_collections` | `/account/apps`                                                         | single request                        | `apps`      | `[id]`                                      | — (full refresh)              | ✅           |
| `app_lists`       | `/account/apps/app?apps_id=<id>`                                        | fan-out over collections              | `apps_app`  | `[app_collection_id, app_id]`               | — (full refresh)              | ✅           |
| `users`           | `/account/users`                                                        | single request                        | root list   | `[id]`                                      | — (full refresh)              | ❌           |
| `reviews`         | `/reviews?ext_id=<ext_id>&from=&to=&page=`                              | fan-out over apps, page/`pages_count` | `reviews`   | `[ext_id, review_id]`                       | `updated` via `last_modified` | ✅           |
| `ratings_history` | `/meta/ratings/history?ext_id=<ext_id>&store=&from=&to=&offset=&limit=` | fan-out over apps, offset/limit       | `ratings`   | `[ext_id, store, date]`                     | `date` via `from`             | ❌           |
| `rankings`        | `/meta/rankings?ext_id=<ext_id>&date=`                                  | fan-out over apps, single request     | unpublished | `[ext_id, country, device, genre_id, date]` | — (full refresh)              | ❌           |
| `keywords`        | `/aso/keywords?ext_id=<ext_id>&date=&page=`                             | fan-out over apps, `page`             | unpublished | `[ext_id, country, device, date, keyword]`  | — (full refresh)              | ❌           |
| `app_versions`    | `/meta/versions?ext_id=<ext_id>&country=&page=`                         | fan-out over apps, `page`             | unpublished | `[ext_id, country, version]`                | — (full refresh)              | ❌           |
| `reviews_stats`   | `/reviews/stats?ext_id=<ext_id>&from=&to=`                              | fan-out over apps, single request     | unpublished | `[ext_id, date]`                            | `date` via `from`             | ❌           |

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
- `reviews_stats`: `from`/`to` bound the reported range, so `from`=watermark is the incremental cursor,
  exactly as for `ratings_history`.
- `rankings` and `keywords` take a single optional `date`, **not** a range. There is no server-side
  filter to drive a delta off, and one request per day per app would cost 10 credits each, so both sync
  as a full refresh of one day. We request today explicitly and stamp that date on every row, so the
  primary key and the partition key are populated even though the response schema is unpublished.
- `app_versions`: `/meta/versions` exposes no date parameter at all. Full refresh; the table is small.

## Pagination notes

- `keywords` and `app_versions` page with a bare 1-indexed `page`. Neither publishes a page count, a
  total, or a page-size parameter, so the walk can only end on an empty page. `MAX_PAGES_PER_APP` caps
  it and logs when the cap is reached.
- `rankings` and `reviews_stats` expose no pagination at all — one request per app is the whole walk.

## Country resolution

`/meta/versions` **requires** a `country`, and an app row does not reliably carry one. The fan-out
resolves it per app: the app's own `country`, then the nested `app.country`, then the collection's
`default_country`, then the first entry of the collection's `countries`, then `us`. An app tracked in
two collections with different countries is fetched once per country, because versions vary by country.
