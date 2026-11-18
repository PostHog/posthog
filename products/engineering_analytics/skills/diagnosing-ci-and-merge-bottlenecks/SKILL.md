---
name: diagnosing-ci-and-merge-bottlenecks
description: 'Diagnoses CI and pull request pipeline health for a GitHub repo with the engineering analytics MCP tools: pull-requests, workflow-health, pr-lifecycle, engineering-analytics-flaky-tests, engineering-analytics-team-ci-health, and the CI cost tools. Use when asked whether CI is getting faster or slower, which GitHub Actions workflow is slow or failing, how long PRs take from open to merge, which open PRs have failing or pending CI, where one pull request is stuck, what a failing test costs, which team owns the flakiest tests, or what CI costs for a PR or workflow. Triggers on "engineering analytics", "is CI getting slower", "slow workflow", "flaky CI", "time to merge", "cycle time", "PR throughput", "failing checks", "where is PR <n> stuck", "CI long pole", "CI cost". For a verdict on one CI failure use investigating-ci-failures. To save these numbers as insights use turning-engineering-analytics-into-insights.'
---

# Diagnosing CI and merge bottlenecks

This skill finds where a pull request slows down between open and merge.
You call named MCP tools and write no SQL.
To take one failing test or one red run to a verdict, use the `investigating-ci-failures` skill.

## Choosing a tool

| Question                                                  | Tool                                          | How                                                                                                                                                               |
| --------------------------------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Is CI getting slower? Which workflow is slowest?          | `workflow-health`                             | Call it over two adjacent windows, for example `date_from=-14d`, then `date_from=-28d` with `date_to=-14d`. Compare `p50_seconds` and `p95_seconds` per workflow. |
| Which open PRs have failing or pending CI?                | `pull-requests`                               | Keep rows where `ci.failing > 0` or `ci.pending > 0`.                                                                                                             |
| Which PRs are stuck open longest?                         | `pull-requests`                               | Keep open rows that are not drafts or bots. Sort by `created_at`, oldest first.                                                                                   |
| How long do PRs take to merge?                            | `pull-requests`                               | Pass `state=merged`. Report the median and p95 of `ready_to_merge_seconds`.                                                                                       |
| Where is PR N stuck?                                      | `pr-lifecycle`                                | Find the largest gap between consecutive events.                                                                                                                  |
| What does a failing test cost? What should we quarantine? | `engineering-analytics-flaky-tests`           | Rows arrive ranked by master failures, then by distinct PRs hit.                                                                                                  |
| Which team owns the flakiest tests?                       | `engineering-analytics-team-ci-health`        | Each count has a `_prior` twin for the previous window of equal length.                                                                                           |
| What did CI cost for one PR?                              | `engineering-analytics-pr-cost`               | A null cost means nothing was billable. It never means zero.                                                                                                      |
| Which runner tier drives a workflow's cost?               | `engineering-analytics-workflow-runner-costs` | Rows arrive with the highest spend first.                                                                                                                         |
| Where did one run spend its time and money?               | `engineering-analytics-workflow-jobs`         | Pass `ci_engine` with `run_id`.                                                                                                                                   |

A common sequence is `workflow-health` to find the slow workflow, `pull-requests` to list affected PRs, then `pr-lifecycle` on one of them.

## Picking the repo

`engineering-analytics-sources` lists one entry per repository a connected GitHub source syncs.
With one entry, skip it, because the other tools default to that repo.
With more than one, pass the chosen entry's `id` as `source_id` and its `repo` as `repo`.
Passing only `source_id` reads the source's default repo, not the one you picked.

## What the numbers mean

### `pull-requests`

- `open_to_merge_seconds` is `merged_at` minus `created_at`, so it includes draft time. Call it "open to merge", never "cycle time" or "review time".
- `ready_to_merge_seconds` is the cycle time. It runs from the last ready-for-review transition to the merge, or from `created_at` for a PR that was never a draft.
- A null `ready_to_merge_seconds` means the tool did not observe the transition. It never means zero. Aggregate over non-null rows and say how many rows that covers.
- Report the median and the p95 together. Never report a mean.
- `ci` counts the latest run per workflow on the PR's current head SHA. Runs from earlier pushes are not in it.
- A run's conclusion arrives by webhook and can lag. Report `ci.pending` as unsettled, not as a failure.
- Rows include bots and drafts. Exclude `author.is_bot` and `is_draft` for throughput and merge-time questions.
- A page holds up to 1000 rows. While `truncated` is true, call again with `offset` increased by `limit`, and keep `date_to` fixed. `author` narrows the list to one handle.
- No tool in this skill returns review or approval data. Do not infer review behavior from its absence.

### `workflow-health`

- The window defaults to the last 24 hours.
- `success_rate` excludes skipped, cancelled, neutral, and action-required runs.
- `p50_seconds` and `p95_seconds` cover successful runs only, because failed and cancelled runs end early.
- Each of these three fields is null when the window has no qualifying runs. Check for null before you compare two windows.
- `run_scope=pull_request` leaves out fork PRs, because their runs carry no PR attribution.

### `pr-lifecycle`

- Each workflow run adds its own `ci_started` and `ci_finished` pair, so a PR with many workflows has many interleaved pairs.
- Draft and ready transitions appear only when the source syncs the issue-events table, and only for a bounded recent window.
- `metric_quality` is `partial` because the timeline has no review or comment events. A long gap after fast CI is probably review or idle time, and the data cannot split the two.

### `engineering-analytics-flaky-tests`

- The tool reads per-test CI spans from the main Backend pytest and Frontend Jest suites only. The window defaults to `-7d` and allows at most 30 days.
- `classification` is `confirmed_flake` only when `same_commit_recovery_run_count > 0`. That means one commit both failed and passed the test in the same matrix job.
- `quarantined` wins over `confirmed_flake`. It means a failure was recorded while the test was masked.
- `suspected_regression` means the data holds failures and no recovery. That does not prove a real break.
- Counts are absolute and never rates, because CI does not emit fast passing runs.
- The tool does not list every flaky test. Recovery proof exists only when someone re-ran failed jobs or the test retried inside its job.
- The tool drops every trial from a CI setup break, such as a job attempt with 100 or more failed tests. When a whole suite goes red, check `workflow-health` and do not read an empty queue as healthy.
- To ask about one test or one PR, pass `test`, `branch`, or `pr_number`, and add `min_failed_prs=1`.

### `engineering-analytics-team-ci-health`

- Counts are distinct CI runs and are absolute, never rates.
- A team is the owner of a code area, never a group of authors. A non-empty `unowned` row means ownership gaps.

## Reporting

- Lead with the verdict in one sentence, then give the numbers that support it.
- Never rank or compare authors by merge time or throughput. Group by `author.handle` only to find stuck work.

## Saving an answer

These tools answer one question at a time, and you cannot save or subscribe to their output.
For a saved insight, a dashboard tile, or a scheduled delivery, use the `turning-engineering-analytics-into-insights` skill.
