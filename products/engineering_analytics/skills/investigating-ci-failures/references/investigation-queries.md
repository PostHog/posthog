# Investigation queries

Copy-ready HogQL for each step of the investigation workflow. All of these run via `execute-sql`
(or `posthog:execute-sql` through MCP). The two views are non-materialized — results are always
current. Adjust windows to the question; 14 days covers almost every investigation.

## 1. Fingerprint a failure (the index query)

Start here whenever the input is a failing test name or an error string. Loose `ILIKE` beats an
exact match — test ids get truncated and re-sharded in reports.

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

Shape reading: `branches = 1` → that branch's own problem. `branches` high + `first_seen`/`last_seen`
tight + `master_hits > 0` → trunk break. `branches` high + window spanning days/weeks with gaps →
flaky.

## 2. Boundary query (trunk break → culprit + fix)

Master-only history for the failing job, around the failure window from query 1. The first
`failure` row after a `success` run is the culprit; the first `success` after the red streak is the
fix.

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
  AND job_name = '<failing job name>'          -- e.g. 'Product tests (data-warehouse (1/2))'
  AND created_at >= <first_seen - 2h> AND created_at < <last_seen + 2h>
  AND created_at_raw >= '<window start date minus 1 day, YYYY-MM-DD>'
ORDER BY created_at ASC
```

The `created_at_raw` floor lets the warehouse scan prune — the parsed `created_at` filter alone hits
a computed column and forces a full jobs scan. It's coarse (a whole-day, string floor a day below the
window), so keep the precise `created_at` bounds too; the raw floor only shrinks what the scan reads.

Shard suffixes matter: `job_name` includes the `(1/2)` shard. If the test moved shards, run once
per shard or match with `job_name LIKE 'Product tests (data-warehouse%'`.

## 3. Failure detail for one fingerprint

The actual error lines behind a fingerprint, newest first — for reading the traceback context and
confirming two occurrences really are the same failure.

```sql
SELECT timestamp, branch, substring(head_sha, 1, 11) AS sha, run_id, job_name, error_signature
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 14 DAY
  AND fingerprint = '<fingerprint from query 1>'
ORDER BY timestamp DESC
LIMIT 50
```

`run_id` links each row to `ci_job_history` (and to the GitHub UI:
`https://github.com/<owner>/<repo>/actions/runs/<run_id>`).

## 4. What's new on master (novelty scan)

Fingerprints first seen recently that have hit master — the "did anything just break" sweep.

```sql
SELECT fingerprint, min(timestamp) AS first_seen, count() AS occurrences, uniqExact(branch) AS branches
FROM engineering_analytics_ci_failures
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY fingerprint
HAVING min(timestamp) >= now() - INTERVAL 1 DAY AND countIf(branch = 'master') > 0
ORDER BY occurrences DESC
```

## 5. Warehouse freshness check

Run before trusting a boundary during a live incident — a stale warehouse names the wrong commit.
Logs stream near-real-time; the jobs table arrives via webhook sync.

```sql
SELECT max(created_at) AS newest_job_row, now() - max(created_at) AS lag
FROM engineering_analytics_ci_job_history
```

If `lag` exceeds ~15 minutes, do the classification from `ci_failures` now and defer the
culprit-naming boundary query until the warehouse catches up (or corroborate the boundary commit
against `git log` before naming it).

## 6. Deterministic or retry-passing?

Track the investigated fingerprint itself across retry attempts, not just the job's conclusion — a
different failure can keep the job red after this fingerprint cleared. Only runs where the
fingerprint ever appeared are considered.

```sql
SELECT
    h.run_id,
    h.run_attempt,
    h.conclusion AS job_conclusion,
    f.run_id != 0 AS fingerprint_present
FROM engineering_analytics_ci_job_history AS h
LEFT JOIN (
    SELECT DISTINCT run_id, run_attempt
    FROM engineering_analytics_ci_failures
    WHERE timestamp >= now() - INTERVAL 7 DAY AND fingerprint = '<fingerprint from query 1>'
) AS f ON h.run_id = f.run_id AND h.run_attempt = f.run_attempt
WHERE h.job_name = '<failing job name>'
  AND h.created_at >= now() - INTERVAL 7 DAY
  AND h.created_at_raw >= '<8 days ago, YYYY-MM-DD>'
  AND h.run_id IN (
    SELECT DISTINCT run_id FROM engineering_analytics_ci_failures
    WHERE timestamp >= now() - INTERVAL 7 DAY AND fingerprint = '<fingerprint from query 1>'
  )
ORDER BY h.run_id, h.run_attempt
```

Reading: `fingerprint_present` dropping on a later attempt while the job goes green = retry-passed
(flake signal). Fingerprint present through the last attempt = deterministic. Fingerprint absent but
the job still red = a different failure holds the job red — don't attribute it to this one.

The `created_at_raw` floor lets the warehouse scan prune — the parsed `created_at` filter alone hits
a computed column and forces a full jobs scan. It's coarse (a whole-day, string floor a day below the
7-day window), so keep the precise `created_at` bound too.
