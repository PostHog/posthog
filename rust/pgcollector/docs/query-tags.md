# Query tags

A query tag is a key/value pair a client puts in a SQL comment so a statement can be
attributed to the code that ran it, rather than to its text.
pgcollector parses the tags out, stores them next to the statement, and pgapi groups,
filters and labels queries by them.

## What a client writes

Three comment shapes are accepted, because all three already run against our clusters:

| shape | example | where it comes from |
| --- | --- | --- |
| SQLCommenter | `/* route='/api/x', controller='PersonViewSet' */` | OpenTelemetry and Datadog instrumentation; values are percent-encoded |
| SQLCommenter | `/* service='personhog-identity', operation='merge_flip_lock_persons' */` | Rust services: `op = "..."` on `common_sqlx_macros::mirrored_query!` and `personhog_common::query_tag!` for statements built at runtime |
| colon pairs | `/* team_id:42 query_type:recording_api_list_blocks */` | the shape PostHog uses for ClickHouse, reused by the CDP and replay services |
| ingestion prefix | `/* nodejs:PERSONS_WRITE:Tx<insertPerson:ingestion/merge> */` | `nodejs/src/common/utils/db/postgres.ts` |

A comment is a tag comment only when every token in it is a `key=value` or `key:value` pair.
Prose comments and planner hints stay in the text, and comment markers inside string literals, dollar quotes and `--` comments are never read as tags.
Tag values are stored as written: they are metadata the application chose to attach, not SQL literals, so redaction does not apply to them.
A statement may carry several tag comments; later ones override earlier keys.

**Put the comment at the front of the statement.**
`pg_stat_activity.query` is cut at `track_activity_query_size` (1 KB by default), so a trailing comment on a long statement never reaches the activity sampler.
Logged statements are complete, so a trailing SQLCommenter block still works there.

## Keys

Keys are lower-cased.
Two classes exist:

**Dimensions** describe a code path and are stored in the `tags` jsonb column of every statement-bearing table.
They can be grouped and filtered on.
Use these names so different services line up:

| key | meaning | example |
| --- | --- | --- |
| `service` | the process type or crate | `web`, `celery`, `temporal`, `nodejs`, `personhog-identity` |
| `route` | HTTP route pattern | `/api/projects/{id}/persons/` |
| `controller`, `action` | handler and method | `PersonViewSet`, `list` |
| `task` | Celery task name | `posthog.tasks.calculate_cohort` |
| `workflow`, `activity` | Temporal workflow and activity types | `batch-export`, `insert_into_s3` |
| `operation` | the named query in a repository or service | `updatePersonsBatch`, `merge_flip_lock_persons` |
| `caller` | the call site behind an operation | `ingestion/person-update-conflict` |
| `db_use` | which pool a Node service used | `PERSONS_WRITE` |
| `tx` | `true` when the statement ran inside an explicit transaction | |
| `product` | owning product area | `replay` |
| `query_type` | a hand-named query | `recording_api_list_blocks` |
| `team_id`, `user_id` | the tenant or actor | `42` |

`team_id` has many values, so group on it only inside a narrow range.
Any other key is stored as-is and can be grouped on; it just will not line up with other services.

**Context** identifies one request and is never grouped on:
`traceparent`, `tracestate`, `trace_id`, `span_id`, `request_id`, `x-request-id`, `session_id`, `task_id`, `job_id`, `run_id`, `workflow_id`, `activity_id`, `txid`.
These are dropped, except that a trace id (`trace_id`, or the second field of `traceparent`) is kept in a `trace_id` column on per-sample rows so a slow statement can be followed into its trace.

The ingestion prefix `nodejs:<DB_USE>[:Tx]<operation[:caller]>` is expanded into `service=nodejs`, `db_use`, `operation`, `caller` and `tx`.

## What can and cannot be attributed

`pg_stat_statements` hashes the parse tree, and comments are not part of it.
Every caller of a statement shares one `queryid` and one set of counters, and the stored text is whichever call the extension saw first.
So the collector cannot split `calls` or `total_exec_time` by tag.
What it does instead:

| source | table | tags |
| --- | --- | --- |
| `pg_stat_activity` every 10 s | `ts_activity_samples` | grouped by tag set; the API turns backend counts into average active sessions per code path |
| `pg_stat_activity` (long or blocked sessions) | `ts_activity_sessions` | per session, with `trace_id` |
| statement log (`log_min_duration_sample`) | `ts_query_latency` | one histogram per statement, minute and tag set; this is where per-tag calls, time and p50/p95/p99 come from |
| statement log (slow statements, plans) | `ts_query_durations`, `ts_log_plans` | per statement, with `trace_id` |
| statement log (errors, temp files) | `ts_log_errors`, `ts_temp_files` | per statement, with `trace_id` |
| `pg_stat_statements` text | `cur_queries` | tags of the first call seen, text stored without the tag comment |

In pgapi:

- `GET /servers/{id}/tags?key=operation` (MCP `query_tags`) is the per-code-path view.
- `GET /servers/{id}/queries?tags=operation=updatePersonsBatch` keeps the `pg_stat_statements` rows for queries seen with that tag in a sampled source inside the range. Their totals still include every caller. Percent-encode a value that contains a comma.
- `GET /servers/{id}/queries/{queryid}` returns `callers`: the tag sets seen while that query ran, with each set's share of samples.

## Adding tags to a declarative collector

A YAML collector selects the raw comment text into a column and names it under `tags:`:

```yaml
tags:
  from: query_tags_raw   # the column holding the statement text; replaced by `tags`
  trace_id: true         # also emit trace_id (per-sample rows only)
  merge:                 # for aggregates grouped by the statement text in SQL
    sum: [backends]
    max: [max_query_age_s]
query: |
  SELECT ..., query AS query_tags_raw
```

`merge` exists because a SQL `GROUP BY` on the statement text splits one code path into one row per request id or literal.
Once the context keys are gone those rows collide, and `merge` adds them back together.
