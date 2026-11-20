---
name: investigating-ci-failures
description: 'Investigates one CI failure to a verdict: whose fault it is, which commit caused it, who wrote that commit, and whether a fix has landed. Use for "who broke master", "why did this test fail in CI", "is this failure my PR or everyone", "is this test flaky or broken", "when did this failure start", "what is broken in CI right now", and "why did the merge queue kick my PR". Works from the engineering-analytics-broken-tests tool, the CI failure log tools, and two warehouse views: engineering_analytics_ci_failures and engineering_analytics_ci_job_history. Not for aggregate CI health, cost, or merge bottlenecks (use diagnosing-ci-and-merge-bottlenecks), and not for saved insights (use turning-engineering-analytics-into-insights).'
---

# Investigating CI failures

Take one failing test or one red run to a verdict: the PR's own bug, a default-branch break, or a flaky test.
For a default-branch break, also name the culprit commit, its author, its PR, and the fix if one landed.
You never need to re-run CI to answer.

## Choosing a starting point

| Question                                        | Use                                                                    |
| ----------------------------------------------- | ---------------------------------------------------------------------- |
| What is broken across CI right now?             | `engineering-analytics-broken-tests`                                   |
| Why did my PR's CI fail?                        | `engineering-analytics-ci-failure-logs` with the PR number             |
| Why did this run fail?                          | `engineering-analytics-run-failure-logs` with `run_id` and `ci_engine` |
| Who broke master? When did this failure start?  | The two views, with the steps below                                    |
| Is this test flaky?                             | The failure's shape, then `engineering-analytics-flaky-tests`          |
| Is this setup or infrastructure failure common? | Job conclusions, query 7                                               |

Query the two views with the `execute-sql` tool:

- `engineering_analytics_ci_failures` has one row per pytest `FAILED <nodeid>` line from the CI logs. `fingerprint` joins the test id to a normalized error, so it groups one failure across runs.
- `engineering_analytics_ci_job_history` has one row per job attempt, with its `conclusion` and commit attribution: `head_sha`, `commit_author_name`, `commit_message`, and `commit_pr_number`.

The logs hold failures only.
Passing jobs exist only in the job history, so every question about when a job turned red or green must use it.

Every numbered query is in [references/investigation-queries.md](./references/investigation-queries.md).

## Triage with the broken-tests tool

`engineering-analytics-broken-tests` groups the last 2 days of failures by fingerprint and returns the most urgent first.
Each row's `state` is one of `breaking_master`, `blocking_merge_queue`, `novel_burst`, `potentially_resolved`, `flaky`, or `pr_only`.
The tool's description defines each state.
`breaking_master_jobs` lists the default-branch jobs whose latest run is red.
Pass a row's `latest_run_id` and `latest_ci_engine` to `engineering-analytics-run-failure-logs` to read the failing lines.
The list stops at 200 rows, so pass `test` or `branch` to ask about one test or one PR.

## Reading a failure's shape

Fingerprint the failure with query 1, then read the branch count, the time window, and the master hits.

| Shape                                             | Reading                                         | Next step                                             |
| ------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------- |
| One PR branch                                     | That PR's own problem                           | Read its failure lines.                               |
| One `trunk-merge/pr-<n>/...` gate branch          | A conflict with trunk or with a PR queued ahead | Run query 8, then compare the gate branch with trunk. |
| Many branches in a tight window, with master hits | A default-branch break                          | Run query 2 to find the culprit.                      |
| Many branches, scattered over days or weeks       | Flaky                                           | Confirm with `engineering-analytics-flaky-tests`.     |

PR CI tests the PR merged with the default branch.
One bad commit there fails every PR that runs at the same time.
When the failure is not the asker's fault, say so in the first sentence.

A merge-queue gate branch carries trunk, the PR, and the PRs queued ahead of it.
The PR already passed its own CI, so a failure there is not that PR's bug by default.

## Finding the culprit of a default-branch break

Query 2 lists the failing job's history on the default branch in time order.
The first `failure` after a `success` is the culprit row.
The first `success` after the red streak is the fix row.
Each row carries the SHA, the author, the commit message, and `commit_pr_number`.

Check two things before you name a commit:

- The commit's message or diff should plausibly touch the failing test's area. If it does not, widen the window and check the adjacent commits.
- The fingerprint's `first_seen` should fall just after the culprit merged. A mismatch means two different problems share one test.

A revert appears as a new commit whose `commit_pr_number` is the reverting PR.

## Checking for a flake

Read the other attempts before you say "flaky".
`run_attempt > 1` rows are re-runs of the same job on the same commit.
A failure that clears on a later attempt suggests a flake, and query 6 tracks the fingerprint across attempts.
A branch where every run is red has a deterministic failure, and a re-run changes none of its inputs.

`engineering-analytics-flaky-tests` marks a test `confirmed_flake` only when one commit both failed and passed it.
Its counts are absolute and never rates, because CI does not emit fast passing runs.

## Caveats

- Fingerprints cover pytest only. For Jest, Playwright, or Cargo failures, read the raw lines with the two failure-log tools.
- A job that failed before its tests ran writes no `FAILED` line. No test-level tool sees it. Only job conclusions show it, through query 7.
- The logs arrive within minutes, but the job history arrives by webhook sync and can lag. During a live incident, run query 5 before you trust a boundary.
- Keep `ci_engine` with every `run_id`. A null engine means unknown provenance, so do not join it to a known engine by integer id.
- Put a time bound on every query. Logs retention is short.
- For the job history, add a string floor such as `created_at_raw >= '<YYYY-MM-DD>'`, one day below the window. The parsed `created_at` filter alone forces a full scan.
- On `depot-*` runners, `actions/cache` reads Depot Cache, which the GitHub cache API cannot see. Read the job's `Cache not found for input keys:` line before you blame a cache eviction.

## Reporting

Lead with the verdict in plain words, including whether the asker's PR is at fault.
Then give the evidence: the boundary rows, the fingerprint window, and the occurrence and branch counts.
Name the author as a fact, not as blame, and link the commit and the PR.
