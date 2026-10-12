# SurveyMonkey API inventory

REST/JSON API at `https://api.surveymonkey.com/v3` (regional variants:
`https://api.eu.surveymonkey.com/v3`, `https://api.surveymonkey.ca/v3`).
Auth: `Authorization: bearer <access_token>` (private-app static token or OAuth2 bearer).
All list endpoints page with `page` / `per_page` and return
`{data: [...], page, per_page, total, links: {self, next, ...}}`. We follow `links.next`.

| Schema             | Path                                       | Grain          | Primary key | Pagination    | Incremental cursor                    | Partition (stable) |
| ------------------ | ------------------------------------------ | -------------- | ----------- | ------------- | ------------------------------------- | ------------------ |
| `surveys`          | `/surveys`                                 | account        | `id`        | `links.next`  | `date_modified` (`start_modified_at`) | `date_created`     |
| `survey_responses` | `/surveys/{survey_id}/responses/bulk`      | fan-out/survey | `id`        | `links.next`  | `date_modified` / `date_created`      | `date_created`     |
| `survey_pages`     | `/surveys/{survey_id}/pages`               | fan-out/survey | `id`        | `links.next`  | full refresh                          | —                  |
| `survey_questions` | `/surveys/{survey_id}/details` (extracted) | fan-out/survey | `id`        | none (1 call) | full refresh                          | —                  |
| `collectors`       | `/surveys/{survey_id}/collectors`          | fan-out/survey | `id`        | `links.next`  | full refresh                          | —                  |

Fan-out endpoints first enumerate every survey id via `/surveys`, then page the child
resource per survey. `survey_questions` is flattened from the nested `pages[].questions[]`
of `/surveys/{id}/details` to avoid a 2-level (`/pages/{page_id}/questions`) fan-out.
`survey_pages`/`collectors`/`survey_questions` rows are stamped with their `survey_id`
(and `page_id` for questions).

## Incremental sync

- `/surveys` documents `start_modified_at` (and `sort_by=date_modified`, `sort_order=ASC`),
  so `date_modified` is the only viable cursor (the sort enum is title/date_modified/
  num_responses and there is no `start_created_at` filter).
- `/surveys/{id}/responses/bulk` documents both `start_modified_at` and `start_created_at`,
  so either timestamp works as a cursor.

For fan-out incremental (`survey_responses`) the cursor is applied per-survey; the pipeline
watermark is the global max across surveys. `sort_mode="asc"` advances the watermark to the
running max after each page, which is correct on a completed sync. A hard crash without a
Redis resume could advance the watermark past unfetched older rows in a later survey — the
same edge case every incremental source carries — mitigated here by resumable state.

## Verification gaps

API behavior was confirmed against the public docs but **not** curl-verified against a live
account (no credentials available at implementation time). In particular:

- responses/bulk's `start_modified_at`/`start_created_at` filtering was confirmed from docs,
  not a future-date smoke test.
- responses/bulk sort ordering is undocumented, so we do **not** send `sort_by` there and
  rely on `links.next` for pagination.
- `collectors` is left full-refresh / unpartitioned because the list returns only
  `id`/`name`/`href` by default (no stable date field confirmed).

Revisit these once a live token is available; tighten incremental/sort behavior accordingly.
