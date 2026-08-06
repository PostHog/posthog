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

| Schema                | Path                          | Pagination    | Data shape          | Primary key | Incremental                        |
| --------------------- | ----------------------------- | ------------- | ------------------- | ----------- | ---------------------------------- |
| `bounces`             | `/suppression/bounces`        | limit/offset  | bare array          | `email`     | `created` (epoch) via `start_time` |
| `blocks`              | `/suppression/blocks`         | limit/offset  | bare array          | `email`     | `created` (epoch) via `start_time` |
| `invalid_emails`      | `/suppression/invalid_emails` | limit/offset  | bare array          | `email`     | `created` (epoch) via `start_time` |
| `spam_reports`        | `/suppression/spam_reports`   | limit/offset  | bare array          | `email`     | `created` (epoch) via `start_time` |
| `global_unsubscribes` | `/suppression/unsubscribes`   | limit/offset  | bare array          | `email`     | `created` (epoch) via `start_time` |
| `unsubscribe_groups`  | `/asm/groups`                 | none (single) | bare array          | `id`        | full refresh                       |
| `marketing_lists`     | `/marketing/lists`            | `_metadata`   | `{"result": [...]}` | `id`        | full refresh                       |
| `templates`           | `/templates`                  | `_metadata`   | `{"result": [...]}` | `id`        | full refresh                       |

Notes:

- The suppression endpoints return a bare JSON array of records (`{created, email, reason, status}`,
  shape varies slightly per endpoint) and accept `limit` (max 500), `offset`, `start_time`, `end_time`
  (Unix epoch seconds). `created` is immutable, so it doubles as the datetime partition key.
- The marketing/template endpoints wrap rows in `{"result": [...], "_metadata": {"next": "<absolute url>"}}`
  and paginate by following `_metadata.next`. `/templates` requires `generations=legacy,dynamic` to return
  both template types. Neither exposes a server-side timestamp filter, so both are full-refresh only.
- `/asm/groups` returns the full set of unsubscribe groups in a single response with no pagination params.
- Rate limits: most v3 endpoints are generous, but the Email Activity API (`/messages`, deliberately not
  synced here) is capped at ~6 req/min — webhook ingestion is the recommended path for per-event data and
  is left as a follow-up.
- Scopes are per endpoint, so a key that reads one table often can't read another.
  `settings.py` records each endpoint's scope as `/v3/scopes` spells it (`suppression.bounces.read`,
  `asm.groups.read`, `marketing.read`, `templates.read`), and `get_endpoint_permissions` probes them so the
  schema picker can disable what the key can't reach.
- `/marketing/lists` is the outlier: it needs `marketing.read` **and** an account with Marketing Campaigns.
  Accounts without it, and accounts still on legacy Marketing Campaigns (a different API, scoped
  `marketing_campaigns.read`), return 403 no matter how the key is scoped, so the table can be genuinely
  unsyncable rather than misconfigured.
