# SparkPost API inventory

SparkPost (now part of Bird) — transactional & marketing email delivery. REST/JSON.

- **Hosts (independent stacks, no shared data):** US `https://api.sparkpost.com`, EU `https://api.eu.sparkpost.com`. User picks the region.
- **Auth:** API key passed verbatim in the `Authorization` header (no `Bearer` prefix).
- **Rate limiting:** dynamic; `429` with a 1–5s back-off hint. Pagination requests count against the limit. Handled with bounded `tenacity` retries on `429`/`5xx`.
- **Credential probe:** `GET /api/v1/account`.

## Endpoints

| Schema                        | Path                                                     | Pagination             | Primary key                                         | Partition key | Incremental                        |
| ----------------------------- | -------------------------------------------------------- | ---------------------- | --------------------------------------------------- | ------------- | ---------------------------------- |
| `events`                      | `/api/v1/events/message`                                 | cursor                 | `event_id`                                          | `timestamp`   | yes — `from` filter on `timestamp` |
| `suppression_list`            | `/api/v1/suppression-list`                               | cursor                 | `recipient`, `type`                                 | `created`     | no (full refresh)                  |
| `recipient_lists`             | `/api/v1/recipient-lists`                                | none                   | `id`                                                | —             | no (full refresh)                  |
| `templates`                   | `/api/v1/templates`                                      | none                   | `id`                                                | —             | no (full refresh)                  |
| `sending_domains`             | `/api/v1/sending-domains`                                | none                   | `domain`                                            | —             | no (full refresh)                  |
| `subaccounts`                 | `/api/v1/subaccounts`                                    | none                   | `id`                                                | —             | no (full refresh)                  |
| `webhooks`                    | `/api/v1/webhooks`                                       | none                   | `id`                                                | —             | no (full refresh)                  |
| `deliverability_time_series`  | `/api/v1/metrics/deliverability/time-series`             | none (`precision=day`) | `ts`                                                | `ts`          | yes — `from` filter on `ts`        |
| `deliverability_by_template`  | `/api/v1/metrics/deliverability/template`                | daily window           | `date`, `template_id`                               | `date`        | yes — daily `from`/`to` on `date`  |
| `bounce_reasons`              | `/api/v1/metrics/deliverability/bounce-reason`           | daily window           | `date`, `reason`, `classification_id`               | `date`        | yes — daily `from`/`to` on `date`  |
| `bounce_reasons_by_domain`    | `/api/v1/metrics/deliverability/bounce-reason/domain`    | daily window           | `date`, `reason`, `domain`, `classification_id`     | `date`        | yes — daily `from`/`to` on `date`  |
| `rejection_reasons`           | `/api/v1/metrics/deliverability/rejection-reason`        | daily window           | `date`, `reason`, `rejection_category_id`           | `date`        | yes — daily `from`/`to` on `date`  |
| `rejection_reasons_by_domain` | `/api/v1/metrics/deliverability/rejection-reason/domain` | daily window           | `date`, `reason`, `domain`, `rejection_category_id` | `date`        | yes — daily `from`/`to` on `date`  |
| `delay_reasons`               | `/api/v1/metrics/deliverability/delay-reason`            | daily window           | `date`, `reason`                                    | `date`        | yes — daily `from`/`to` on `date`  |
| `delay_reasons_by_domain`     | `/api/v1/metrics/deliverability/delay-reason/domain`     | daily window           | `date`, `reason`, `domain`                          | `date`        | yes — daily `from`/`to` on `date`  |

## Notes / gotchas

- **Response shape:** every list endpoint wraps records in `{"results": [...]}`.
- **Cursor pagination:** opt in by sending `cursor=initial` + `per_page` on the first request, then follow the
  `links` array entry with `rel: next` (the `href` is a path relative to the API host). The management list
  endpoints return a single page.
- **Event retention is 10 days**, so the first sync of `events` is bounded to that window
  (`default_lookback_days=10`).
- **`from` is inclusive, `to` exclusive.** We send only `from` (open upper bound) and map it from the stored
  watermark; the boundary event is re-fetched and deduped on `event_id` by the merge.
- **Verification caveat:** endpoint hosts and `401` error shape were confirmed with unauthenticated curl. The
  server-side behaviour of `from`/`to` filtering, the exact cursor-link format, and event sort order could not
  be exercised end-to-end without a live API key, so they follow the public SparkPost docs. Only `events` is
  marked incremental (the one endpoint with a documented server-side timestamp filter); everything else ships
  full refresh and dedupes on its primary key.
- **Webhooks:** SparkPost exposes a programmatic Event Webhooks API (`/api/v1/webhooks`). This source pulls the
  webhook _configuration_ as a table but does not (yet) register PostHog as a push destination — a future
  `WebhookSource` enhancement.
- **Metrics API:** data is retained for 6 months, so the first sync of a metrics table reaches back 180 days.
  `from` is required on every route. The breakdown routes (template, bounce/rejection/delay reason) return one
  total for the whole `from`/`to` window and have no time column, so the source requests one UTC day per call
  (`from=<day>T00:00&to=<day>T23:59`) and adds a `date` column. An incremental run re-fetches the watermark day,
  because it was usually still in progress at the last sync. The Deliverability Add-On metrics (seed and panel
  counts) are not requested, because accounts without the add-on cannot request them. The breakdowns have no
  pagination; `limit=10000` (the maximum) caps the rows per day.
- **Transmissions are not synced.** The current API reference has no list call for transmissions. The only read
  call, `GET /api/v1/transmissions/{id}`, is deprecated and returns only scheduled (future) transmissions.
