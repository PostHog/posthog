---
name: diagnosing-ci-and-merge-bottlenecks
description: >
  Diagnoses CI and pull-request pipeline health for a GitHub repo using the engineering analytics MCP tools —
  pull-requests (PR list with CI status), workflow-health (per-workflow CI trends), and pr-lifecycle (a single PR's
  timeline). Use when asked whether CI is getting faster or slower, which GitHub Actions workflow is the slow or
  flaky long-pole, how long PRs take from open to merge, how an author's merge time compares to the cohort, which
  open PRs have failing or pending CI, or where a specific pull request is stuck. Triggers on "engineering
  analytics", "is CI getting slower", "slow workflow", "flaky CI", "time to merge", "cycle time", "PR throughput",
  "failing checks", "where is PR <n> stuck", "CI long pole", "what's holding up this PR".
---

# Diagnosing CI and merge bottlenecks

Engineering analytics treats a pull request like product analytics treats a user: a PR moves through a pipeline
(`opened → CI → review → merged → deployed`) and the job is to find where it slows down. The surface is **named
MCP tools** — you call them, you don't write SQL. Dogfooded on `PostHog/posthog`; the same tools serve
autonomous agents (e.g. PostHog Code) reasoning about their own PRs.

## The tools

- **`pull-requests`** — the PR workhorse. Open PRs plus anything merged or closed since `date_from` (default
  `-30d`), newest first. Each row carries `author` (nested object: `handle`, `display_name`, `is_bot`), `repo`
  (nested: `owner`, `name`), `state`, `is_draft`, `labels`, `open_to_merge_seconds`, and a `ci` rollup
  (`runs` / `passing` / `failing` / `pending`) from the head-SHA join. Answers most PR-level questions:
  which PRs have failing or pending CI, which are stuck open longest, per-author or per-repo triage, and
  time-to-merge stats (aggregate `open_to_merge_seconds` over the returned merged rows yourself — median and p95,
  never a mean).
- **`workflow-health`** — per-workflow CI health over a window (`date_from` / `date_to`, default last 30 days):
  `run_count`, `success_rate`, `p50_seconds`, `p95_seconds`, `last_failure_at`. Answers "is CI getting faster or
  slower" and "which workflow is the slow or flaky long pole". There is no built-in trend — call it over two
  adjacent windows and compare. `success_rate` / `p50_seconds` / `p95_seconds` cover completed runs only and are
  `null` when a window has no completed runs — guard for null before comparing two windows (a workflow can have
  runs in one and none in the other).
- **`pr-lifecycle`** — a single PR's timeline: a header plus ordered events — opened, then a CI started/finished
  pair **per workflow run** (many on a multi-workflow repo, interleaved by time), then merged/closed. Answers
  "where is PR N stuck". `metric_quality` is `partial`.
- **`engineering-analytics-flaky-tests`** — per-test flakiness leaderboard from the per-test CI spans, over a
  window (`date_from` default `-7d`, max 30 days). A test qualifies by passing on an automatic retry
  (`rerun_passed_count`, the strongest signal — only rerun-enabled CI lanes emit it) or failing on ≥
  `min_failed_prs` distinct PRs (`failed_pr_count`, the signal for no-rerun lanes). Answers "which tests are
  flaky right now" and picks quarantine candidates; `xfailed_count > 0` means already quarantined but still
  failing. Counts are absolute signal, never rates — passing runs are mostly not emitted, so there is no honest
  denominator.

There is no aggregate time-to-merge tool and no "counts" tool — derive those from `pull-requests` (the stuck/failing
counts, the merge-time percentiles).

## Caveats you must carry into every answer

These are structural limits of today's snapshot data — state them, don't paper over them.

- **`open_to_merge_seconds` is coarse.** It fuses _draft_ time and _ready-for-review_ time into one figure. Report
  it as "open to merge", never "cycle time" or "review time". Flag it when long-lived drafts inflate a number.
- **CI status can be stale.** The CI source syncs on a watermark and does not refresh a run that completes after
  newer runs land (until the `workflow_run` webhook ships). Treat a `pending` count as unsettled, not as a settled
  failure; lead with status, not a verdict.
- **CI for a PR is the head-SHA join, nothing else.** The `ci` rollup reflects only the latest commit's runs. There
  is no other link between a PR and its checks.
- **No reviews, approvals, per-check/job, or deploys yet.** Don't infer review behaviour or DORA metrics from their
  absence; that data hasn't landed. `pr-lifecycle` is `partial` for the same reason.
- **Bots and drafts are present in `pull-requests` output, excluded by convention.** Filter out `author.is_bot`
  (nested under `author`, not a row-level field) and `is_draft` for throughput / merge-time questions; keep them in
  for bot-impact questions.
- **`pull-requests` returns a capped page.** At most `limit` rows (newest first); `truncated` is `true` when more
  match, and there is no repo or limit filter to narrow the call. When `truncated` is `true`, any percentile or
  count you derive covers only the newest page — not the whole window — so say so and shrink `date_from` until the
  real set fits under the cap.

## Choosing a tool

| The question                                           | Tool                                | How                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------ | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Is CI getting slower? Which workflow is the long pole? | `workflow-health`                   | Call over two adjacent windows (e.g. `date_from=-14d`, then `date_from=-28d` `date_to=-14d`); compare `p50_seconds` and `p95_seconds` per workflow. Lead with the median but always check p95 separately — they move independently.                                                            |
| Which open PRs have failing or pending CI?             | `pull-requests`                     | Keep rows where `ci.failing > 0` or `ci.pending > 0`. `pending` means unsettled (or stale) — not a settled failure.                                                                                                                                                                            |
| Which PRs are stuck open longest?                      | `pull-requests`                     | Keep `state = open`, not `is_draft`, not `author.is_bot`; sort by `created_at` ascending (oldest first).                                                                                                                                                                                       |
| How long are PRs taking to merge? Per author?          | `pull-requests`                     | Over merged rows (`merged_at` set, not bot, not draft), aggregate `open_to_merge_seconds` — median and p95. Group by `author.handle` for **cohort context, not a ranking** (per-developer surveillance is an explicit non-goal). Trend it by calling with two `date_from` windows.             |
| Where is PR N stuck?                                   | `pr-lifecycle`                      | Walk the sorted events: `opened → first CI started`, the CI span (first start → last finish; one pair per workflow), `last CI finished → merged`. The largest gap is the bottleneck. A long open→merge with quick CI points at review/idle time the `partial` data can't itemize yet — say so. |
| Which tests are flaky? What should be quarantined?     | `engineering-analytics-flaky-tests` | Default window is `-7d`; rows are already ranked by `rerun_passed_count` + `failed_pr_count`. Report counts, never rates. A no-rerun lane surfaces flakes as plain failures — that's what `failed_pr_count` catches.                                                                           |

## The high-value chain

Mirror how a human investigates: aggregate signal → confirm → concrete PR.

```text
workflow-health  (find the slow/flaky long-pole workflow)
   → pull-requests  (confirm it's dragging merge time; list the affected PRs)
      → pr-lifecycle  (open a representative stuck PR and show the gap)
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
- Don't report a CI count as a settled failure when `pending > 0` — it may be unsettled or stale.
- Don't infer reviews, approvals, per-check counts, or deploys — that data isn't ingested yet.
- Don't turn per-author buckets into a leaderboard — they're for finding stuck work, not ranking people.
- Don't reach for these tools to fetch raw PR contents or diffs — they surface pipeline signal, not the PR thread.
