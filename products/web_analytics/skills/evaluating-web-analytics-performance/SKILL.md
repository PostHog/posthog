---
name: evaluating-web-analytics-performance
description: >
  Investigate the performance of web analytics query runners by slicing
  `system.query_log` on the tags those runners emit. Use when a web analytics
  PR adds or renames a `query_type`/strategy tag and you want to verify the
  rollout, attribute slow tail latency to a specific strategy, or break a
  catch-all tag down by sub-dimension (breakdown, conversion goal, etc.).
  Wraps `query-clickhouse-via-metabase` with the web-analytics-specific
  tagging vocabulary and query patterns.
---

# Evaluating web analytics query performance

The web analytics query runners (`WebStatsTableQueryRunner`, `WebOverviewQueryRunner`, etc.) tag every ClickHouse query they execute with a `query_type` and — where it applies — a `breakdown_by`. Those tags land in `system.query_log.log_comment`, which makes per-strategy and per-breakdown latency answerable with a single Metabase query.

This skill is the playbook for that workflow. The mechanics of authenticating to Metabase and running queries live in [`query-clickhouse-via-metabase`](../../../../.agents/skills/query-clickhouse-via-metabase/SKILL.md) — open that skill first if you don't already have a cached cookie.

## When to use this

- A recent PR introduced or renamed web analytics `query_type` tags and you want to confirm the new tags are emitting in prod (and the old ones are tapering off).
- You see "web analytics is slow" reports and want to attribute the tail to a specific strategy.
- You want to break a catch-all tag like `stats_table_main_query` down by breakdown dimension (DeviceType vs Browser vs Country, etc.).
- You're considering a follow-up that would add a new query tag — sanity-check the current distribution first to see whether the segmentation is worth it.

## Tag vocabulary

The current set of web analytics `query_type` values, all in `system.query_log.log_comment.query_type`:

| Tag                                                            | Runner / strategy                                                |
| -------------------------------------------------------------- | ---------------------------------------------------------------- |
| `stats_table_main_query`                                       | `WebStatsTableQueryRunner` catch-all (Browser, OS, Country, ...) |
| `stats_table_path_bounce_query`                                | PAGE breakdown + bounce rate                                     |
| `stats_table_path_bounce_and_avg_time_query`                   | PAGE breakdown + avg time on page                                |
| `stats_table_frustration_metrics_query`                        | FRUSTRATION_METRICS breakdown                                    |
| `stats_table_entry_bounce_query`                               | INITIAL_PAGE + bounce rate                                       |
| `stats_table_preaggregated_query`                              | preagg tables, generic breakdown                                 |
| `stats_table_preaggregated_path_breakdown_query`               | preagg tables, PAGE breakdown                                    |
| `stats_table_preaggregated_entry_bounce_query`                 | preagg tables, INITIAL_PAGE + bounce                             |
| `web_overview_lazy_query` / `web_overview_lazy_insert`         | overview lazy precompute (read / INSERT)                         |
| `web_stats_lazy_query` / `web_stats_<breakdown>_lazy_insert`   | stats lazy precompute (read / INSERT)                            |
| `web_stats_paths_lazy_query` / `web_stats_paths_lazy_insert`   | paths lazy precompute (read / INSERT)                            |
| `web_vitals_paths_lazy_query` / `web_vitals_paths_lazy_insert` | vitals path-breakdown lazy precompute (read / INSERT)            |
| `external_clicks_query`                                        | `WebExternalClicksTableQueryRunner`                              |
| `web_overview_query` / `web_overview_preaggregated_query`      | overview raw / V2                                                |
| `web_goals_query`                                              | goals                                                            |
| `web_vitals_path_breakdown_query`                              | vitals path breakdown (raw)                                      |

These are not stable forever — when in doubt, grep for `query_type=` under `products/web_analytics/backend/hogql_queries/` to get the current truth.

Additional segmentation fields in `log_comment` for web analytics queries:

- `breakdown_by` — top-level since the `tag_queries(breakdown_by=...)` hook in `WebAnalyticsQueryRunner.calculate`. Avoids the older `JSONExtractString(JSONExtractRaw(log_comment, 'query'), 'breakdownBy')` dance.
- `query.breakdownBy` — same value, but nested under the full query JSON. Fall back to this if you're querying historical data from before the top-level tag existed, or for runners that don't go through the central tagging hook.
- `team_id`, `user_id`, `route_id`, `access_method`, `workload`, `kind` — generic; useful for filtering out cache warming, MCP traffic, personal API key calls, etc.

## Investigation workflow

1. **Establish the question.**
   - "Are the new tags emitting since deploy at T?" → timeline query bucketed by `event_time`.
   - "What's the latency distribution by tag?" → per-`query_type` aggregate over a window post-deploy.
   - "What inside `stats_table_main_query` is slow?" → per-`breakdown_by` aggregate inside that single tag.
   - "Are lazy precompute jobs landing?" → split by `_lazy_query` vs `_lazy_insert` to see read/INSERT volume separately.

2. **Pick a window that covers the deploy.** Cutover for a rolling deploy in prod is typically 20–60 min after merge. Bucket by 15 minutes for the first few hours to see the transition.

3. **Run the right query pattern** (below). Use `--save /tmp/<name>.tsv` so rows land in a file rather than streaming through the conversation.

4. **Sanity-check the residue.** If an old tag is still emitting after the deploy, don't assume it's an unmigrated path on the runner you changed — `grep` the repo for the literal tag string. The lingering hits are often from a _different_ runner that reused the same hardcoded string.

5. **When proposing a new tag**, check whether `QueryTags` (`posthog/clickhouse/query_tagging.py`) already declares the field. Several useful fields (`breakdown_by`, `feature`, etc.) are defined but unused — wiring them up is one line.

## Query patterns

These are jumping-off points. Edit time windows and tag filters to your case. They run via `hogli metabase:query --region us --database-id <id>` (see `query-clickhouse-via-metabase` for the auth + DB-ID discovery loop).

### Tag distribution and latency post-deploy

```sql
SELECT
    JSONExtractString(log_comment, 'query_type') AS query_type,
    count() AS query_count,
    round(avg(query_duration_ms), 1) AS avg_duration_ms,
    round(quantile(0.95)(query_duration_ms), 1) AS p95_duration_ms,
    round(quantile(0.99)(query_duration_ms), 1) AS p99_duration_ms,
    max(query_duration_ms) AS max_duration_ms,
    min(event_time) AS first_seen,
    max(event_time) AS last_seen
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 6 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'query_type') LIKE 'stats_table%'
GROUP BY query_type
ORDER BY query_count DESC
```

Adjust the `LIKE` to cover whichever family you're studying (`'web_overview%'`, `'web_vitals%'`, etc.).

### Rollout timeline by 15-minute bucket

```sql
SELECT
    toStartOfInterval(event_time, INTERVAL 15 MINUTE) AS bucket,
    countIf(JSONExtractString(log_comment, 'query_type') = 'stats_table_query') AS old_tag,
    countIf(JSONExtractString(log_comment, 'query_type') = 'stats_table_main_query') AS main,
    countIf(JSONExtractString(log_comment, 'query_type') = 'stats_table_path_bounce_query') AS path_bounce,
    countIf(JSONExtractString(log_comment, 'query_type') LIKE 'stats_table_preaggregated%') AS preaggregated,
    countIf(JSONExtractString(log_comment, 'query_type') LIKE '%_lazy_query') AS lazy_read,
    countIf(JSONExtractString(log_comment, 'query_type') LIKE '%_lazy_insert') AS lazy_insert
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 6 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'query_type') LIKE 'stats_table%'
GROUP BY bucket
ORDER BY bucket
```

A clean cutover looks like the old tag dropping ~10x within one bucket as the new tags pick up.

### Per-breakdown distribution inside a single tag

```sql
SELECT
    JSONExtractString(log_comment, 'breakdown_by') AS breakdown_by,
    count() AS cnt,
    round(avg(query_duration_ms), 1) AS avg_ms,
    round(quantile(0.95)(query_duration_ms), 1) AS p95_ms,
    round(quantile(0.99)(query_duration_ms), 1) AS p99_ms
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 4 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'query_type') = 'stats_table_main_query'
GROUP BY breakdown_by
ORDER BY cnt DESC
```

For data older than the top-level `breakdown_by` tag, fall back to:

```sql
JSONExtractString(JSONExtractRaw(log_comment, 'query'), 'breakdownBy') AS breakdown_by
```

### Lazy precompute read-vs-INSERT split

Useful to verify a lazy precompute rollout: reads dominate after the first INSERT for a `(team, query_hash, window)` triple, so a healthy roll-out has reads ≫ INSERTs as TTL warms the cache.

```sql
SELECT
    JSONExtractString(log_comment, 'query_type') AS query_type,
    count() AS cnt,
    round(avg(query_duration_ms), 1) AS avg_ms,
    round(quantile(0.95)(query_duration_ms), 1) AS p95_ms,
    round(quantile(0.99)(query_duration_ms), 1) AS p99_ms,
    uniqExact(JSONExtractInt(log_comment, 'team_id')) AS teams
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 6 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND (
        JSONExtractString(log_comment, 'query_type') LIKE '%_lazy_query'
        OR JSONExtractString(log_comment, 'query_type') LIKE '%_lazy_insert'
    )
GROUP BY query_type
ORDER BY query_type
```

Read tail rising faster than INSERT volume is a sign that something is degrading the merge path (e.g., parts not yet merged into the read shard, or load balancing routing reads off the writer replica).

### Source attribution for surprise traffic

When a tag is still emitting after you expected it to die, find out _who_ is sending it before chasing ghosts in the runner you modified:

```sql
SELECT
    JSONExtractString(log_comment, 'kind') AS kind,
    JSONExtractString(log_comment, 'access_method') AS access_method,
    JSONExtractString(log_comment, 'workload') AS workload,
    JSONExtractString(log_comment, 'route_id') AS route_id,
    count() AS cnt
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 3 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'query_type') = '<tag-you-are-investigating>'
GROUP BY kind, access_method, workload, route_id
ORDER BY cnt DESC
LIMIT 30
```

If the same tag comes from two different `route_id`s or runners, the second one is probably a sibling runner reusing the string — `grep` the repo.

### Filter usage and combinations

Two questions, one workflow. First, how many filters are users actually applying:

```sql
WITH web_queries AS (
    SELECT JSONExtractRaw(log_comment, 'query') AS query_json
    FROM clusterAllReplicas(posthog, system, query_log)
    WHERE event_time > now() - INTERVAL 6 HOUR
        AND type = 'QueryFinish'
        AND is_initial_query
        AND (
            JSONExtractString(log_comment, 'query_type') LIKE 'stats_table%'
            OR JSONExtractString(log_comment, 'query_type') LIKE 'web_%'
            OR JSONExtractString(log_comment, 'query_type') = 'external_clicks_query'
        )
        AND query_json != ''
)
SELECT
    length(JSONExtractArrayRaw(query_json, 'properties')) AS num_filters,
    count() AS query_count
FROM web_queries
GROUP BY num_filters
ORDER BY num_filters
```

Then which filter _combinations_ are actually run together. This is more useful than per-key counts because it shows real query patterns instead of summing across unrelated use cases:

```sql
WITH web_queries AS (
    SELECT
        JSONExtractRaw(log_comment, 'query') AS query_json,
        JSONExtractString(log_comment, 'query_type') AS query_type,
        query_duration_ms
    FROM clusterAllReplicas(posthog, system, query_log)
    WHERE event_time > now() - INTERVAL 6 HOUR
        AND type = 'QueryFinish'
        AND is_initial_query
        AND (
            JSONExtractString(log_comment, 'query_type') LIKE 'stats_table%'
            OR JSONExtractString(log_comment, 'query_type') LIKE 'web_%'
            OR JSONExtractString(log_comment, 'query_type') = 'external_clicks_query'
        )
        AND query_json != ''
)
SELECT
    arrayStringConcat(
        arraySort(
            arrayMap(
                p -> concat(JSONExtractString(p, 'type'), ':', JSONExtractString(p, 'key')),
                JSONExtractArrayRaw(query_json, 'properties')
            )
        ),
        ' + '
    ) AS filter_combo,
    length(JSONExtractArrayRaw(query_json, 'properties')) AS num_filters,
    count() AS cnt,
    round(avg(query_duration_ms), 1) AS avg_ms,
    round(quantile(0.95)(query_duration_ms), 1) AS p95_ms
FROM web_queries
GROUP BY filter_combo, num_filters
ORDER BY cnt DESC
LIMIT 40
```

Add `query_type` to the `SELECT` and `GROUP BY` to slice combos per strategy and answer "which strategy serves which combo." A signature appearing twice with the same key (`event:$geoip_city_name + event:$geoip_city_name`) usually means two operators applied to the same key (e.g. `is X` + `is_not Y`) — not a bug.

Cross-source combos (`event:` + `session:` filters together) tend to be markedly slower than same-source combos at the same row count — worth checking before assuming a slow query is purely a strategy problem.

### Failing queries

Look at exceptions in the same query window — the `query_log` keeps `QueryFinish`, `ExceptionWhileProcessing`, and `ExceptionBeforeStart` rows side by side, so distinguishing real errors from timeouts/cancellations is straightforward:

```sql
SELECT
    JSONExtractString(log_comment, 'query_type') AS query_type,
    exception_code,
    multiIf(
        exception_code = 159, 'TIMEOUT_EXCEEDED',
        exception_code = 160, 'TOO_SLOW',
        exception_code = 202, 'TOO_MANY_SIMULTANEOUS_QUERIES',
        exception_code = 241, 'MEMORY_LIMIT_EXCEEDED',
        exception_code = 386, 'NO_COMMON_TYPE',
        exception_code = 394, 'QUERY_WAS_CANCELLED',
        toString(exception_code)
    ) AS error_name,
    count() AS cnt,
    uniqExact(JSONExtractInt(log_comment, 'team_id')) AS teams_affected,
    round(avg(query_duration_ms), 1) AS avg_duration_ms,
    round(quantile(0.95)(query_duration_ms), 1) AS p95_duration_ms
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 24 HOUR
    AND type IN ('QueryFinish', 'ExceptionWhileProcessing', 'ExceptionBeforeStart')
    AND exception_code != 0
    AND is_initial_query
    AND (
        JSONExtractString(log_comment, 'query_type') LIKE 'stats_table%'
        OR JSONExtractString(log_comment, 'query_type') LIKE 'web_%'
        OR JSONExtractString(log_comment, 'query_type') = 'external_clicks_query'
    )
GROUP BY query_type, exception_code, error_name
ORDER BY cnt DESC
LIMIT 50
```

When you see an unfamiliar exception code, pull the actual message text — the human-readable string is the fastest path to an error-enum name and the source of the bug:

```sql
SELECT
    exception_code,
    substring(exception, 1, 200) AS exception_msg,
    count() AS cnt
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 24 HOUR
    AND type IN ('ExceptionWhileProcessing', 'ExceptionBeforeStart')
    AND exception_code = <code>
    AND is_initial_query
GROUP BY exception_code, exception_msg
ORDER BY cnt DESC
LIMIT 10
```

Interpretation guide:

- `QUERY_WAS_CANCELLED` (394) almost always dominates — users navigating away, dashboard remounts, request cancellation upstream. Loud but rarely a code bug.
- `TIMEOUT_EXCEEDED` (159) at exactly the configured timeout (e.g. 60s) is the real signal — that query is genuinely too slow.
- `TOO_MANY_SIMULTANEOUS_QUERIES` (202) is a capacity ceiling on a specific user/cluster (often the `default` user on the OFFLINE cluster). The host names in the message tell you which shards.
- `NO_COMMON_TYPE` (386) / type errors are _real_ product bugs in the query builder — small counts but they break the user's view every time.
- `MEMORY_LIMIT_EXCEEDED` (241) on a `stats_table` query is usually a runaway breakdown on high-cardinality fields; sample the `query_id` to grab the full query.

## Reporting the result

Keep the writeup concrete and small:

- one table of (tag, count, avg, p95, p99) over a fixed window
- one timeline if you're verifying a rollout
- call out which tag has the worst tail explicitly — that's the actionable signal the per-strategy split was meant to expose
- note any tag that's missing from the data (e.g. preaggregated paths that never fire because the modifier is off) — that's also a finding

Include `query_id` examples for anything weird so reviewers can pull the full row from `system.query_log`.

## Known gotchas

- `is_initial_query` is required — without it you'll double-count subqueries.
- `type = 'QueryFinish'` keeps you on what actually executed; `QueryStart` and `ExceptionBeforeStart` rows are noise for latency.
- The `breakdown_by` top-level tag is recent. Historical data only has it nested under `log_comment.query.breakdownBy`.
- Cache warmer queries (`feature='cache_warmup'` or `trigger='webAnalyticsQueryWarming'`) inflate counts on whatever tag they target — filter them out if you're measuring user-facing latency.
- Personal-API-key traffic (`access_method='personal_api_key'`) is real but behaves differently from UI traffic; segment separately if you're sizing dashboards.
- Lazy precompute `*_lazy_insert` rows do _not_ serve a user request directly — they populate the cache as a side effect of a read miss. Filter them out when sizing user-facing latency; include them when sizing INSERT cost.
