# HogQL recipes over the GitHub warehouse tables

These base subqueries mirror the product's curated builders
(`products/engineering_analytics/backend/logic/views/`), so an insight built on them matches what the dashboard and MCP tools report.
Replace `github_pull_requests` / `github_workflow_runs` / `github_reviews` with the team's real table names from `engineering-analytics-sources` (`prefix` + `github_<endpoint>`).
The `engineering_analytics_*` views used below have fixed names — no prefix, no discovery.

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

`pr_number` is the first entry of the run's `pull_requests` association, or `0` when there is none (fork PRs, pushes with no open PR); filter `pr_number > 0` before attributing runs to PRs.
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

Report p50 and p95 side by side; they move independently. This is "open to merge", not cycle time.

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

Completed runs only: in-flight and stale-conclusion rows would poison the rate.
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

A PR's current CI status is the latest completed run per `(head_sha, workflow_name)`; this is the one place head SHA is the correct key:

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
WHERE prs.state = 'open' AND ci.failing > 0
```

Drafts and bots stay included here, matching the product's failing-CI card (`ci_cards` only excludes them from the stuck count); add `AND NOT prs.is_draft` only if the user explicitly wants non-draft PRs, and say the number then diverges from the dashboard.
A `pending`-heavy result can be sync staleness, not real in-flight CI; treat pending as unsettled, never as failure.

## Job-level recipes

Durations and queue times are honest SQL over `<prefix>github_workflow_jobs` (`started_at - created_at` is queue wait, `completed_at - started_at` is run time; all string timestamps, parse them).
**Do not** recompute dollar cost from labels: the runner-tier price ladder lives in product code and drifts; query the `engineering_analytics_job_costs` view instead (below), which renders that model into SQL and is parity-tested against it.

## Recipe: weekly CI cost by workflow (job_costs view)

```sql
SELECT
    toStartOfWeek(created_at) AS week,
    workflow_name,
    round(sum(estimated_cost_usd), 2) AS estimated_cost_usd
FROM engineering_analytics_job_costs
WHERE created_at >= now() - INTERVAL 60 DAY
GROUP BY week, workflow_name
ORDER BY week, estimated_cost_usd DESC
```

Grain is one row per job attempt, so `sum` is correct across retries.
`estimated_cost_usd` is NULL (skipped by `sum`) for non-billable jobs (github-hosted, non-Linux, unclassifiable labels) and for jobs still running; disambiguate a NULL via `provider` (non-billable) vs `completed_at` (unsettled).
Add `WHERE pr_number = <n>` for one PR's cost — it matches `engineering-analytics-pr-cost`, since the tool reads the same rendered cost SELECT.
With several connected sources, filter `repo_owner` / `repo_name`.

## Review recipes

In `<prefix>github_reviews`, pending drafts are dropped at sync; `state` is `APPROVED` / `CHANGES_REQUESTED` / `COMMENTED` / `DISMISSED`, and the injected `pr_number` joins to the PR base's `number`.

Weekly time to first review:

```sql
WITH prs AS (<PR base>),
first_review AS (
    SELECT pr_number, min(parseDateTimeBestEffort(submitted_at)) AS first_review_at
    FROM github_reviews
    GROUP BY pr_number
)
SELECT
    toStartOfWeek(prs.created_at) AS week,
    median(dateDiff('second', prs.created_at, fr.first_review_at)) / 3600 AS p50_hours,
    quantile(0.95)(dateDiff('second', prs.created_at, fr.first_review_at)) / 3600 AS p95_hours,
    count() AS reviewed_prs
FROM prs
INNER JOIN first_review fr ON prs.number = fr.pr_number
WHERE prs.created_at >= now() - INTERVAL 90 DAY
  AND NOT prs.is_bot
GROUP BY week
ORDER BY week
```

Name it "open to first review", not "time in review": there is no ready-for-review timestamp, so draft time is fused in, same caveat as `open_to_merge_seconds`.
The reviewer handle is `ifNull(JSONExtractString(user, 'login'), '')` when needed (e.g. to exclude self-reviews by comparing against `author_handle`) — but never build per-reviewer leaderboards.

## Recipe: a team's weekly merge time (team_members table)

`<prefix>github_team_members` maps PR authors to GitHub org teams (every column lands Nullable; drop empty logins — they would match deleted-account authors).
Attribute PRs to a team with a membership **semi-join**, the shape the product's own team merge trend uses — a plain JOIN would double-count authors who belong to several teams:

```sql
WITH prs AS (<PR base>),
members AS (
    SELECT ifNull(login, '') AS member_handle
    FROM github_team_members
    WHERE ifNull(team_slug, '') = 'my-team'
      AND ifNull(login, '') != ''
)
SELECT
    toStartOfWeek(merged_at) AS week,
    median(open_to_merge_seconds) / 3600 AS p50_hours,
    count() AS merged_prs
FROM prs
WHERE merged_at >= now() - INTERVAL 90 DAY
  AND NOT is_bot
  AND author_handle IN (SELECT member_handle FROM members)
GROUP BY week
ORDER BY week
```

Only team-level aggregates leave the query — no per-member figures, no cross-team rankings.
Note the namespace: these are GitHub org team slugs, while the `engineering-analytics-team-ci-health` tool groups by the repo's ownership map (`products/*/product.yaml` + CODEOWNERS); a team whose slugs differ across the two won't line up between such insights and that tool.

## Recipe: distinct CI failures per day (ci_failures view)

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    uniq(fingerprint) AS distinct_failures,
    count() AS failed_test_lines
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
```

The view reads the Logs product, so its reach is bounded by the short logs retention — fine for a recent-window tile, wrong for long trends.
Fingerprinting is pytest-only, and the data is failure-only (passing runs are absent), so report absolute counts, never rates.
To chase a specific failure to a culprit, hand off to the `investigating-ci-failures` skill, which works from this view plus `engineering_analytics_ci_job_history`.
When windowing `engineering_analytics_ci_job_history`, pair the precise `created_at >= …` filter with a coarse raw floor (`created_at_raw >= '<YYYY-MM-DD>'`, a day below the window) so the parquet scan can prune; a computed-column predicate alone forces a full scan.
