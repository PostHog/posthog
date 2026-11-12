---
name: turning-engineering-analytics-into-insights
description: 'Turns engineering analytics (PR and CI) data into saved PostHog insights, dashboards, and subscriptions, and explains how to query the data with SQL. Covers finding the per-team GitHub warehouse tables with engineering-analytics-sources, writing HogQL that matches the product''s own rules, reading the managed engineering_analytics_* warehouse views for CI cost, job history, and fingerprinted failures, saving queries with insight-create, and scheduling delivery with subscriptions-create. Use when asked to "save this as an insight", "put CI health or merge times on a dashboard", "email me PR throughput weekly", "chart CI cost", "track time to first review", "subscribe to these numbers", "alert on CI success rate", or "what tables and views does engineering analytics read". For one-off CI and merge questions use diagnosing-ci-and-merge-bottlenecks. To investigate one CI failure use investigating-ci-failures.'
---

# Turning engineering analytics into insights and subscriptions

You cannot save an engineering analytics MCP tool's output as an insight or subscribe to it.
The same data is queryable with HogQL, and a SQL insight over it can go on a dashboard or into a subscription.

## Where the data lives

| Data                                                    | Where to query it                                              | Insight?                      |
| ------------------------------------------------------- | -------------------------------------------------------------- | ----------------------------- |
| PRs, merge times, workflow runs                         | `<prefix>github_pull_requests`, `<prefix>github_workflow_runs` | Yes                           |
| Job durations and queue times                           | `<prefix>github_workflow_jobs`                                 | Yes                           |
| Reviews and approvals                                   | `<prefix>github_reviews`                                       | Yes                           |
| Team-level PR metrics                                   | `<prefix>github_team_members`, as a membership filter          | Yes, as team aggregates only  |
| CI cost per job attempt                                 | `engineering_analytics_job_costs` view                         | Yes                           |
| Job history with commit attribution                     | `engineering_analytics_ci_job_history` view                    | Yes                           |
| Fingerprinted pytest failure lines                      | `engineering_analytics_ci_failures` view                       | Yes, for short recent windows |
| Flaky tests, broken tests, team CI health, failure logs | MCP tools only                                                 | No                            |

The three views have fixed names and no prefix.
A project has them once someone has opened engineering analytics and a GitHub source syncs both workflow runs and workflow jobs.
They are not materialized, so each query computes them from current data.
The two job views also include Depot CI jobs, which the raw GitHub tables do not hold.

Some projects also have three materialized views: `engineering_analytics_pr_friction`, `engineering_analytics_ci_runs`, and `engineering_analytics_ci_jobs`.
Use them only after a test query shows they exist.

Never create more warehouse views for this data, and never rewrite in SQL what a view already computes.

## Step 1: find the tables

Table names carry a prefix the user chose, so never hardcode them.
Call `engineering-analytics-sources`.
It returns one entry per repository, with `id`, `repo`, `prefix`, and `synced`.

- A source's original repo uses the plain names, such as `<prefix>github_pull_requests`.
- Every other repo of the same source has a repo-qualified table name. The tool's description gives the naming rule.
- With several entries, ask which repo the user means.

The views cover every GitHub source of the project.
Filter `repo_owner` and `repo_name` on the two job views, or `repo` on `engineering_analytics_ci_failures`, to keep one repo.

## Step 2: write the HogQL

First check whether a view already answers the question.

The raw tables hold GitHub's JSON as strings, so a plain `SELECT` gets the rules wrong.
Copy the base subqueries from [references/hogql-recipes.md](references/hogql-recipes.md) and follow these rules:

- Timestamps are strings. Wrap each in `parseDateTimeBestEffort` before you compare or subtract.
- JSON columns are Nullable. Wrap each in `ifNull` before `JSONExtractArrayRaw` or `splitByChar`.
- Attribute a CI run to a PR by PR number, from the run's own PR association. A head SHA join drops every push except the latest.
- Exclude bots and drafts from throughput and merge-time metrics.
- `merged_at` minus `created_at` is `open_to_merge_seconds`. It includes draft time, so never title an insight "cycle time" or "review time".
- Compute success rates over `status = 'completed'` rows. A run's conclusion arrives by webhook and can lag.
- Join reviews to PRs on `pr_number`.
- Attribute PRs to a team with `author_handle IN (SELECT ...)` over the team members table. A plain join double-counts authors who belong to several teams.
- On the two job views, bound `created_at` and add a string floor such as `created_at_raw >= '<YYYY-MM-DD>'`. The floor lets the scan skip old data.

Test the query with the `execute-sql` tool before you save anything.

## Step 3: save the insight

Call `insight-create` with a SQL insight:

```json
{
  "name": "Weekly PR open to merge time (hours)",
  "query": {
    "kind": "DataVisualizationNode",
    "source": { "kind": "HogQLQuery", "query": "<tested SQL>" }
  }
}
```

- If you are unsure of the chart type, save the table and link the insight so the user picks one.
- Put a relative window in the SQL, such as `>= now() - INTERVAL 90 DAY`. Tell the user that dashboard date filters will not change it.
- Use `dashboard-create` to group several insights.

## Step 4: subscribe

Follow the `managing-subscriptions` skill for the `subscriptions-create` payload, channels, and frequency.

Alerts support only trends insights, so a SQL insight cannot have one.
For "notify me when X", offer a scheduled subscription, or a threshold check in an AI subscription.

## What stays on the MCP tools

Flaky-test ranking, broken-test classification, team CI health, and failure-log thinning apply rules that live in product code.
Do not copy them into SQL.
For a recurring report on those, create an AI subscription with the `creating-ai-subscription` skill.
Have its prompt call `engineering-analytics-flaky-tests`, `engineering-analytics-broken-tests`, or `engineering-analytics-team-ci-health`.

For cost, query the `engineering_analytics_job_costs` view, which runs the same cost query as the cost tools.
Never compute dollar cost from runner labels yourself.

## Caveats to write into the insight description

- Say whether the insight excludes bots and drafts.
- A null `estimated_cost_usd` means the job was not billable or has not finished. It never means zero.
- `engineering_analytics_ci_failures` holds pytest failures only and no passing runs, so its counts are absolute and never rates.
- Never build a ranking of authors or reviewers. For a team split, use the team membership filter and return team aggregates only.
