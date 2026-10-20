# Charting the metrics this scout records

Every run of this scout records its numbers as `$scout_structured_output` events (see the
**Record metrics** step in `SKILL.md`). This file is how you turn them into a dashboard. Nothing
here is part of a run — it is for whoever wants to watch the series.

Two filters belong on every query:

- `properties.skill_name = 'signals-scout-mcp-tool-calls'` — the event is shared with every other
  scout that records output.
- `properties.output_mcp_metrics_version = '1'` — definitions change; charts should not silently
  mix two of them. Raise this when the scout bumps the version.

Each record's scalar fields arrive flattened as `output_<field>` properties, so no JSON access is
needed. The two record kinds are told apart by `output_mcp_record_kind`.

**Every record is a rolling seven-day snapshot, and the scout runs more than once a day.** Summing
`calls` or `problem_tools` across a day adds the same window to itself once per run. Take the latest
snapshot of the day with `argMax(..., timestamp)`, or average, and label it.

**Plot the recorded rate, never a count of records.** A trend that counts `$scout_structured_output`
events broken down by category answers "how many times did the scout write about this category",
which is one per run and tells you nothing. The rate is a value in a property, so it needs an
aggregation over that property — `avg(output_mcp_error_rate_pct)`, not `count()`.

## 1. Error rate and struggle share per category over time

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    toString(properties.output_mcp_category) AS category,
    avg(toFloat(properties.output_mcp_error_rate_pct)) AS error_rate_pct,
    avg(toFloat(properties.output_mcp_struggle_session_pct)) AS struggle_session_pct,
    argMax(toInt(properties.output_mcp_calls), timestamp) AS calls
FROM events
WHERE event = '$scout_structured_output'
    AND properties.skill_name = 'signals-scout-mcp-tool-calls'
    AND properties.output_mcp_metrics_version = '1'
    AND properties.output_mcp_record_kind = 'category_rollup'
    AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY day, category
ORDER BY day DESC, calls DESC
```

`struggle_session_pct` is null for a category whose calls carry no session id, and `avg` skips
nulls, so those points are gaps rather than false zeroes. `calls` rides along as the weight: a category's
rate on a hundred calls is not comparable to one on fifty thousand. Filter `category = 'all'` for
the project-wide baseline on its own.

## 2. Session share per tool per source

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    toString(properties.output_mcp_source) AS source,
    toString(properties.output_mcp_tool) AS tool,
    avg(toFloat(properties.output_mcp_session_share_pct)) AS session_share_pct,
    avg(toFloat(properties.output_mcp_share_pct_prior_window)) AS share_pct_prior_window,
    avg(toFloat(properties.output_mcp_calls_per_session)) AS calls_per_session
FROM events
WHERE event = '$scout_structured_output'
    AND properties.skill_name = 'signals-scout-mcp-tool-calls'
    AND properties.output_mcp_metrics_version = '1'
    AND properties.output_mcp_record_kind = 'tool_session_share'
    AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY day, source, tool
ORDER BY day DESC, session_share_pct DESC
```

Add `AND properties.output_mcp_tool = '<tool>'` to watch one tool.

### Alerting on a step change for a named tool

The jump is the shape that matters, not the level, so alert on the difference between the current
share and the prior-window share the scout recorded next to it. Compute the delta in SQL and save
it as a single-series insight, then put a threshold alert on that series:

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    avg(toFloat(properties.output_mcp_session_share_pct) - toFloat(properties.output_mcp_share_pct_prior_window)) AS share_delta_pct
FROM events
WHERE event = '$scout_structured_output'
    AND properties.skill_name = 'signals-scout-mcp-tool-calls'
    AND properties.output_mcp_metrics_version = '1'
    AND properties.output_mcp_record_kind = 'tool_session_share'
    AND properties.output_mcp_source = '<source>'
    AND properties.output_mcp_tool = '<tool>'
    AND isNotNull(properties.output_mcp_share_pct_prior_window)
    AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY day
ORDER BY day DESC
```

The null filter drops runs where the prior window had too few sessions to be a baseline, so a
surface a team is only starting to use does not alert on every tool. Pick the threshold from the
tool's own history rather than a round number: a tool that has sat at 30% for a month should
alert on a jump of twenty points, not on crossing 90%. A trends insight with two series and the
formula `A - B` does the same job if you prefer the UI, with series A on the current share and
series B on the prior share.

## 3. Problem tools and what the scout decided

```sql
SELECT
    toStartOfDay(timestamp) AS day,
    toString(properties.output_mcp_category) AS category,
    toString(properties.output_mcp_report_action) AS report_action,
    argMax(toInt(properties.output_mcp_problem_tools), timestamp) AS problem_tools
FROM events
WHERE event = '$scout_structured_output'
    AND properties.skill_name = 'signals-scout-mcp-tool-calls'
    AND properties.output_mcp_metrics_version = '1'
    AND properties.output_mcp_record_kind = 'category_rollup'
    AND properties.output_mcp_category != 'all'
    AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY day, category, report_action
ORDER BY day DESC, problem_tools DESC
```

This is the tile that makes the scout auditable: the problem-tool count next to what it did about
it. A category with problem tools and a long run of `below_bar` means the bar is set wrong, or the
tools are chronically noisy and the scout is right to hold. A run of `skipped_live_report` means a
report has been open a while and nobody has acted on it.

For the decision mix on its own, break `count()` down by `output_mcp_report_action` — here the
count is the measure, because each record is one decision.
