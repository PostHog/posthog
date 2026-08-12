# Tasks query cookbook

All queries run via `execute-sql` over the `system.tasks` and `system.task_runs` Postgres system tables.
Conventions used throughout:

- **Always exclude the scout fleet's own rows**: `t.origin_product != 'signals_scout'`.
  Those are the harness's run containers, not project work — no repository, one creator, and on an active project they can outnumber every real origin combined.
  The `internal` flag does **not** exclude them.
- **Join on `r.task_id = t.id`.**
  Add `t.deleted = 0` when you're counting tasks rather than runs.
- **Internal tasks are invisible here, and that bounds the lens.**
  `system.tasks` carries a hard `internal != true` predicate. Loop firings (`origin_product = 'loop'`, created `internal=True`) and parts of the signals pipeline never appear, so this cookbook measures the _non-internal_ slice only. Don't describe a finding as fleet-wide delivery health — it is delivery health for the work this table can see.
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
- **Status values are lowercase**: `not_started`, `queued`, `in_progress`, `completed`, `failed`, `cancelled`.
  `not_started` is the model default, so a run that never advances past creation sits there — the non-terminal set is all three of `not_started` / `queued` / `in_progress`, never just the latter two.
- **Never substitute task-derived text into SQL — use the numeric fingerprints.**
  Both `error_message` and `repository` are attacker-influenceable: error text is arbitrary tool output, and `validate_repository` only requires two non-empty slash-separated parts, so a quote survives it. Queries 2 and 3 emit `repo_fingerprint` / `err_fingerprint` (`cityHash64(...)`) precisely so downstream predicates carry an integer instead. Escaping by hand mid-run is not a control — if you find yourself pasting a quoted string into a predicate, derive a fingerprint instead.
- **`created_by_id` is an internal integer.**
  Good for counting distinct people; it does **not** resolve to a reviewer.
  Use `tasks-retrieve` on one task id in the cluster and read `created_by.uuid`.

## 0 — Orientation: origin mix and field coverage

**Confirm the schema first.** The `execute-sql` contract requires querying `system.information_schema.columns` for every `system.*` table before projecting its columns, and column sets do drift:

```sql
SELECT table_name, column_name, data_type
FROM system.information_schema.columns
WHERE table_name IN ('system.tasks', 'system.task_runs')
ORDER BY table_name, column_name
```

Then run the orientation query below using only confirmed columns.
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
    countIf(r.status IN ('not_started', 'queued', 'in_progress')) AS in_flight,
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
    cityHash64(t.repository)                                     AS repo_fingerprint,
    t.repository                                                 AS repo,
    count()                                                      AS runs,
    uniq(r.task_id)                                              AS tasks,
    countIf(r.status = 'failed')                                 AS failed,
    uniqIf(r.task_id, r.status = 'failed')                       AS failed_tasks,
    round(countIf(r.status = 'failed')
          / nullIf(uniqIf(r.task_id, r.status = 'failed'), 0), 1) AS failed_runs_per_task,
    round(100.0 * countIf(r.status = 'failed') / count(), 1)     AS fail_pct,
    -- Reach must be the creators who were *affected*. A plain uniq() mixes in everyone whose
    -- runs succeeded, dressing a one-person failure up as broad reach.
    uniqIf(t.created_by_id, r.status = 'failed')                 AS affected_users
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
  -- Repo-less tasks are unrelated work that would group into one synthetic "repository";
  -- that cluster can trip the total-failure exception with no shared repo behind it.
  -- Query 3 owns cross-task failure classes that have no repository.
  AND isNotNull(t.repository) AND t.repository != ''
GROUP BY repo_fingerprint, repo
-- The floor applies to *partial* failure rates. A repo where every run fails is a
-- readiness break the body says to file at any volume, so it must survive the floor —
-- but only with independent spread. `failed_tasks >= 2` is what stops one person
-- retrying a single task against a fresh repo from minting a team-visible report.
HAVING runs > 20 OR (failed = runs AND runs >= 3 AND failed_tasks >= 2)
-- Order by the discriminator, not raw count. `HAVING` is the volume guard, so everything
-- here already clears the floor; ranking by count would let a high-traffic repo with a
-- healthy 1% rate push a small repo at 100% past the LIMIT — the exact inversion the body
-- calls noise. Rate first, count only as tie-breaker.
ORDER BY fail_pct DESC, failed DESC
LIMIT 25
```

## 3 — Error class clustering (lens A localize)

The localization lens.
Grouping on a message prefix collapses the variable tail (ids, paths, timings) and leaves the class.
60 characters is a good default: long enough to separate classes, short enough that per-task detail doesn't fragment them.

**The width is a constant shared by queries 3, 4 and 9.** If two distinct classes collapse and you widen it, widen it in _all three_ — `err_fingerprint` is a hash of the prefix, so a 100-character hash from query 3 matches nothing against a 60-character hash downstream, and the chain silently returns zero rows for exactly the collision the widening was meant to resolve.

`err_fingerprint` is what downstream queries filter on — carry the **number**, never the text (see query 4).

**Visibility: this reads error text from runs you may not be entitled to see.** `system.task_runs` enforces team scoping only, not `task_run_visibility_q`, so a private `#me` task's failure contributes its error text here just like any other — the same actor gets a 404 from `tasks-runs-retrieve` for that run. Two rules follow, and they are what keep this query inside the boundary:

1. **Never quote the raw prefix in a report.** Name the class ("clone authentication failure", "agent returned no parseable output") with counts. The aggregate is what the lens is for; the string is not.
2. **Any concrete run you cite must round-trip through `tasks-runs-retrieve` first** (query 9 gets you the ids). That call applies the visibility rule — a 404 means this run is not yours to surface, so drop it and cite a different one. Treat the retrieve as the authorization check, not a convenience.

`failed_runs_per_task` here is the same discriminator applied per class.
The `status = 'failed'` filter below already scopes every row to a failure, so the plain `count() / uniq(task_id)` is failure-scoped as written — no `uniqIf` needed, unlike query 2.

```sql
SELECT
    cityHash64(substring(r.error_message, 1, 60))                AS err_fingerprint,
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
  -- Project-wide by default. When query 2 named a candidate repository, re-run this
  -- scoped to it — a repo's own worst class is often outside the global top 20, and
  -- without this the query 2 -> query 3 -> query 4 chain stalls with nothing to localize:
  -- AND cityHash64(t.repository) = 0000000000000000000  -- repo_fingerprint from query 2
GROUP BY err_fingerprint, err_prefix
-- Rank by how many distinct tasks a class touches, not raw runs: one task retried 200 times
-- would otherwise fill the page and push out a class that hit 30 tasks once each — the
-- systemic shape this lens exists to find.
ORDER BY tasks DESC, runs DESC
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
**Filter by the `err_fingerprint` integer query 3 returned** — without a predicate this returns the global top 30 pairs and the class you are chasing may not be among them.

**Never interpolate the error text itself.** An error message is arbitrary tool output, not a trusted constant: an apostrophe breaks the literal, and a crafted message (`x' OR 1=1 --`) would rewrite the predicate and pull in unrelated runs. Escaping-by-hand is not a control you should rely on mid-run, so the cookbook removes the need for it — substitute the **numeric** fingerprint and no attacker-controlled string ever reaches the SQL. If you genuinely need to match text, derive a fresh fingerprint in the query rather than pasting a literal.

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
  -- Substitute the integer from query 3's err_fingerprint column (digits only):
  AND cityHash64(substring(r.error_message, 1, 60)) = 0000000000000000000
GROUP BY repo, err_prefix
HAVING runs > 0
ORDER BY runs DESC
LIMIT 30
```

## 5 — Silent non-completion (lens A)

Two separate questions with two different windows, which is why this is two queries.
A cancellation rate well above the baseline in query 1 is a prompt to look at what those tasks shared, not a finding on its own.

**5a — cancellation rate (windowed).**

```sql
SELECT
    t.repository                                                 AS repo,
    count()                                                      AS runs,
    countIf(r.status = 'cancelled')                              AS cancelled,
    round(100.0 * countIf(r.status = 'cancelled') / count(), 1)  AS cancel_pct,
    countIf(r.status IN ('not_started', 'queued', 'in_progress')) AS in_flight
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 14 day
  AND t.origin_product != 'signals_scout'
GROUP BY repo
HAVING runs > 20
-- Rate first: the guard above already handles volume, and a busy healthy repo would
-- otherwise displace the low-volume repo whose cancellation rate actually spiked.
ORDER BY cancel_pct DESC, cancelled DESC
LIMIT 20
```

**5b — aging backlog (deliberately unbounded).**
A run stuck for longer than the analysis window is the _most_ interesting one, so this query must not carry the 14-day lower bound that 5a does — that bound would hide exactly the runs it exists to find.

Apply the same runs-per-task discriminator here: `runs_per_stuck_task` ≫ 1 over few `stuck_tasks` is one task retrying, not a backlog.
**Known gap:** archiving a task sets `Task.archived` without transitioning its runs, and `system.tasks` exposes no `archived` column — so an archived task's stuck run cannot be filtered out here and will persist as a finding. Before filing a backlog report, confirm the task is still live via `tasks-retrieve`; treat an archived one as noise and record it under `noise:tasks:`.

```sql
SELECT
    t.repository                                                 AS repo,
    r.status                                                     AS status,
    count()                                                      AS stuck_runs,
    uniq(r.task_id)                                              AS stuck_tasks,
    round(count() / nullIf(uniq(r.task_id), 0), 1)               AS runs_per_stuck_task,
    min(r.created_at)                                            AS oldest,
    max(r.created_at)                                            AS newest
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.status IN ('not_started', 'queued', 'in_progress')
  AND r.created_at < now() - interval 1 day
  AND t.origin_product != 'signals_scout'
  -- `Task.soft_delete()` does not transition its runs, so without this a deleted task's
  -- stuck run stays "backlog" forever. This scan is unbounded, so that false finding never ages out.
  AND t.deleted = 0
  -- A local (Desktop) run can sit `queued` by design while the local agent drives it, so the
  -- cloud staleness rule doesn't apply to it. Restrict to cloud rather than reporting normal
  -- long-lived local sessions as silent non-completion.
  AND r.environment = 'cloud'
GROUP BY repo, status
-- Oldest first: the point of an unbounded scan is the run stuck for months, which ranking by
-- count would bury under several repos holding a few two-day-old runs.
ORDER BY oldest ASC, stuck_runs DESC
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
  AND origin_product IN ('user_created', 'slack', 'posthog_ai', 'hogdesk')
GROUP BY origin, repo
-- Requester spread first: the demand lens requires repetition across people, so one person's
-- high-volume queue must not displace groups where several people asked for the same thing.
ORDER BY requesters DESC, tasks DESC
LIMIT 30
```

## 7 — Demand theme sampling (lens B, gated) — NOT SQL

**Do not read task titles or descriptions from `system.tasks`.**
The system table applies only team scoping and `internal != true`. It does **not** apply `task_visibility_q`, the rule that keeps personal-channel ("#me") tasks readable by their creator alone, and it exposes no `channel` column, so that rule cannot be reconstructed here. Reading titles in SQL would let the scout summarize a teammate's private task into a team-visible report — content the run's own actor gets a 404 for through the API.

Read task text through the **MCP tools instead**, which enforce the boundary server-side for the token's user:

- `tasks-list` — page newest-first, filtered by `origin_product` to the demand origins (`user_created`, `slack`, `posthog_ai`, `hogdesk`). This is the theme-sampling surface.
- `tasks-retrieve` — full detail on one task when a theme is worth pursuing, and the source of `created_by.uuid` for reviewer routing.

Two properties of `tasks-list` shape how you call it, and neither is optional:

- **It returns `description` on every row**, up to 100 rows per page. There is no title-only projection, so "read titles at scale" is not free here the way it was in SQL — a full page on a project with long descriptions can swallow the run's context before you analyse anything. **Cap the sample: a small page size and a hard ceiling of a few pages per run.** Take the newest tasks, form themes from titles, and accept that a demand pass samples rather than enumerates. If you run out of budget, stop and record how far you got in `pattern:tasks:last-demand-pass` so the next pass resumes rather than restarting.
- **It has no `created_at` filter.** Filtering is by `origin_product` / `repository` / `created_by` only, so once an origin runs out of recent tasks the pages keep going backwards into older ones. **Discard any row whose `created_at` is past the 30-day demand window and stop paging that origin at the cutoff** — otherwise historical requests join a theme whose volume and requester counts (query 6) only cover current demand, and the two halves of the lens disagree.

Query 6 stays SQL because it returns only counts and aggregates — no task text crosses the boundary there.

## 8 — Lens intersection (the highest-value shape)

Tasks whose runs failed, restricted to human origins — where a delivery-health cluster and a demand theme overlap.
A capability people keep asking for that also keeps failing is the most actionable thing this scout can surface.

Returns **ids only, no task text**, for the same visibility reason as query 7: resolve each candidate with `tasks-retrieve`, which applies the visibility rule and 404s on a task this run's actor may not read. A 404 here is the boundary working — drop that task and move on, don't try to recover its title from SQL.

```sql
SELECT
    t.id                                                         AS task_id,
    t.repository                                                 AS repo,
    t.created_by_id                                              AS creator,
    substring(r.error_message, 1, 60)                            AS err_prefix,
    count()                                                      AS failed_runs
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE r.created_at > now() - interval 30 day
  AND r.status = 'failed'
  -- Lens B anchors on task creation, so bound the task too. Without this an old or
  -- soft-deleted request retried inside the window reads as current demand.
  AND t.created_at > now() - interval 30 day
  AND t.deleted = 0
  AND t.origin_product IN ('user_created', 'slack', 'posthog_ai', 'hogdesk')
GROUP BY task_id, repo, creator, err_prefix
ORDER BY failed_runs DESC
LIMIT 30
```

## 9 — Drill-down: a representative failing run (lens A)

Every other lens-A query aggregates, but a report has to cite concrete ids and the body sends you to `tasks-runs-retrieve`, which needs both a task id and a run id.
Run this once per cluster you're about to file, substituting the repository or error prefix that defines it, and cite what it returns.
It covers backlog findings as well as failures: query 5b returns no ids, and its stuck runs are neither `failed` nor inside a 14-day window, so the status and time predicates below are written to accept them.

```sql
SELECT
    r.id                                                         AS run_id,
    r.task_id                                                    AS task_id,
    t.repository                                                 AS repo,
    r.status                                                     AS status,
    substring(r.error_message, 1, 120)                           AS error_message,
    r.created_at                                                 AS run_created_at
FROM system.task_runs AS r
JOIN system.tasks AS t ON r.task_id = t.id
WHERE t.origin_product != 'signals_scout'
  AND t.deleted = 0
  -- Failure clusters: keep both lines as written.
  -- Backlog clusters (query 5b): swap the status list for
  -- ('not_started', 'queued', 'in_progress') AND replace the recent-run bound with
  -- `r.created_at < now() - interval 1 day`, then flip the ORDER BY to `r.created_at ASC`,
  -- and add `AND r.environment = 'cloud'` to match 5b's scope.
  -- Dropping the age predicate entirely would return the *newest* active runs, and dropping
  -- the environment one would surface a local run 5b never counted — either lets the report
  -- cite a run that was never part of the backlog it claims to evidence.
  AND r.status = 'failed'
  AND r.created_at > now() - interval 14 day
  -- Narrow to the cluster you are filing, e.g.:
  -- AND cityHash64(t.repository) = 0000000000000000000  -- repo_fingerprint from query 2
  -- AND cityHash64(substring(r.error_message, 1, 60)) = 0000000000000000000  -- err_fingerprint from query 3
ORDER BY r.created_at DESC
LIMIT 5
```
