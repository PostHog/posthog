---
name: turning-engineering-analytics-into-insights
description: >
  Converts engineering analytics (PR / CI) data into saved PostHog insights, dashboards, and subscriptions, and
  explains what data the product reads so it can be queried directly with SQL. The engineering analytics dashboard
  and MCP tools run curated HogQL privately over per-team GitHub warehouse tables — this skill teaches discovering
  those tables via engineering-analytics-sources, replicating the curated column semantics in HogQL, saving the
  query with insight-create, and scheduling delivery with subscriptions-create. Use when asked to "save this as an
  insight", "put CI health / merge times on a dashboard", "email me PR throughput weekly", "subscribe to these
  numbers", "alert on CI success rate", or "what data/tables does engineering analytics read". For ad-hoc CI and
  merge questions use diagnosing-ci-and-merge-bottlenecks instead.
---

# Turning engineering analytics into insights and subscriptions

The engineering analytics dashboard and MCP tools (`pull-requests`, `workflow-health`, `pr-lifecycle`, …)
run curated HogQL privately — nothing in the UI or the tool output names the underlying tables,
and the endpoints cannot themselves be saved as insights or subscribed to.
The data, however, lives in ordinary team-scoped sources you can query yourself:

| What the product shows                           | Where the data actually lives                                                        | Can it back an insight?               |
| ------------------------------------------------ | ------------------------------------------------------------------------------------ | ------------------------------------- |
| PR list, merge times, CI status, workflow health | Data warehouse tables `<prefix>github_pull_requests`, `<prefix>github_workflow_runs` | **Yes** — SQL insight over the tables |
| Job durations, runner tiers, CI cost             | `<prefix>github_workflow_jobs` (optional; plus a cost model in product code)         | Partially — durations yes, cost no    |
| CI failure logs for a PR                         | Logs product (`service_name = 'github-ci-logs'`), short retention                    | No — use the MCP tool ad hoc          |
| Flaky test leaderboard                           | CI trace spans + ranking logic in product code                                       | No — use the MCP tool ad hoc          |

So the job splits cleanly:
warehouse-backed metrics become SQL insights (then dashboards, then subscriptions);
everything computed by product logic stays on the MCP tools, delivered recurringly via an AI subscription if needed.

## Step 1 — discover the team's tables

Warehouse table names carry a user-chosen prefix, so never hardcode them.
Call the `engineering-analytics-sources` MCP tool: each connected GitHub source returns its `id`, `repo`, and `prefix`.
The tables are `<prefix>github_pull_requests`, `<prefix>github_workflow_runs`, and (when the job-level sync is enabled) `<prefix>github_workflow_jobs` —
an empty prefix means the plain `github_*` names.
With multiple sources, ask which repo the user means; each source is one repo.

## Step 2 — write HogQL that carries the curated semantics

The raw tables land GitHub's JSON verbatim, so a naive `SELECT` gets the domain rules wrong.
Copy the base subqueries from [references/hogql-recipes.md](references/hogql-recipes.md) — they mirror the product's own curated builders — and follow these rules:

- **Timestamps are strings.** Always `parseDateTimeBestEffort(created_at)` etc. before comparing or diffing.
- **Nested JSON is Nullable.** `ifNull(...)`-unwrap before `JSONExtractArrayRaw` / `splitByChar` — ClickHouse rejects an Array inside a Nullable.
- **CI ↔ PR attribution is by PR number** (the run's `pull_requests` association), never by head SHA — the PR snapshot keeps only the current head, so a SHA join silently drops every push but the latest. head SHA is only for a PR's _current_ CI status (latest run per `(head_sha, workflow_name)`).
- **Bot detection**: `author_handle LIKE '%[bot]' OR author_handle IN ('dependabot', 'github-actions', 'posthog-bot', 'renovate')`. Exclude bots and drafts from throughput / merge-time metrics by default.
- **Honest names.** `merged_at - created_at` is `open_to_merge_seconds` (it fuses draft and review time) — never label an insight "cycle time" or "review time".
- **Conclusions can be stale.** The runs sync watermarks on `created_at`; a run that completes late can show a stale conclusion. Compute rates over `status = 'completed'` rows only.

Test the query with the `execute-sql` MCP tool (or the SQL editor) before saving anything.

## Step 3 — save it as an insight

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
when unsure, save it and let the user pick the visualization in the UI — link the returned insight URL.
Bake a relative window into the SQL (`>= now() - INTERVAL 90 DAY`);
note that a hard-coded date filter means dashboard date overrides won't apply to this tile.
Bundle several insights with `dashboard-create`.

## Step 4 — subscribe

With the insight (or dashboard) saved, this is standard subscription territory — follow the `managing-subscriptions` skill for the `subscriptions-create` payload, channels, frequency, and AI-summary options.

For "notify me when X" (a condition, not a schedule): alerts require a trends insight, so a SQL insight can't be alerted today.
Offer a scheduled subscription instead, or a threshold check inside a prompt-kind AI subscription.

## What NOT to rebuild in SQL

CI **cost** (runner-tier price ladder), the **flaky-test ranking**, and **failure-log thinning** are product logic, not table columns —
hand-rolled SQL versions will silently drift from what the dashboard shows.
For a recurring report on those, create a prompt-kind AI subscription (see the `creating-ai-subscription` skill) whose prompt asks for the relevant engineering analytics reading each period,
or just call the MCP tools (`engineering-analytics-pr-cost`, `engineering-analytics-flaky-tests`, `engineering-analytics-ci-failure-logs`) ad hoc.

## Caveats to carry into every insight

Name these in the insight description so future readers inherit them:
`open_to_merge_seconds` is coarse (draft + review fused);
CI conclusions can lag until the run's webhook settles;
reviews, approvals, and deploys are not in the data yet;
bots and drafts are excluded (or not — say which).
And never build per-author leaderboards or cross-author rankings — per-developer surveillance is an explicit product non-goal.
