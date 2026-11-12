# Investigation queries

Run these HogQL queries with the `execute-sql` tool.
Both views compute from current data on every query.
Adjust the windows to the question.
Replace `master` with the repo's default branch where it differs.

Every query on `engineering_analytics_ci_job_history` pairs the `created_at` bound with a `created_at_raw` string floor.
The floor is a date one day below the window, and it lets the scan skip old data.
The parsed `created_at` filter alone forces a full scan, so keep both.

## 1. Fingerprint a failure

Start here when you have a failing test name or an error string.
Use a loose `ILIKE`, because reports often truncate test ids.

```sql
SELECT
    fingerprint,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen,
    count() AS occurrences,
    uniqExact(branch) AS branches,
    countIf(branch = 'master') AS master_hits
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 14 DAY
  AND test_id ILIKE '%<part of the test name>%'   -- or: error_signature ILIKE '%<error text>%'
GROUP BY fingerprint
ORDER BY last_seen DESC
```

- `branches = 1` means that branch's own problem.
- Many branches, a tight window, and `master_hits > 0` mean a default-branch break.
- Many branches over days or weeks with gaps mean a flaky test.

## 2. Find the culprit and the fix

This query lists the failing job's default-branch history around the window from query 1.
The first `failure` after a `success` is the culprit.
The first `success` after the red streak is the fix.

```sql
SELECT
    substring(head_sha, 1, 11) AS sha,
    conclusion,
    created_at,
    run_attempt,
    commit_author_name,
    commit_pr_number,
    substring(commit_message, 1, 100) AS message
FROM engineering_analytics_ci_job_history
WHERE head_branch = 'master'
  AND job_name = '<failing job name>'
  AND created_at >= <first_seen - 2h> AND created_at < <last_seen + 2h>
  AND created_at_raw >= '<window start date minus 1 day, YYYY-MM-DD>'
ORDER BY created_at ASC
```

`job_name` includes the shard suffix, such as `(1/2)`.
If the test may have moved shards, match with `job_name LIKE '<job name prefix>%'`.

## 3. Read the lines behind one fingerprint

Use this to confirm that two occurrences are the same failure.

```sql
SELECT timestamp, branch, substring(head_sha, 1, 11) AS sha, ci_engine, run_id, job_name, error_signature
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 14 DAY
  AND fingerprint = '<fingerprint from query 1>'
ORDER BY timestamp DESC
LIMIT 50
```

Join runs on `(ci_engine, run_id)`.
Only `github_actions` ids link to `https://github.com/<owner>/<repo>/actions/runs/<run_id>`.
A row with a null engine has unknown provenance, so do not use it to prove a retry recovery.

## 4. Find new failures on master

This query returns fingerprints first seen in the last day that have hit master.

```sql
SELECT fingerprint, min(timestamp) AS first_seen, count() AS occurrences, uniqExact(branch) AS branches
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY fingerprint
HAVING min(timestamp) >= now() - INTERVAL 1 DAY AND countIf(branch = 'master') > 0
ORDER BY occurrences DESC
```

## 5. Check job history freshness

Run this before you trust a boundary during a live incident.
A stale job history names the wrong commit.

```sql
SELECT max(created_at) AS newest_job_row, now() - max(created_at) AS lag_seconds
FROM engineering_analytics_ci_job_history
WHERE created_at_raw >= '<7 days ago, YYYY-MM-DD>'
```

No rows means the job history is more than a week stale.
If the lag exceeds about 15 minutes, classify the failure from `engineering_analytics_ci_failures` now.
Name the culprit after the job history catches up, or confirm the boundary commit against `git log` first.

## 6. Tell a deterministic failure from a retry pass

Track the fingerprint across retry attempts, not only the job's conclusion.
A different failure can keep the job red after this fingerprint cleared.
The query covers only runs where the fingerprint appeared.

```sql
SELECT
    h.ci_engine,
    h.run_id,
    h.run_attempt,
    h.conclusion AS job_conclusion,
    f.run_id != 0 AS fingerprint_present
FROM engineering_analytics_ci_job_history AS h
LEFT JOIN (
    SELECT DISTINCT ci_engine, run_id, run_attempt
    FROM engineering_analytics_ci_failures
    WHERE timestamp >= now() - INTERVAL 7 DAY AND fingerprint = '<fingerprint from query 1>'
) AS f ON h.ci_engine = f.ci_engine AND h.run_id = f.run_id AND h.run_attempt = f.run_attempt
WHERE h.job_name = '<failing job name>'
  AND h.created_at >= now() - INTERVAL 7 DAY
  AND h.created_at_raw >= '<8 days ago, YYYY-MM-DD>'
  AND (h.ci_engine, h.run_id) IN (
    SELECT DISTINCT ci_engine, run_id FROM engineering_analytics_ci_failures
    WHERE timestamp >= now() - INTERVAL 7 DAY AND fingerprint = '<fingerprint from query 1>'
  )
ORDER BY h.ci_engine, h.run_id, h.run_attempt
```

- The fingerprint disappears on a later attempt and the job goes green: a retry passed, which suggests a flake.
- The fingerprint is present through the last attempt: the failure is deterministic.
- The fingerprint is absent but the job is still red: a different failure holds the job red.

## 7. Job failure rate, for failures with no test rows

A job that failed before its tests ran writes no `FAILED` line.
Job conclusions are the only place it appears.
They also record passing jobs, so this is the one true rate in this skill.

```sql
SELECT
    countIf(conclusion = 'success') AS ok,
    countIf(conclusion IN ('failure', 'timed_out', 'startup_failure', 'stale')) AS fail,
    round(100.0 * fail / nullIf(ok + fail, 0), 2) AS fail_pct
FROM engineering_analytics_ci_job_history
WHERE repo_name = '<repo>'
  AND workflow_name = '<failing workflow name>'
  AND job_name = '<failing job name>'
  AND NOT is_rerun_copy
  AND created_at >= now() - INTERVAL 7 DAY
  AND created_at_raw >= '<8 days ago, YYYY-MM-DD>'
```

- Filter by repo and workflow as well as job. The view covers every connected repo, and job names repeat across workflows.
- `NOT is_rerun_copy` drops the rows GitHub lists again for jobs a partial re-run did not execute.
- The rate leaves out `cancelled`, `skipped`, `neutral`, and `action_required`, because none of them reached a verdict.

A percentage cannot tell an old flake from a live outage, so break the same job down by hour:

```sql
SELECT
    toStartOfHour(created_at) AS hour,
    countIf(conclusion = 'success') AS ok,
    countIf(conclusion IN ('failure', 'timed_out', 'startup_failure', 'stale')) AS fail
FROM engineering_analytics_ci_job_history
WHERE repo_name = '<repo>'
  AND workflow_name = '<failing workflow name>'
  AND job_name = '<failing job name>'
  AND NOT is_rerun_copy
  AND created_at >= now() - INTERVAL 12 HOUR
  AND created_at_raw >= '<yesterday, YYYY-MM-DD>'
GROUP BY hour
ORDER BY hour DESC
```

- A low rate with recent hours mostly green is transient. Recommend a retry.
- Recent hours that are all red are an outage. Stop recommending retries.
- A steady rate across days is a standing defect.

## 8. What the merge queue ran for a PR

The gate branch is temporary, but its jobs stay in the job history under that `head_branch`.

```sql
SELECT head_branch, head_sha, ci_engine, run_id, workflow_name, job_name, conclusion, created_at
FROM engineering_analytics_ci_job_history
WHERE startsWith(head_branch, 'trunk-merge/pr-<n>/')
  AND created_at >= now() - INTERVAL 7 DAY
  AND created_at_raw >= '<8 days ago, YYYY-MM-DD>'
ORDER BY conclusion IN ('failure', 'timed_out', 'startup_failure', 'stale') DESC, created_at DESC
```

Each distinct `head_branch` is one queue attempt.
Use the failing `job_name` in query 7.
GitHub's native queue names its branches `gh-readonly-queue/<base>/pr-<n>-<sha>`.
To list the PRs a Trunk gate branch carried, run `gh api repos/<owner>/<repo>/compare/master...<head_sha>` and read the merge commit titles.
