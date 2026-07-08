# HogQL recipes over the GitHub warehouse tables

These base subqueries mirror the product's curated builders
(`products/engineering_analytics/backend/logic/views/`), so an insight built on them matches what the dashboard and MCP tools report.
Replace `github_pull_requests` / `github_workflow_runs` with the team's real table names from `engineering-analytics-sources` (`prefix` + `github_<endpoint>`).

## The PR base

```sql
SELECT
    number,
    title,
    author_handle,
    (author_handle LIKE '%[bot]'
        OR author_handle IN ('dependabot', 'github-actions', 'posthog-bot', 'renovate')) AS is_bot,
    arrayElement(repo_parts, 1) AS repo_owner,
    arrayElement(repo_parts, 2) AS repo_name,
    if(merged_at IS NOT NULL, 'merged', raw_state) AS state,
    is_draft,
    created_at,
    merged_at,
    closed_at,
    head_sha,
    if(merged_at IS NOT NULL, dateDiff('second', created_at, merged_at), NULL) AS open_to_merge_seconds
FROM (
    SELECT
        number,
        title,
        state AS raw_state,
        coalesce(draft, false) AS is_draft,
        ifNull(JSONExtractString(user, 'login'), '') AS author_handle,
        splitByChar('/', ifNull(JSONExtractString(base, 'repo', 'full_name'), '')) AS repo_parts,
        JSONExtractString(head, 'sha') AS head_sha,
        parseDateTimeBestEffort(created_at) AS created_at,
        parseDateTimeBestEffort(merged_at) AS merged_at,
        parseDateTimeBestEffort(closed_at) AS closed_at
    FROM github_pull_requests
)
```

The two-layer shape is required: the inner `SELECT` parses string timestamps and `ifNull`-unwraps Nullable JSON;
the outer derives state, repo identity, and durations.
Collapsing the layers hits ClickHouse's Array-inside-Nullable rejection and same-`SELECT` alias limits.

## The workflow-runs base

```sql
SELECT
    workflow_name,
    head_sha,
    head_branch,
    status,
    conclusion,
    run_started_at,
    run_attempt,
    pr_number,
    if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
    arrayElement(repo_parts, 1) AS repo_owner,
    arrayElement(repo_parts, 2) AS repo_name
FROM (
    SELECT
        name AS workflow_name,
        head_sha,
        head_branch,
        status,
        conclusion,
        run_attempt,
        JSONExtractInt(arrayElement(JSONExtractArrayRaw(ifNull(pull_requests, '[]')), 1), 'number') AS pr_number,
        splitByChar('/', ifNull(JSONExtractString(repository, 'full_name'), '')) AS repo_parts,
        parseDateTimeBestEffort(run_started_at) AS run_started_at,
        parseDateTimeBestEffort(updated_at) AS updated_at
    FROM github_workflow_runs
)
```

`pr_number` is the first entry of the run's `pull_requests` association — `0` when there is none (fork PRs, pushes with no open PR); filter `pr_number > 0` before attributing runs to PRs.
This association, not `head_sha`, is how the product links CI to a PR across all its pushes.

## Recipe: weekly open→merge time trend

```sql
WITH prs AS (<PR base>)
SELECT
    toStartOfWeek(merged_at) AS week,
    median(open_to_merge_seconds) / 3600 AS p50_hours,
    quantile(0.95)(open_to_merge_seconds) / 3600 AS p95_hours,
    count() AS merged_prs
FROM prs
WHERE merged_at >= now() - INTERVAL 90 DAY
  AND NOT is_bot
  AND NOT is_draft
GROUP BY week
ORDER BY week
```

Report p50 and p95 side by side — they move independently. This is "open to merge", not cycle time.

## Recipe: weekly CI success rate and p95 duration per workflow

```sql
WITH runs AS (<workflow-runs base>)
SELECT
    toStartOfWeek(run_started_at) AS week,
    workflow_name,
    count() AS runs,
    countIf(conclusion = 'success') / count() AS success_rate,
    quantile(0.95)(duration_seconds) AS p95_seconds
FROM runs
WHERE status = 'completed'
  AND run_started_at >= now() - INTERVAL 60 DAY
GROUP BY week, workflow_name
HAVING runs >= 5
ORDER BY week, runs DESC
```

Completed runs only — in-flight and stale-conclusion rows would poison the rate.
For a single-workflow tile, add `AND workflow_name = 'CI'` and drop the group.

## Recipe: PR throughput per week

```sql
WITH prs AS (<PR base>)
SELECT
    toStartOfWeek(created_at) AS week,
    countIf(state = 'merged') AS merged,
    countIf(state = 'closed') AS closed_unmerged
FROM prs
WHERE created_at >= now() - INTERVAL 90 DAY
  AND NOT is_bot
  AND NOT is_draft
GROUP BY week
ORDER BY week
```

## Recipe: open PRs with failing CI right now

A PR's current CI status is the latest completed run per `(head_sha, workflow_name)` — the one place head SHA is the correct key:

```sql
WITH prs AS (<PR base>),
runs AS (<workflow-runs base>),
ci AS (
    SELECT
        head_sha,
        countIf(s = 'completed' AND c IN ('failure', 'timed_out')) AS failing
    FROM (
        SELECT head_sha, workflow_name,
            argMax(status, run_started_at) AS s,
            argMax(conclusion, run_started_at) AS c
        FROM runs
        GROUP BY head_sha, workflow_name
    )
    GROUP BY head_sha
)
SELECT count() AS open_prs_failing_ci
FROM prs
INNER JOIN ci ON prs.head_sha = ci.head_sha
WHERE prs.state = 'open' AND NOT prs.is_draft AND ci.failing > 0
```

A `pending`-heavy result can be sync staleness, not real in-flight CI — treat pending as unsettled, never as failure.

## Job-level recipes (optional table)

`<prefix>github_workflow_jobs` may not be synced — check `engineering-analytics-sources` output or probe with a `LIMIT 1`.
Durations and queue times are honest SQL (`started_at - created_at` is queue wait, `completed_at - started_at` is run time; all string timestamps, parse them).
**Do not** recompute dollar cost from labels — the runner-tier price ladder lives in product code and drifts; use the `engineering-analytics-pr-cost` / `engineering-analytics-workflow-runner-costs` MCP tools for cost figures.
