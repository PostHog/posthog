---
name: investigating-ci-failures
description: >
  Investigates a specific CI failure to a verdict: whose fault, which commit, who wrote it, and
  whether it's fixed. Use for "who broke master", "why did this test fail in CI", "is this failure
  my PR's fault or everyone's", "is this test flaky or actually broken", "when did this failure
  start". Works from the engineering_analytics warehouse views (engineering_analytics_ci_failures,
  engineering_analytics_ci_job_history) plus the CI failure logs. Not for aggregate CI health, cost,
  or merge bottlenecks (use diagnosing-ci-and-merge-bottlenecks) and not for building saved insights
  (use turning-engineering-analytics-into-insights).
---

# Investigating CI failures

The job: take one failing test or one red run and get to a verdict a developer can act on —
_yours / trunk-borne / flaky_, and when trunk-borne: the culprit SHA, its author, the PR, and
whether a fix already landed. Everything below is derivation over data that already exists; you
never need to re-run CI to answer.

Two warehouse views are the substrate (both non-materialized — always current, query them freely):

- **`engineering_analytics_ci_failures`** — one row per pytest `FAILED <nodeid>` line from CI logs,
  pre-fingerprinted (`fingerprint` = test id + digit/hex-normalized error). Group by `fingerprint`
  to get first/last seen, occurrence count, and branch spread.
- **`engineering_analytics_ci_job_history`** — one row per job attempt with `conclusion` AND commit
  attribution: `head_sha`, `commit_author_name`, `commit_message`, `commit_pr_number` (parsed from
  the squash-merge suffix — the only PR attribution a master push run has). This is where greens
  live; the logs are failure-only, so every "when did it turn red / green again" question must come
  from here, never from the logs.

Copy-ready SQL for every step is in [references/investigation-queries.md](./references/investigation-queries.md).

## Before you start: confirm the substrate exists

Everything here runs over data that only exists once the team has Engineering analytics configured
— a connected GitHub source whose `workflow_runs` **and** `workflow_jobs` endpoints are both synced.
Without it the two views don't exist and every query below fails with
`Unknown table engineering_analytics_ci_failures`. Check first, so you don't dead-end mid-investigation:

1. Call the `engineering-analytics-sources` MCP tool. No source → the team hasn't connected a GitHub
   repo, so CI investigations aren't available yet. Point them at Engineering analytics setup (connect
   a GitHub source and sync its `workflow_runs` + `workflow_jobs` endpoints) and stop.
2. Probe the views (query 0 in the references). If it errors with `Unknown table …`, a source is
   connected but the CI views aren't provisioned — almost always because `workflow_jobs` isn't synced
   (all three views share that one gate). Say that and stop rather than running the workflow against
   tables that don't exist.

Only once both pass do you have the substrate the rest of this skill assumes.

## The three failure shapes

Fingerprint the failure first (query 1 in the references), then read its shape — the classification
falls out of three columns:

| Shape                                   | Reading                         | Next step                                            |
| --------------------------------------- | ------------------------------- | ---------------------------------------------------- |
| 1 branch, any window                    | That PR's own problem           | Read its failure lines; done                         |
| Many branches, dense burst, hits master | Trunk break (master is/was red) | Boundary query → culprit (below)                     |
| Many branches, sporadic over days/weeks | Flaky                           | Corroborate with `engineering-analytics-flaky-tests` |

Why cross-branch means trunk: PR CI runs the PR **merged with master**, so one bad master commit
fails every concurrently-running PR. A failure appearing on many unrelated branches in a tight
window is the signature of a master-merge break, not of those PRs' code. Tell the asker explicitly
when their PR is not at fault — that is usually the single most valuable sentence in the answer.

## Trunk break → culprit

Run the boundary query (query 2): master-only job history for the failing job, ordered by
`created_at`. The pattern reads directly:

```text
... success success | failure failure ... failure | success ...
                    ^ first red = the culprit row  ^ first green = the fix row
```

The culprit row carries everything: `head_sha`, `commit_author_name`, `commit_message` (which names
what changed), `commit_pr_number`. The first-green row identifies the fix the same way. Confidence
check before naming anyone: does the culprit commit plausibly touch the failing area (its message /
PR diff vs the failing test's module)? A boundary landing on an unrelated commit means sharding or
timing noise — widen the window and check the adjacent commit before asserting.

Then verify the failure window in `ci_failures` matches (first_seen just after the culprit merged,
last_seen shortly after the fix as the PR queue drained). Mismatch = you're looking at two
different problems sharing a test.

## Flaky → corroborate, don't guess

Sporadic shape alone is suggestive, not proof. The `engineering-analytics-flaky-tests` MCP tool reads per-test CI spans
(rerun-pass signal — a test that failed then passed on retry in the same job) and is the stronger
signal where it has coverage. Counts only, never rates: passing runs below the emitter's duration
threshold aren't recorded, so there is no honest denominator.

## Caveats you must carry into every answer

- **The logs are failure-only.** No green baseline exists in `ci_failures`; absence of a
  fingerprint is weak evidence (the job may simply not have run). Greens come from
  `ci_job_history` only.
- **Fingerprints are pytest-only (v1).** Jest / playwright / cargo failures appear in the raw
  failure logs but are not in `ci_failures`. For a specific PR, read them with the
  `engineering-analytics-ci-failure-logs` MCP tool (PR-scoped, grouped by job); across master, query
  the Logs product directly (`service.name = 'github-ci-logs'`, branch `master`) — there is no grouped
  pre-fingerprinted feed for non-pytest runners yet.
- **Freshness differs per source.** Logs stream in near-real-time; the warehouse jobs/runs tables
  arrive via webhook sync and can lag. During a live incident, start from `ci_failures` and check
  the warehouse's `max(created_at)` before trusting a boundary (query 5). A boundary computed
  against a stale warehouse names the wrong commit.
- **A run's `conclusion` can be stale** until the `workflow_run` webhook settles it (SPEC §9) —
  treat a very recent "failure-free" tail with suspicion.
- **Retries:** `run_attempt > 1` rows are the same job re-run. A failure that clears on attempt 2
  is flake signal; one that fails through attempt 5+ is deterministic.
- **Reverts:** a revert shows up as a _new_ first-green (or first-red) commit whose
  `commit_pr_number` is the reverting PR — attribution follows the revert, not the original.
- **Time-bound every logs query.** The failure-log stream is large; unbounded scans hit the read
  cap. 14 days covers almost every investigation.
- **Pair the warehouse twin too.** A `ci_job_history` query windowed on `created_at` alone forces a
  full jobs scan — the parsed timestamp is a computed column the parquet scan can't prune on. Add a
  coarse `created_at_raw >= '<YYYY-MM-DD>'` string floor (a day below the window) alongside the
  precise `created_at` bound so the scan skips; `created_at` stays the exact filter.

## Choosing a surface

| Question                               | Use                                                                    |
| -------------------------------------- | ---------------------------------------------------------------------- |
| "Why did MY PR's CI fail?"             | `engineering-analytics-ci-failure-logs` MCP tool (PR-scoped, grouped)  |
| "Who broke master / when did X start?" | The two views, workflow above                                          |
| "Is X flaky?"                          | Shape from `ci_failures` + the flaky-tests tool                        |
| "What's failing on master right now?"  | The novelty scan (query 4) over `ci_failures`; `workflow-health` (branch `master`) for non-pytest |
| "Is CI slow / expensive / PRs stuck?"  | The `diagnosing-ci-and-merge-bottlenecks` skill                        |
| "Save this as a dashboard/insight"     | The `turning-engineering-analytics-into-insights` skill                |

## Output expectations

Lead with the verdict and the exoneration/blame in plain words ("not your PR — master was broken
between 08:01 and 09:58 UTC by #68727; fixed by #68855"), then the evidence: the boundary rows, the
fingerprint window, occurrence/branch counts. Name the author factually (they authored the culprit
commit), never accusatorially — the commit message and PR link let the reader judge the change, and
half the time the "culprit" was a reasonable change with an unmocked test dependency.
