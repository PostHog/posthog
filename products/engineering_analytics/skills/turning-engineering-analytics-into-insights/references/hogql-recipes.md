# HogQL recipes over the GitHub warehouse tables

These base subqueries follow the product's own query builders, so an insight built on them matches the product's numbers.
Replace every `github_*` table name with the real table name from `engineering-analytics-sources`.
The `engineering_analytics_*` views have fixed names and need no replacement.

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
        ifNull(JSONExtractString(head, 'ref'), '') AS head_branch,
        parseDateTimeBestEffort(created_at) AS created_at,
        parseDateTimeBestEffort(merged_at) AS merged_at,
        parseDateTimeBestEffort(closed_at) AS closed_at
    FROM github_pull_requests
)
WHERE NOT (startsWith(head_branch, 'trunk-merge/') OR startsWith(head_branch, 'gh-readonly-queue/'))
```

Keep the two layers.
The inner `SELECT` parses the string timestamps and unwraps the Nullable JSON.
The outer `SELECT` derives state, repo, and duration from those columns.

The `WHERE` drops the temporary PRs a merge queue opens for its gate branches.
The product also checks that the queue's bot opened the PR, so this filter is slightly wider.

## The workflow runs base

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
    (startsWith(head_branch, 'trunk-merge/') OR startsWith(head_branch, 'gh-readonly-queue/')) AS is_merge_queue,
    if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
    arrayElement(repo_parts, 1) AS repo_owner,
    arrayElement(repo_parts, 2) AS repo_name
FROM (
    SELECT
        name AS workflow_name,
        head_sha,
        ifNull(head_branch, '') AS head_branch,
        status,
        conclusion,
        run_attempt,
        JSONExtractInt(
            arrayFirst(
                p -> JSONExtractInt(p, 'base', 'repo', 'id') > 0
                    AND JSONExtractInt(p, 'base', 'repo', 'id') = ifNull(JSONExtractInt(repository, 'id'), 0),
                JSONExtractArrayRaw(ifNull(pull_requests, '[]'))
            ),
            'number'
        ) AS pr_number,
        splitByChar('/', ifNull(JSONExtractString(repository, 'full_name'), '')) AS repo_parts,
        parseDateTimeBestEffort(run_started_at) AS run_started_at,
        parseDateTimeBestEffort(updated_at) AS updated_at
    FROM github_workflow_runs
)
```

`pr_number` is the first PR in the run's association whose base repo is the run's own repo.
It is `0` when there is none, as for fork PRs and default-branch pushes.
Filter `pr_number > 0` before you attribute runs to PRs.

On a merge-queue gate run, the association names the queue's temporary PR.
Filter `NOT is_merge_queue` for per-PR metrics.
For a run's real PR on gate runs and default-branch pushes, use `pr_number` and `commit_pr_number` from `engineering_analytics_ci_job_history`.

This table holds GitHub Actions runs only.

## Weekly open to merge time

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

Show p50 and p95 together.
Title it "open to merge", not "cycle time".

## Weekly CI success rate and p95 duration per workflow

```sql
WITH runs AS (<workflow runs base>)
SELECT
    toStartOfWeek(run_started_at) AS week,
    workflow_name,
    count() AS runs,
    countIf(conclusion = 'success')
        / nullIf(countIf(conclusion IN ('success', 'failure', 'timed_out', 'startup_failure', 'stale')), 0)
            AS success_rate,
    quantileIf(0.95)(duration_seconds, conclusion = 'success') AS p95_seconds
FROM runs
WHERE status = 'completed'
  AND run_started_at >= now() - INTERVAL 60 DAY
GROUP BY week, workflow_name
HAVING runs >= 5
ORDER BY week, runs DESC
```

The rate counts `failure`, `timed_out`, `startup_failure`, and `stale` as failures.
It excludes skipped, cancelled, neutral, and action-required runs, because none of them reached a verdict.
The percentile uses successful runs, because failed and cancelled runs end early.

## PR throughput per week

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

## Open PRs with failing CI now

A PR's current CI status is the latest run per `(head_sha, workflow_name)`.
This is the one place where the head SHA is the correct key.

```sql
WITH prs AS (<PR base>),
runs AS (<workflow runs base>),
ci AS (
    SELECT
        head_sha,
        countIf(s = 'completed' AND c IN ('failure', 'timed_out', 'startup_failure', 'stale')) AS failing
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

The product's failing-CI count includes drafts and bots, and so does this query.
If the user wants drafts excluded, add `AND NOT prs.is_draft` and say the number then differs from the product.

## Job durations and queue times

In `<prefix>github_workflow_jobs`, `started_at` minus `created_at` is the queue wait.
`completed_at` minus `started_at` is the run time.
All three are strings, so parse them first.
For dollar cost, use the view below.

## Weekly CI cost by workflow

```sql
SELECT
    toStartOfWeek(created_at) AS week,
    workflow_name,
    round(sum(estimated_cost_usd), 2) AS estimated_cost_usd
FROM engineering_analytics_job_costs
WHERE created_at >= now() - INTERVAL 60 DAY
  AND created_at_raw >= toString(toDate(now() - INTERVAL 61 DAY))
GROUP BY week, workflow_name
ORDER BY week, estimated_cost_usd DESC
```

- The view has one row per job attempt, so `sum` is correct across retries.
- `estimated_cost_usd` is null for a job that is not billable, has not finished, or is a re-listed copy of an earlier attempt. `sum` skips nulls.
- Read `provider`, `completed_at`, and `is_rerun_copy` to tell those three cases apart.
- The `created_at_raw` floor lets the scan skip old data. Keep the precise `created_at` bound next to it.
- Add `AND pr_number = <n>` for one PR's cost.
- `is_merge_queue` separates merge-queue spend.
- With several connected repos, filter `repo_owner` and `repo_name`.

## Weekly time to first review

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

Title it "open to first review", because the figure includes draft time.
The reviews table holds submitted reviews only.
The reviewer's handle is `ifNull(JSONExtractString(user, 'login'), '')`, which lets you exclude self-reviews.
Never build a ranking of reviewers.

## A team's weekly merge time

`<prefix>github_team_members` maps GitHub logins to org teams.
Every column is Nullable.
Filter PR authors with `IN`, because a plain join double-counts authors who belong to several teams.

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

Return team aggregates only.
Do not return per-member figures or rank teams against each other.

## Distinct CI failures per day

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

The view reads the Logs product, whose retention is short.
Use it for a recent window, not for a long trend.
It holds pytest failures only and no passing runs, so chart counts and never rates.
To trace one failure to a culprit commit, use the `investigating-ci-failures` skill.
