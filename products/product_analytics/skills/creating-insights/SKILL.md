---
name: creating-insights
description: >
  Answers product analytics questions and creates insights with PostHog's typed query runners
  (query-trends, query-funnel, query-retention, query-stickiness, query-lifecycle, query-paths)
  instead of SQL. Use before you query events to count, compare, or chart anything: how many,
  how often, unique users, change over time, top values, averages or percentiles of a property,
  conversion, drop-off, retention, or engagement. Also use before you create or update an insight
  with insight-create or insight-update, including the insights on a dashboard. Covers what the
  runners can compute (custom aggregations, formulas, HogQL filters and breakdowns), when SQL is
  the right tool instead, and how to save a SQL insight as a chart rather than a table.
---

# Creating insights

The typed runners compute trends, funnels, retention, stickiness, lifecycle, and paths with PostHog's own rules:
test-account filtering, merged persons, conversion windows, and the project's timezone.
Their results show as interactive charts, and a saved one opens in the insight editor, where a person can change it.
SQL gives you none of this.
Use a runner whenever one can answer the question, for a one-off answer as much as for a saved insight.

## Pick the runner

| Question                                                                         | Runner             |
| -------------------------------------------------------------------------------- | ------------------ |
| How many, how often, how much, change over time, against last period, top values | `query-trends`     |
| Conversion between steps, drop-off, time to convert, conversion over time        | `query-funnel`     |
| Whether people come back                                                         | `query-retention`  |
| How many days in a period people do something                                    | `query-stickiness` |
| New, returning, resurrecting, and dormant users                                  | `query-lifecycle`  |
| What people do before or after an event                                          | `query-paths`      |

Each runner's description has worked examples. Read it with `info` before you build the query.

## Runners cover more than they seem to

Most questions that look like they need SQL fit `query-trends`:

- Unique users, weekly or monthly actives, unique sessions, first-time users: `math` set to `dau`, `weekly_active`, `monthly_active`, `unique_session`, or `first_time_for_user`.
- Sum, average, median, or percentile of a property: `math` set to `sum`, `avg`, `median`, `p90`, `p95`, or `p99`, with `math_property`.
- Events per user: `avg_count_per_actor`, `median_count_per_actor`, and the percentile variants.
- Any other aggregation: `math: "hogql"` with an expression in `math_hogql`, for example `countIf(toFloat(properties.duration) > 30)`.
- A rate between two series: `trendsFilter.formulaNodes` with a formula such as `A / B`, and `aggregationAxisFormat: "percentage_scaled"`.
- Leaving out internal users: `filterTestAccounts: true` applies the project's own test-account filters.
- A condition no property filter expresses: a property filter with `type: "hogql"` and a boolean expression as its `key`.
- Grouping by a derived value, such as an email domain: a breakdown with `type: "hogql"`.
- Counting accounts instead of people: `aggregation_group_type_index` for the group type.
- Top values, not a time series: a breakdown with `breakdown_limit` and the `ActionsBarValue` display.
- One number: the `Metric` display, with `compareFilter.compare: true` to show the change from the previous period.
- Against the same time last week: `compareFilter.compare_to: "-1w"`, with `interval: "hour"` for an hourly view.

A recurring report, digest, or monitor does not need stored SQL.
Save the insight once, then read it with `insight-query` on each run.

## Edit the answer in the same runner

When the person changes the last answer, change the same query and run it again.
Rewriting it in SQL loses the chart and the editable insight, and the edits below all fit a runner:

- Exclude a value, such as the homepage: a property filter with `is_not`, for example `$pathname` is not `/`.
- A number threshold, such as files under 1 GB: `lt` or `gt` on the property.
- Internal users: `filterTestAccounts: true`.
- A cohort: a property filter with `type: "cohort"` and the cohort's id.
- A group property, such as the account's plan: a property filter with `type: "group"` and the `group_type_index`.
- How old a person's account is: a HogQL filter such as `person.created_at < now() - INTERVAL 7 DAY`.
- Another window or interval: `dateRange` and `interval`.
- Another split or line: `breakdownFilter`, or another series.
- Another chart: the display setting.

Move to SQL only for an edit the runner can't express, and say which part needed it.

Checking a result does not need SQL either:

- To check a filter, run the same query with a breakdown on the property you filtered on.
- For the counts behind a funnel's conversion over time, run `query-trends` on each step's event with the same filters and interval, counting unique users.

## When SQL is the right tool

- Finding PostHog entities in `system.*` tables, or reading the schema.
- Logs, error tracking, LLM traces, and data warehouse tables, where no dedicated tool covers the question.
- Joins between tables or sources, and window functions over results.
- Reading raw rows to check what an event or property holds.
- The person asks for SQL, or an existing SQL query already fits.

These are not reasons to use SQL: knowing SQL better, an example written in SQL, having used SQL to find the event, or wanting a table.
When SQL is the right tool, the `querying-posthog-data` skill covers how to write it.

## Save the insight

- Run the query and read the result first. Then save the same query with `insight-create`. A bare `TrendsQuery` that you just ran is accepted.
- A SQL insight without a `display` saves as a table. Give it a chart that fits its columns: a line over a time column, bars per category, or `BoldNumber` or `Metric` for one value. Keep a table only when a person reads the rows, such as a list of accounts.
- For a dashboard, the `building-a-dashboard` skill covers which insights to build and how to lay them out. Build each new tile with this skill.
