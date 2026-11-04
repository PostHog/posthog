# SendGrid (Twilio) — endpoint inventory

SendGrid v3 REST API. Base URL `https://api.sendgrid.com/v3`. Auth: `Authorization: Bearer <API key>`.

Docs: <https://www.twilio.com/docs/sendgrid/api-reference>

## Verification status

Endpoint existence and the 401/403 auth contract were confirmed with `curl` against the live API
(every endpoint below returns `401 {"errors":[{"message":"unauthorized"}]}` without a key). Behaviour
that needs a **valid** key — that `start_time` actually filters server-side, exact response ordering,
and `_metadata.next` shape — was taken from the public docs and the Airbyte/Fivetran SendGrid
connectors; it was **not** re-confirmed with live credentials (none available in this environment). The
conservative failure mode if `start_time` were silently ignored is a full re-fetch that merge-dedupes
on the primary key — wasted API calls, not corrupted data.

## Endpoints

| Schema                           | Path                                                                   | Pagination    | Data shape            | Primary key                                                        | Incremental                          |
| -------------------------------- | ---------------------------------------------------------------------- | ------------- | --------------------- | ------------------------------------------------------------------ | ------------------------------------ |
| `bounces`                        | `/suppression/bounces`                                                 | limit/offset  | bare array            | `email`                                                            | `created` (epoch) via `start_time`   |
| `blocks`                         | `/suppression/blocks`                                                  | limit/offset  | bare array            | `email`                                                            | `created` (epoch) via `start_time`   |
| `invalid_emails`                 | `/suppression/invalid_emails`                                          | limit/offset  | bare array            | `email`                                                            | `created` (epoch) via `start_time`   |
| `spam_reports`                   | `/suppression/spam_reports`                                            | limit/offset  | bare array            | `email`                                                            | `created` (epoch) via `start_time`   |
| `global_unsubscribes`            | `/suppression/unsubscribes`                                            | limit/offset  | bare array            | `email`                                                            | `created` (epoch) via `start_time`   |
| `stats`                          | `/stats`                                                               | none (single) | nested daily stats    | `date`                                                             | `date` via `start_date` (YYYY-MM-DD) |
| `unsubscribe_groups`             | `/asm/groups`                                                          | none (single) | bare array            | `id`                                                               | full refresh                         |
| `marketing_lists`                | `/marketing/lists`                                                     | `_metadata`   | `{"result": [...]}`   | `id`                                                               | full refresh                         |
| `templates`                      | `/templates`                                                           | `_metadata`   | `{"result": [...]}`   | `id`                                                               | full refresh                         |
| `message_activity`               | `/messages`                                                            | query window  | `{"messages": [...]}` | `msg_id`                                                           | `last_event_time` via `query`        |
| `unsubscribe_group_suppressions` | `/asm/suppressions`                                                    | none (single) | bare array            | `group_id`, `email`                                                | full refresh                         |
| `singlesends`                    | `/marketing/singlesends`                                               | `_metadata`   | `{"result": [...]}`   | `id`                                                               | full refresh                         |
| `singlesend_stats`               | `/marketing/stats/singlesends`                                         | `_metadata`   | `{"results": [...]}`  | `id`, `ab_variation`, `ab_phase`                                   | full refresh                         |
| `singlesend_link_stats`          | `/marketing/stats/singlesends/{id}/links` (fan-out over `singlesends`) | `_metadata`   | `{"results": [...]}`  | `singlesend_id`, `url`, `url_location`, `ab_variation`, `ab_phase` | full refresh                         |
| `categories`                     | `/categories`                                                          | limit/offset  | bare array            | `category`                                                         | full refresh                         |
| `category_stats`                 | `/categories/stats` (fan-out over `categories`)                        | none (single) | nested daily stats    | `category`, `date`                                                 | `date` via `start_date` (YYYY-MM-DD) |
| `automation_stats`               | `/marketing/stats/automations`                                         | `_metadata`   | `{"results": [...]}`  | `id`, `aggregation`, `step_id`                                     | full refresh                         |
| `automation_link_stats`          | `/marketing/stats/automations/{id}/links` (fan-out)                    | `_metadata`   | `{"results": [...]}`  | `automation_id`, `url`, `url_location`, `step_id`                  | full refresh                         |

Notes:

- The suppression endpoints return a bare JSON array of records (`{created, email, reason, status}`,
  shape varies slightly per endpoint) and accept `limit` (max 500), `offset`, `start_time`, `end_time`
  (Unix epoch seconds). `created` is immutable, so it doubles as the datetime partition key.
- The marketing/template endpoints wrap rows in `{"result": [...], "_metadata": {"next": "<absolute url>"}}`
  and paginate by following `_metadata.next`. `/templates` requires `generations=legacy,dynamic` to return
  both template types. Neither exposes a server-side timestamp filter, so both are full-refresh only.
- `/asm/groups` returns the full set of unsubscribe groups in a single response with no pagination params.
- `/stats` returns global email statistics as a bare array of `{date, stats: [{metrics: {...}}]}`
  buckets. With `aggregated_by=day` (and no breakdown dimension) each bucket holds one `metrics`
  object, so it flattens to one flat row per day carrying `requests`, `delivered`, `opens`,
  `clicks`, `bounces`, `spam_reports`, etc. — the send-side denominators the suppression tables
  lack. `start_date` (YYYY-MM-DD) is a real server-side filter, so it syncs incrementally on the
  daily `date`; it is also required on every request, so the first sync backfills a fixed window.
  Free on every SendGrid plan (`stats.read`).
- `/messages` (Email Activity API) is the only per-recipient engagement record the API exposes, and it is
  synced as the opt-in `message_activity` table. It has no cursor or offset: `limit` (max 1000, default 10)
  only caps how many of the most recent matches come back, so the sync pages by narrowing the required
  `query=last_event_time BETWEEN TIMESTAMP "…" AND TIMESTAMP "…"` window newest to oldest until a short
  page (`sort_mode="desc"`; the pipeline defers the watermark to the end of a successful run). Grain is one
  row per message (`msg_id`), mutated in place as new events land (`status`, `opens_count`, `clicks_count`,
  `last_event_time`) — which makes the table merge-only, unpartitioned, and lets `last_event_time` double
  as the incremental cursor: an old message with a new event re-enters the window. Access requires the paid
  "additional email activity history" add-on (30 days of history, hence the 30-day first-sync backfill);
  accounts without it — including reseller accounts (Azure/GCP/Heroku), which cannot buy it — get 403
  however the key is scoped (`email_activity.read`), so the table ships `should_sync_default=False` with a
  `permission_note`. Rate limit is 6 requests/minute (429 + `X-RateLimit-Reset` epoch header, honored by
  the shared REST transport). Query syntax, `limit` cap, and the response shape were verified against the
  public docs only — no add-on credentials were available; the conservative failure mode of the inclusive
  window bounds is boundary re-fetches that merge dedupes on `msg_id`.
- The Event Webhook delivers the same event types at no extra cost and in near real time, but SendGrid
  allows a single webhook URL per account, so registering ours can silently break or replace a consumer the
  customer already runs. Webhook ingestion therefore stays parked as a separate product decision;
  `/messages` is the only per-event path wired here.
- Scopes are per endpoint, so a key that reads one table often can't read another.
  `settings.py` records each endpoint's scope as `/v3/scopes` spells it (`suppression.bounces.read`,
  `asm.groups.read`, `marketing.read`, `templates.read`), and `get_endpoint_permissions` probes them so the
  schema picker can disable what the key can't reach.
- `unsubscribe_group_suppressions` reads `/asm/suppressions`, which returns every unsubscribe group
  membership as `{email, group_id, group_name, created_at}` in one unpaginated response. The per-group
  `/asm/groups/{group_id}/suppressions` returns only bare email strings, so it would need a fan-out
  over `/asm/groups` and still lack the creation time. Neither takes a time filter.
- The Single Send endpoints (`singlesends`, `singlesend_stats`, `singlesend_link_stats`) follow
  `_metadata.next` like the other marketing endpoints. The stats endpoints cap `page_size` at 50.
- `categories` reads `/categories`, a bare array of `{category}` paged by `limit`/`offset`. No maximum
  `limit` is documented, so it pages at the documented default of 50: a silently capped page would read
  as the short last page and end the walk early.
- `/categories/stats` requires `categories` (up to 10 names) and `start_date`, so `category_stats` fans
  out over `categories` with one category per request and `aggregated_by=day`. Each response is the
  same `{date, stats: [{name, type, metrics}]}` nesting as `/stats`, flattened to one row per category
  and day. Category names are free text, so the name is percent-encoded before it goes into the query
  string. `start_date` filters server-side, so the table syncs incrementally on `date`. Rows come one
  category at a time, so they declare no sort order. The listing needs `categories.read` and the stats
  need `categories.stats.read`, so the permission probe calls `/categories/stats` itself with a
  placeholder category. `/categories/stats/sums` is not synced: it sums the same metrics over a date
  range, which a query over `category_stats` can do.
- The Automation endpoints (`automation_stats`, `automation_link_stats`) follow `_metadata.next` and
  cap `page_size` at 50, like the Single Send stats. The API has no Automation listing, so the link
  fan-out reads the Automation ids from the stats rows (one lifetime-total row per Automation without
  `group_by`).
- `/marketing/contacts` is not synced. It returns a sample of up to 50 recent contacts, and its pagination
  is deprecated. The full set needs the asynchronous export job (`POST /marketing/contacts/exports`, poll
  the status, then download the files), and the public spec does not document the file layout.
  `singlesend_stats` sends no `singlesend_ids`, so it returns lifetime totals for every Single Send;
  without `group_by` each row has `ab_variation` and `ab_phase` set to `all`. `singlesend_link_stats`
  fans out over `singlesends`, and a 404 for a Single Send deleted mid-sync is skipped. No Single Send
  endpoint takes a time filter, so all three are full refresh. They need `marketing.read` and an
  account with Marketing Campaigns, like `/marketing/lists`.
- `/marketing/contacts` is not synced. The GET returns a sample of at most 50 recent contacts. The full
  set needs an asynchronous export job (`POST /marketing/contacts/exports`, then poll, then download
  files from S3 links), which creates a job in the customer's account.
- `/marketing/lists` is the outlier: it needs `marketing.read` **and** an account with Marketing Campaigns.
  Accounts without it, and accounts still on legacy Marketing Campaigns (a different API, scoped
  `marketing_campaigns.read`), return 403 no matter how the key is scoped, so the table can be genuinely
  unsyncable rather than misconfigured.
