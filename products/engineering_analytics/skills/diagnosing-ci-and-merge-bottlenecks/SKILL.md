---
name: diagnosing-ci-and-merge-bottlenecks
description: >
  Diagnoses CI and pull-request pipeline health for a GitHub repo by querying the engineering analytics read
  layer with HogQL — two curated views (engineering_analytics_pull_requests, engineering_analytics_workflow_runs)
  over warehouse PR/CI data — plus the pr-lifecycle deep tool for a single PR. Use when asked whether CI is getting
  faster or slower, which GitHub Actions workflow is the slow or flaky long-pole, how long PRs take from open to
  merge, how an author's merge time compares to the cohort, which open PRs have failing or pending CI, or where a
  specific pull request is stuck. Triggers on "engineering analytics", "is CI getting slower", "slow workflow",
  "flaky CI", "time to merge", "cycle time", "PR throughput", "failing checks", "where is PR <n> stuck",
  "CI long pole", "what's holding up this PR".
---

# Diagnosing CI and merge bottlenecks

Engineering analytics treats a pull request like product analytics treats a user: a PR moves through a pipeline
(`opened → CI → review → merged → deployed`) and the job is to find where it slows down. The surface is **SQL over
two curated views** — query them with HogQL the same way you would any PostHog data — plus one named deep tool
(`pr-lifecycle`) for a single PR's timeline. Dogfooded on `PostHog/posthog`; the same surface serves autonomous
agents (e.g. PostHog Code) reasoning about their own PRs.

## The read layer

Two views over the GitHub warehouse snapshots. Every domain rule (bot detection, repo identity, the CI join, honest
metric naming) is already baked into these columns — you read them, you don't re-derive them.

### `engineering_analytics_pull_requests` — one row per PR

| column                                 | notes                                                                                  |
| -------------------------------------- | -------------------------------------------------------------------------------------- |
| `number`, `title`, `head_sha`          | `head_sha` is the join key to CI runs                                                  |
| `author_handle`, `author_avatar_url`   |                                                                                        |
| `is_bot`                               | `handle` ends in `[bot]` or is a known bot — **exclude by default** in throughput work |
| `repo_owner`, `repo_name`              | from `base.repo.full_name`                                                             |
| `labels`                               | array of label names, e.g. `has(labels, 'bug')`                                        |
| `state`                                | `open` / `closed` / `merged` (merged is derived from `merged_at`)                      |
| `is_draft`                             | **exclude by default** in throughput work                                              |
| `created_at`, `merged_at`, `closed_at` | `merged_at`/`closed_at` are null when not merged/closed                                |
| `open_to_merge_seconds`                | `merged_at − created_at`, **coarse** — see caveats. Null until merged                  |

### `engineering_analytics_workflow_runs` — one row per CI run

| column                                       | notes                                                                       |
| -------------------------------------------- | --------------------------------------------------------------------------- |
| `workflow_name`, `head_sha`                  |                                                                             |
| `status`                                     | `queued` / `in_progress` / `completed`                                      |
| `conclusion`                                 | `success` / `failure` / … or null — **may be stale**, see caveats           |
| `run_started_at`, `updated_at`, `created_at` | window CI trends on `created_at`                                            |
| `duration_seconds`                           | `updated_at − run_started_at`, **only for completed runs** (null otherwise) |
| `repo_owner`, `repo_name`                    | from `repository.full_name`                                                 |

## Caveats you must carry into every answer

These are structural limits of today's snapshot data — state them, don't paper over them.

- **`open_to_merge_seconds` is coarse.** It fuses _draft_ time and _ready-for-review_ time into one figure. Report it
  as "open-to-merge", never as "cycle time" or "review time". Flag it when long-lived drafts inflate a number.
- **CI `conclusion`/`status` can be stale.** `github_workflow_runs` syncs on a `created_at` watermark and does not
  refresh a run that completes after newer runs land (until the `workflow_run` webhook ships). A PR can show
  `failing` or `in_progress` when CI has actually moved on. Lead with `status`; treat a non-`completed` run as
  unsettled, not as a verdict.
- **CI for a PR = the `head_sha` join, nothing else.** A PR's checks are the workflow runs whose `head_sha` matches
  the PR's `head_sha`. There is no other link. Only the latest commit's runs reflect current state.
- **No reviews, approvals, per-check/job, or deploys yet.** Don't infer review behavior or DORA metrics from absence;
  that data hasn't landed. `pr-lifecycle` is `partial` for the same reason.
- **Bots and drafts are first-class in the data, excluded by convention.** Throughput / time-to-merge recipes add
  `AND NOT is_bot AND NOT is_draft`. Keep them in for bot-impact questions.

## Recipes

Run these with the HogQL query tool. Adjust windows and filters to the question.

### Is CI getting faster or slower?

There is no built-in trend — produce one by running this over two adjacent windows and comparing per workflow.

```sql
SELECT
    workflow_name,
    count() AS runs,
    countIf(conclusion = 'success') / count() AS success_rate,
    quantile(0.5)(duration_seconds) AS p50_seconds,
    quantile(0.95)(duration_seconds) AS p95_seconds,
    maxIf(updated_at, conclusion = 'failure') AS last_failed_at
FROM engineering_analytics_workflow_runs
WHERE status = 'completed'
  AND created_at >= now() - INTERVAL 7 DAY
GROUP BY workflow_name
ORDER BY p50_seconds DESC
```

Lead with the **median** (typical experience) but always check **p95** separately — they move independently. A
falling median with a rising p95 means the common case improved while a long tail got worse; name the workflow
driving the tail. Cross-reference `success_rate` and `last_failed_at`: slow _and_ failing often is "bad friction"
worth removing; slow-but-reliable is a duration problem. Filter `status = 'completed'` so `duration_seconds` is real.

### How long are PRs taking to merge?

```sql
SELECT
    quantile(0.5)(open_to_merge_seconds) AS p50_seconds,
    quantile(0.95)(open_to_merge_seconds) AS p95_seconds,
    count() AS merged_prs
FROM engineering_analytics_pull_requests
WHERE merged_at IS NOT NULL
  AND merged_at >= now() - INTERVAL 30 DAY
  AND NOT is_bot AND NOT is_draft
```

Add `author_handle` to the `SELECT` and `GROUP BY` for per-author buckets. Frame per-author output as **cohort
context, not a ranking** — per-developer surveillance is an explicit non-goal. A high bucket is a prompt to ask
"what's blocking these PRs", not a scoreboard. Report `open_to_merge_seconds` as open-to-merge and carry the coarse
caveat. Trend it like CI — two adjacent windows — when asked whether merge time is improving.

### Which open PRs have failing or pending CI? (the head_sha join)

```sql
SELECT
    pr.number,
    pr.title,
    pr.author_handle,
    countIf(wr.conclusion = 'failure') AS failing_checks,
    countIf(wr.conclusion = 'success') AS passing_checks,
    countIf(wr.status != 'completed') AS pending_checks
FROM engineering_analytics_pull_requests AS pr
LEFT JOIN engineering_analytics_workflow_runs AS wr ON wr.head_sha = pr.head_sha
WHERE pr.state = 'open' AND NOT pr.is_draft AND NOT pr.is_bot
GROUP BY pr.number, pr.title, pr.author_handle
HAVING failing_checks > 0 OR pending_checks > 0
ORDER BY failing_checks DESC, pending_checks DESC
```

`pending_checks > 0` means CI is unsettled (or stale per the caveat) — don't report it as a settled failure.

### Which PRs are stuck open the longest?

```sql
SELECT number, title, author_handle, dateDiff('day', created_at, now()) AS age_days
FROM engineering_analytics_pull_requests
WHERE state = 'open' AND NOT is_draft AND NOT is_bot
ORDER BY age_days DESC
LIMIT 20
```

## When to use `pr-lifecycle`

For a **single** PR's timeline, call the `pr-lifecycle` deep tool instead of writing SQL — it assembles the header
plus the ordered CI-run events (opened → CI started/finished → merged/closed) across both views in one call.

```text
pr-lifecycle { pr_number: N }   # add repo: "owner/name" only to disambiguate across connected repos
```

Walk the timeline and measure the gaps: `opened → CI started`, CI duration, `CI finished → merged/closed`. The
largest gap is the bottleneck. A long open→merge with quick CI points at review/idle time (which the `partial` data
can't itemize yet — say so); slow CI shows up directly as the CI gap. `metric_quality` is `partial` — carry it.

## The high-value chain

Mirror how a human investigates: aggregate signal → confirm → concrete PR.

```text
workflow-health recipe (find the slow/flaky long-pole workflow)
   → time-to-merge recipe (confirm it's dragging overall merge time)
      → pr-lifecycle (open a representative stuck PR and show the gap)
```

"CI median rose because `e2e-playwright` p95 doubled; that workflow is the long pole on PR #1234, which sat 47m in
CI before merging."

## Output expectations

- Lead with the verdict in one line, then the supporting numbers.
- Carry the coarse / partial / staleness caveat whenever the distinction matters.
- For multi-window or multi-workflow comparisons, a short table beats prose. Report median and p95 side by side —
  never collapse them into one "average".

## What NOT to do

- Don't call `open_to_merge_seconds` cycle time or review time — it's coarse open-to-merge.
- Don't report a CI `conclusion` as settled when `status` isn't `completed` — it may be stale.
- Don't infer reviews, approvals, per-check counts, or deploys — that data isn't ingested yet.
- Don't turn per-author buckets into a leaderboard — they're for finding stuck work, not ranking people.
- Don't reach for this data to fetch raw PR contents or diffs — it surfaces pipeline signal, not the PR thread.
