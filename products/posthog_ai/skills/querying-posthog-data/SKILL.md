---
name: querying-posthog-data
description: >
  Queries PostHog with HogQL/SQL, finds entities, and inspects warehouse,
  web analytics, errors, logs, sessions, and LLM data. Use before writing
  HogQL/SQL or calling execute-sql. Covers custom calculations, joins,
  schemas, functions, and the semantic-layer workflow for governed measures.
  For event trends, conversion funnels, and retention, use the focused
  query-trends, query-funnel, or query-retention skill instead.
---

# Querying data in PostHog

## Choose the focused skill

- Event counts, time series, several metrics, and scorecards: read `query-trends` before `posthog:query-trends`.
- Conversion and step drop-off: read `query-funnel` before `posthog:query-funnel`.
- Cohorts and returning users: read `query-retention` before `posthog:query-retention`.

## Important

- Use a typed runner when it supports the requested product analytics calculation. Use SQL for custom joins, record inspection, entity discovery, existing SQL, or a request for SQL.
- For a governed measure, check for a matching approved metric before calculating it. Follow the [semantic-layer workflow](./references/query-workflow.md).
- Use a chart and concise findings for time series and comparisons. Include a supporting table when exact values help, and honor explicit table requests. Save an insight only when the user asks.

## Query workflow and references

1. Read the [query workflow](./references/query-workflow.md) for tool selection, metric definitions, and entity discovery.
2. For SQL, read the [guidelines](./references/guidelines.md). Use the [reference index](./references/query-reference-index.md) to find schemas, functions, and examples for the task.
3. Follow the [result format](./references/presenting-results.md) for lifecycle, paths, stickiness, SQL, and other query paths. The focused skills contain the result format for trends, funnels, and retention.
