---
name: turning-engineering-analytics-into-insights
description: >
  Converts engineering analytics (PR / CI) data into saved PostHog insights, dashboards, and subscriptions, and
  explains what data the product reads so it can be queried directly with SQL. The engineering analytics dashboard
  and MCP tools run curated HogQL privately over per-team GitHub warehouse tables; this skill teaches discovering
  those tables via engineering-analytics-sources, replicating the curated column semantics in HogQL, reading the
  exposed engineering_analytics_* warehouse views where product logic is involved (CI cost, fingerprinted failure
  lines, commit attribution), saving the query with insight-create, and scheduling delivery with
  subscriptions-create. Use when asked to "save this as an insight", "put CI health / merge times on a dashboard",
  "email me PR throughput weekly", "chart CI cost", "track time to first review", "subscribe to these numbers",
  "alert on CI success rate", or "what data/tables/views does engineering analytics read". For ad-hoc CI and merge
  questions use diagnosing-ci-and-merge-bottlenecks; to investigate one specific CI failure use
  investigating-ci-failures.
---

# Turning engineering analytics into insights and subscriptions

The engineering analytics dashboard and MCP tools (`pull-requests`, `workflow-health`, `pr-lifecycle`, `engineering-analytics-broken-tests`, …)
run curated HogQL privately: nothing in the UI or the tool output names the underlying tables,
and the endpoints cannot themselves be saved as insights or subscribed to.
The data, however, is queryable directly, through two substrates:

- **Raw warehouse tables** — `<prefix>github_pull_requests`, `<prefix>github_workflow_runs`,
  `<prefix>github_workflow_jobs`, `<prefix>github_reviews`, and `<prefix>github_teams` /
  `<prefix>github_team_members` (org team membership — the author→team map) — ordinary team-scoped tables you query with HogQL.
- **Three curated warehouse views** with fixed names — `engineering_analytics_job_costs`,
  `engineering_analytics_ci_job_history`, `engineering_analytics_ci_failures` — provisioned per team from the
  connected GitHub source(s).
  Non-materialized: computed at query time, always current, and they back insights and subscriptions like any table.

The views exist for exactly one reason: they render **product code** into SQL — the runner-tier cost model, the
failure-fingerprint recipe, the jobs↔runs commit-attribution rules — logic that would silently drift if hand-rolled,
re-rendered into the team's view whenever the code changes. Everything else is just table data, and **pure HogQL over
the raw tables is always enough**: never create additional warehouse views for engineering analytics data, and never
re-derive in SQL what the three views already encode.

| What the product shows                                      | Where the data actually lives                                                        | Can it back an insight?                        |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------------- |
| PR list, merge times, CI status, workflow health            | Data warehouse tables `<prefix>github_pull_requests`, `<prefix>github_workflow_runs` | **Yes** (SQL insight over the tables)          |
| Reviews and approvals                                       | `<prefix>github_reviews`                                                             | **Yes**                                        |
| Team-level PR metrics (author→team attribution)             | `<prefix>github_team_members` semi-joined against the PR authors                     | **Yes** (team aggregates only)                 |
| Job durations, queue times, runner tiers                    | `<prefix>github_workflow_jobs`                                                       | **Yes**                                        |
| CI cost (runner-tier price ladder)                          | `engineering_analytics_job_costs` view                                               | **Yes** (query the view, never recompute cost) |
| Per-job CI history with commit attribution                  | `engineering_analytics_ci_job_history` view                                          | **Yes**                                        |
| Grouped (fingerprinted) CI failure lines                    | `engineering_analytics_ci_failures` view (reads the Logs product, short retention)   | **Yes**, for short recent windows              |
| Thinned CI failure logs for a PR or run                     | Logs product (`service_name = 'github-ci-logs'`) + thinning logic                    | No (use the MCP tools ad hoc)                  |
| Flaky-test leaderboard, broken-tests triage, team CI health | CI trace spans + ranking/classification logic in product code                        | No (use the MCP tools ad hoc)                  |

So the job splits cleanly:
warehouse-backed metrics (raw tables or the three views) become SQL insights (then dashboards, then subscriptions);
everything computed by product logic at request time stays on the MCP tools, delivered recurringly via an AI subscription if needed.

## Step 1: discover the team's tables

Warehouse table names carry a user-chosen prefix, so never hardcode them.
Call the `engineering-analytics-sources` MCP tool: each connected GitHub source returns its `id`, `repo`, and `prefix`.
The tables are `<prefix>github_pull_requests`, `<prefix>github_workflow_runs`, `<prefix>github_workflow_jobs`, `<prefix>github_reviews`, and `<prefix>github_teams` / `<prefix>github_team_members`;
an empty prefix means the plain `github_*` names.
With multiple sources, ask which repo the user means; each source is one repo.

The three `engineering_analytics_*` views need no discovery: their names are fixed (no prefix), and each unions every
connected source, carrying `repo_owner` / `repo_name` columns (`repo` on `ci_failures`) to filter down to one repo.

## Step 2: write HogQL that carries the curated semantics

First check whether one of the three views already answers the question — cost, per-job history and commit
attribution, fingerprinted failure lines — and query it directly; the rules below are for the raw tables.

The raw tables land GitHub's JSON verbatim, so a naive `SELECT` gets the domain rules wrong.
Copy the base subqueries from [references/hogql-recipes.md](references/hogql-recipes.md) (they mirror the product's own curated builders) and follow these rules:

- **Timestamps are strings.** Always `parseDateTimeBestEffort(created_at)` etc. before comparing or diffing.
- **Nested JSON is Nullable.** `ifNull(...)`-unwrap before `JSONExtractArrayRaw` / `splitByChar`: ClickHouse rejects an Array inside a Nullable.
- **CI ↔ PR attribution is by PR number** (the run's `pull_requests` association), never by head SHA: the PR snapshot keeps only the current head, so a SHA join silently drops every push but the latest. head SHA is only for a PR's _current_ CI status (latest run per `(head_sha, workflow_name)`).
- **Bot detection**: `author_handle LIKE '%[bot]' OR author_handle IN ('dependabot', 'github-actions', 'posthog-bot', 'renovate')`. Exclude bots and drafts from throughput / merge-time metrics by default.
- **Honest names.** `merged_at - created_at` is `open_to_merge_seconds` (it fuses draft and review time); never label an insight "cycle time" or "review time".
- **Conclusions can be stale.** The runs sync watermarks on `created_at`; a run that completes late can show a stale conclusion. Compute rates over `status = 'completed'` rows only.
- **Reviews join by `pr_number`.** In `github_reviews`, `state` is `APPROVED` / `CHANGES_REQUESTED` / `COMMENTED` / `DISMISSED` (pending drafts are dropped at sync), and the injected `pr_number` joins to the PR table's `number`.
- **Author→team attribution is a membership semi-join.** Filter `author_handle IN (SELECT member_handle FROM …)` against `github_team_members` (see the team recipe) — the shape the product's own team merge trend uses. A person can belong to several GitHub teams, so a plain JOIN would double-count their PRs across teams; and only team-level aggregates leave the query, never per-member figures.

Test the query with the `execute-sql` MCP tool (or the SQL editor) before saving anything.

## Step 3: save it as an insight

Use `insight-create` with a SQL insight:

```json
{
  "name": "Weekly PR open→merge time (hours)",
  "query": {
    "kind": "DataVisualizationNode",
    "source": { "kind": "HogQLQuery", "query": "<tested SQL>" }
  }
}
```

`display` (a `ChartDisplayType`, e.g. `ActionsLineGraph`) and `chartSettings` (`xAxis` / `yAxis` columns) turn the table into a chart;
when unsure, save it and let the user pick the visualization in the UI, linking the returned insight URL.
Bake a relative window into the SQL (`>= now() - INTERVAL 90 DAY`);
note that a hard-coded date filter means dashboard date overrides won't apply to this tile.
Bundle several insights with `dashboard-create`.

## Step 4: subscribe

With the insight (or dashboard) saved, this is standard subscription territory: follow the `managing-subscriptions` skill for the `subscriptions-create` payload, channels, frequency, and AI-summary options.

For "notify me when X" (a condition, not a schedule): alerts require a trends insight, so a SQL insight can't be alerted today.
Offer a scheduled subscription instead, or a threshold check inside a prompt-kind AI subscription.

## What NOT to rebuild in SQL

The **flaky-test ranking**, **broken-tests classification**, **team CI health rollup**, and **failure-log thinning** are product logic over data an insight can't reach (CI trace spans, raw log bodies);
hand-rolled SQL versions will silently drift from what the dashboard shows.
For a recurring report on those, create a prompt-kind AI subscription (see the `creating-ai-subscription` skill) whose prompt asks for the relevant engineering analytics reading each period,
or just call the MCP tools (`engineering-analytics-flaky-tests`, `engineering-analytics-broken-tests`, `engineering-analytics-team-ci-health`, `engineering-analytics-ci-failure-logs`, `engineering-analytics-run-failure-logs`) ad hoc.

CI **cost** is not on that list because its product logic is rendered into the
`engineering_analytics_job_costs` view (parity-tested against the product's own model, re-rendered when the model
changes), so cost insights are plain SQL over the view — and the cost MCP tools (`engineering-analytics-pr-cost`,
`engineering-analytics-workflow-runner-costs`) read that same rendered SELECT, so the numbers agree. Still: never
recompute dollar cost from runner labels yourself.

## Caveats to carry into every insight

Name these in the insight description so future readers inherit them:
`open_to_merge_seconds` is coarse (draft + review fused);
CI conclusions can lag until the run's webhook settles;
`estimated_cost_usd` NULL means non-billable or still running, never zero — disambiguate via `provider` vs `completed_at`;
`ci_failures` is pytest-only and failure-only, so its counts are absolute signal, never rates;
bots and drafts are excluded (or not: say which).
And never build per-author leaderboards or cross-author rankings; per-developer surveillance is an explicit product non-goal.
When a team-level split is wanted, group through the `github_team_members` membership semi-join instead.
