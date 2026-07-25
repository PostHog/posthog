# Tasks query cookbook

All queries run via `execute-sql` over the `system.tasks` and `system.task_runs` Postgres system tables.
Conventions used throughout:

- **Always exclude the scout fleet's own rows**: `t.origin_product != 'signals_scout'`.
  Those are the harness's run containers, not project work — no repository, one creator, and on an active project they can outnumber every real origin combined.
  The `internal` flag does **not** exclude them.
- **Join on `r.task_id = t.id`.**
  `system.tasks` is already filtered to non-internal rows; add `t.deleted = 0` when you're counting tasks rather than runs.
- **Two different time anchors.**
  `t.created_at` is when someone asked; `r.created_at` is when a run executed.
  A task created months ago can run today, so an origin mix computed on task creation will not match one computed on run time.
  Pick the anchor that matches the question — lens A anchors on `r.created_at`, lens B on `t.created_at`.
- **`stage` is unpopulated.**
  Verified null across every run.
  Never group or filter on it.
- **`error_message` presence is not failure.**
  Far more runs carry a message than are in `failed` status.
  Always pair it with `status = 'failed'` when measuring failures.
- **Status values are lowercase**: `completed`, `failed`, `cancelled`, `queued`, `in_progress`.
- **`created_by_id` is an internal integer.**
  Good for counting distinct people; it does **not** resolve to a reviewer.
  Use `tasks-retrieve` on one task id in the cluster and read `created_by.uuid`.

## 0 — Orientation: origin mix and field coverage

Run once per run before anything else.
Tells you which origins this project actually uses (never assume the full enum is present) and whether the fields your lenses need are populated here.

```sql
SELECT
    t.origin_product                                             AS origin,
    count()                                                      AS runs,
    uniq(r.task_id)                                              AS tasks,
    uniq(t.created_by_id)                                        AS creators,
    uniq(t.repository)                                           AS repos,
    countIf(r.status = 'failed')                                 AS failed,
    countIf(isNotNull(r.error_message))                          AS with_error_msg,
    countIf(isNotNull(r.branch))                                 AS with_branch
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
GROUP BY origin
ORDER BY runs DESC
```

## 1 — Run health by origin (lens A detect)

The project-wide baseline.
Record the result in `pattern:tasks:baseline` so later runs compare against it instead of re-deriving it.

```sql
SELECT
    t.origin_product                                             AS origin,
    count()                                                      AS runs,
    countIf(r.status = 'failed')                                 AS failed,
    round(100.0 * countIf(r.status = 'failed') / count(), 1)     AS fail_pct,
    round(100.0 * countIf(r.status = 'cancelled') / count(), 1)  AS cancel_pct,
    countIf(r.status IN ('queued', 'in_progress'))               AS in_flight,
    uniq(t.created_by_id)                                        AS users
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
GROUP BY origin
ORDER BY runs DESC
```

## 2 — Failure concentration by repository (lens A detect)

The primary report grain for lens A.
`failed_runs_per_task` is the systemic-vs-retry-storm ratio: ≈ 1 across many failing tasks is systemic, ≫ 1 over few is a retry storm.
A repo at `fail_pct = 100` is a readiness break worth filing at any volume.

**The ratio must be computed over failed runs only.** Dividing total runs by total tasks folds successful re-runs into the numerator, so a repo whose tasks are routinely re-run on success reads as a retry storm even when its failures are spread 1:1 across many distinct tasks — exactly inverting the discriminator on the systemic case it exists to catch. `uniqIf` scopes the denominator to the tasks that actually failed; `nullIf` keeps a repo with zero failures from dividing by zero. Query 3 gets this for free from its `status = 'failed'` WHERE clause, so its plain `count() / uniq(task_id)` is already failure-scoped — don't "fix" it to match this one.

```sql
SELECT
    t.repository                                                 AS repo,
    count()                                                      AS runs,
    uniq(r.task_id)                                              AS tasks,
    countIf(r.status = 'failed')                                 AS failed,
    uniqIf(r.task_id, r.status = 'failed')                       AS failed_tasks,
    round(countIf(r.status = 'failed')
          / nullIf(uniqIf(r.task_id, r.status = 'failed'), 0), 1) AS failed_runs_per_task,
    round(100.0 * countIf(r.status = 'failed') / count(), 1)     AS fail_pct,
    uniq(t.created_by_id)                                        AS users
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
GROUP BY repo
HAVING runs > 20
ORDER BY failed DESC
LIMIT 25
```

## 3 — Error class clustering (lens A localize)

The localization lens.
Grouping on a message prefix collapses the variable tail (ids, paths, timings) and leaves the class.
60 characters is a good default: long enough to separate classes, short enough that per-task detail doesn't fragment them.
Widen to 100 if two distinct classes collapse together.

`failed_runs_per_task` here is the same discriminator applied per class.
The `status = 'failed'` filter below already scopes every row to a failure, so the plain `count() / uniq(task_id)` is failure-scoped as written — no `uniqIf` needed, unlike query 2.

```sql
SELECT
    substring(r.error_message, 1, 60)                            AS err_prefix,
    count()                                                      AS runs,
    uniq(r.task_id)                                              AS tasks,
    round(count() / uniq(r.task_id), 1)                          AS failed_runs_per_task,
    uniq(t.repository)                                           AS repos,
    uniq(t.created_by_id)                                        AS users
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
  AND r.status = 'failed'
  AND isNotNull(r.error_message)
GROUP BY err_prefix
ORDER BY runs DESC
LIMIT 20
```

Classes seen in the wild, as a rough taxonomy to orient against — expect a project's own mix to differ, and let the data name the classes rather than matching these:

| Shape                                                  | Usually points at                                         |
| ------------------------------------------------------ | --------------------------------------------------------- |
| Agent returned no parseable structured output          | the agent's output contract — often broad and systemic    |
| Repository clone or authentication failure             | repo readiness / credentials — often a whole repo at 100% |
| Sandbox start, request timeout, or connection failure  | infrastructure — check whether it's one task looping      |
| Schema or field-validation error on a produced payload | a contract mismatch between producer and consumer         |
| Poll or activity timeout after a fixed duration        | long-running work hitting a ceiling                       |
| Upstream model provider error                          | third-party; usually a disqualifier                       |

## 4 — Cross: repository × error class (lens A group)

Once queries 2 and 3 name a candidate, this confirms whether the class is repo-specific (a config problem on that repo) or spread across repos (systemic).
Substitute the prefix you're chasing.

```sql
SELECT
    t.repository                                                 AS repo,
    substring(r.error_message, 1, 60)                            AS err_prefix,
    count()                                                      AS runs,
    uniq(r.task_id)                                              AS tasks
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
  AND r.status = 'failed'
  AND isNotNull(r.error_message)
GROUP BY repo, err_prefix
HAVING runs > 3
ORDER BY runs DESC
LIMIT 30
```

## 5 — Silent non-completion (lens A)

Cancellation rate and aging in-flight backlog.
A cancellation rate well above the baseline in query 1 is a prompt to look at what those tasks shared, not a finding on its own.

```sql
SELECT
    t.repository                                                 AS repo,
    count()                                                      AS runs,
    countIf(r.status = 'cancelled')                              AS cancelled,
    round(100.0 * countIf(r.status = 'cancelled') / count(), 1)  AS cancel_pct,
    countIf(r.status IN ('queued', 'in_progress'))               AS in_flight,
    countIf(r.status IN ('queued', 'in_progress')
            AND r.created_at < now() - interval 1 day)           AS stale_in_flight
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
GROUP BY repo
HAVING runs > 20
ORDER BY cancelled DESC
LIMIT 20
```

## 6 — Human-origin demand volume (lens B, gated)

Lens B only.
The origin filter here is the whole point — machine origins are excluded so the inbox's own throughput can't register as user demand.

```sql
SELECT
    origin_product                                               AS origin,
    repository                                                   AS repo,
    count()                                                      AS tasks,
    uniq(created_by_id)                                          AS requesters,
    round(avg(length(description)))                              AS avg_desc_len
FROM system.tasks
WHERE created_at > now() - interval 30 day
  AND deleted = 0
  AND origin_product IN ('user_created', 'slack', 'posthog_ai', 'hogdesk', 'onboarding')
GROUP BY origin, repo
ORDER BY tasks DESC
LIMIT 30
```

## 7 — Demand theme sampling (lens B, gated)

Titles only, and windowed.
Descriptions on real projects average thousands of characters — pulling them in bulk will exhaust the run's budget.
Read titles at scale here, then `tasks-retrieve` a handful of representative ids for full context on a theme worth pursuing.

Titles are also the safer read: they're shorter and far less likely to carry the credentials and customer detail that descriptions routinely do.

```sql
SELECT
    id                                                           AS task_id,
    substring(title, 1, 120)                                     AS title,
    origin_product                                               AS origin,
    repository                                                   AS repo,
    created_by_id                                                AS creator,
    created_at
FROM system.tasks
WHERE created_at > now() - interval 30 day
  AND deleted = 0
  AND origin_product IN ('user_created', 'slack', 'posthog_ai', 'hogdesk', 'onboarding')
  AND length(title) > 10
ORDER BY created_at DESC
LIMIT 200
```

Cluster the titles yourself, then verify each candidate theme against the two tests in the body: repeated across **distinct** `creator` values, and not already served by the project's product.
A theme that only survives on one creator's tasks is that person's workflow, not demand.

## 8 — Lens intersection (the highest-value shape)

Tasks whose runs failed, restricted to human origins — where a delivery-health cluster and a demand theme overlap.
A capability people keep asking for that also keeps failing is the most actionable thing this scout can surface.

```sql
SELECT
    substring(t.title, 1, 120)                                   AS title,
    t.id                                                         AS task_id,
    t.repository                                                 AS repo,
    t.created_by_id                                              AS creator,
    substring(r.error_message, 1, 60)                            AS err_prefix,
    count()                                                      AS failed_runs
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 30 day
  AND r.status = 'failed'
  AND t.origin_product IN ('user_created', 'slack', 'posthog_ai', 'hogdesk', 'onboarding')
GROUP BY title, task_id, repo, creator, err_prefix
ORDER BY failed_runs DESC
LIMIT 30
```
