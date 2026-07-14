---
name: diagnosing-ci-and-merge-bottlenecks
description: >
  Diagnoses CI and pull-request pipeline health for a GitHub repo using the engineering analytics MCP tools —
  pull-requests (PR list with CI status), workflow-health (per-workflow CI trends), and pr-lifecycle (a single PR's
  timeline). Use when asked whether CI is getting faster or slower, which GitHub Actions workflow is the slow or
  flaky long-pole, how long PRs take from open to merge, how an author's merge time compares to the cohort, which
  open PRs have failing or pending CI, or where a specific pull request is stuck. Also routes CI health to owning
  teams: which team owns the flakiest test surfaces, and whether one team's CI signal is getting better or worse.
  Triggers on "engineering analytics", "is CI getting slower", "slow workflow", "flaky CI", "time to merge",
  "cycle time", "PR throughput", "failing checks", "where is PR <n> stuck", "CI long pole", "what's holding up
  this PR", "which team owns", "team CI health".
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
- **`workflow-health`** — per-workflow CI health over a window (`date_from` / `date_to`, default last 24 hours):
  `run_count`, `success_rate`, `p50_seconds`, `p95_seconds`, `last_failure_at`. Answers "is CI getting faster or
  slower" and "which workflow is the slow or flaky long pole". There is no built-in trend — call it over two
  adjacent windows and compare. `success_rate` covers completed runs; `p50_seconds` / `p95_seconds` cover
  successful runs only (cancelled and failed runs end early and would bias the duration trend). Each is `null`
  when a window has no qualifying runs — guard for null before comparing two windows (a workflow can have runs
  in one and none in the other). `run_scope=pull_request` scopes to PR-attributed runs, excluding master/main
  (same-repo PRs only — fork runs carry no PR attribution).
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
- **`engineering-analytics-team-ci-health`**: the per-owning-team roster over a window (`date_from` default
  `-14d`, max 30 days): flaky-test count (the leaderboard's qualification bar applied per team), failed/error
  and pass-on-retry span counts, each with an equal-length previous-window twin (`*_prior`) for honest deltas.
  Answers "which team owns the flakiest surfaces" and routes a CI finding to its owning team. Ownership is
  stamped on each test span at CI emission time from the repo's ownership map (products/\*/product.yaml +
  CODEOWNERS); a nonempty `unowned` row means ownership gaps, not a real team. Teams own code surfaces, never
  authors.
- **`engineering-analytics-team-ci-activity`**: one team's drill-down: the daily signal series over the window
  plus per-test current-vs-prior signal pairs, capped at `test_limit` (`truncated_tests` set when more
  qualified). Answers "is this team's CI health getting better or worse, and which tests moved". Pass
  `owner_team` exactly as the roster returned it (including `unowned`); each test row carries the pytest nodeid
  and a runnable selector.

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
- **Team attribution is capture-time ownership.** Test spans are stamped with the owning team when CI emits them,
  so a test is attributed to whoever owned it when it ran, and spans emitted before the stamp existed (or from
  paths with no owner) aggregate under `unowned`. Report a growing `unowned` row as an ownership gap to fix, never
  as a team.

## Choosing a tool

| The question                                           | Tool                                     | How                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------ | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Is CI getting slower? Which workflow is the long pole? | `workflow-health`                        | Call over two adjacent windows (e.g. `date_from=-14d`, then `date_from=-28d` `date_to=-14d`); compare `p50_seconds` and `p95_seconds` per workflow. Lead with the median but always check p95 separately — they move independently.                                                            |
| Which open PRs have failing or pending CI?             | `pull-requests`                          | Keep rows where `ci.failing > 0` or `ci.pending > 0`. `pending` means unsettled (or stale) — not a settled failure.                                                                                                                                                                            |
| Which PRs are stuck open longest?                      | `pull-requests`                          | Keep `state = open`, not `is_draft`, not `author.is_bot`; sort by `created_at` ascending (oldest first).                                                                                                                                                                                       |
| How long are PRs taking to merge? Per author?          | `pull-requests`                          | Over merged rows (`merged_at` set, not bot, not draft), aggregate `open_to_merge_seconds` — median and p95. Group by `author.handle` for **cohort context, not a ranking** (per-developer surveillance is an explicit non-goal). Trend it by calling with two `date_from` windows.             |
| Where is PR N stuck?                                   | `pr-lifecycle`                           | Walk the sorted events: `opened → first CI started`, the CI span (first start → last finish; one pair per workflow), `last CI finished → merged`. The largest gap is the bottleneck. A long open→merge with quick CI points at review/idle time the `partial` data can't itemize yet — say so. |
| Which tests are flaky? What should be quarantined?     | `engineering-analytics-flaky-tests`      | Default window is `-7d`; rows are already ranked by `rerun_passed_count` + `failed_pr_count`. Report counts, never rates. A no-rerun lane surfaces flakes as plain failures — that's what `failed_pr_count` catches.                                                                           |
| Which team owns the flakiest CI surfaces?              | `engineering-analytics-team-ci-health`   | Default window is `-14d`. Rank by `flaky_test_count` + `failed_count`; compare each figure to its `*_prior` twin for the trend. Report a nonempty `unowned` row as an ownership gap, not a team.                                                                                               |
| Is team X's CI getting better or worse? What moved?    | `engineering-analytics-team-ci-activity` | Pass `owner_team` from the roster verbatim. Compare `signal_count` vs `signal_count_prior` per test; the daily series shows when it moved. Use each row's selector to run the test locally.                                                                                                    |

## The high-value chain

Mirror how a human investigates: aggregate signal → confirm → concrete PR.

```text
workflow-health  (find the slow/flaky long-pole workflow)
   → pull-requests  (confirm it's dragging merge time; list the affected PRs)
      → pr-lifecycle  (open a representative stuck PR and show the gap)
```

"CI median rose because `e2e-playwright` p95 doubled; that workflow is the long pole on PR #1234, which sat 47m in
CI before merging."

For routing flaky-test health to owners, the chain runs roster to drill-down:

```text
team-ci-health  (which team owns the flakiest surfaces; is 'unowned' growing)
   → team-ci-activity  (that team's daily trend and the specific tests that moved)
      → engineering-analytics-flaky-tests  (cross-team context for the same tests)
```

"batch-exports holds 4 of the top 10 flaky tests, flat vs the prior window; team-replay is the mover, 2 to 3
qualifying tests, driven by test_snapshot_batching (9 signal spans vs 2 prior)."

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

## Persisting an answer

These tools are ad-hoc reads; they cannot be saved as an insight or subscribed to. When the user wants the same
numbers as a saved insight, a dashboard tile, or a scheduled email/Slack delivery, switch to the
`turning-engineering-analytics-into-insights` skill: the underlying warehouse tables
(`<prefix>github_pull_requests` / `<prefix>github_workflow_runs`, prefix from `engineering-analytics-sources`)
are directly queryable with HogQL, and that skill carries the curated column semantics plus the
insight-create / subscriptions-create workflow.
