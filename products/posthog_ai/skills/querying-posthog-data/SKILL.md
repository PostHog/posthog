---
name: querying-posthog-data
description: 'Required reading before writing any HogQL/SQL or calling execute-sql against PostHog. Use whenever the user wants to search, find, or do complex aggregations PostHog entities (insights, dashboards, cohorts, feature flags, experiments, surveys, hog flows, data warehouse, persons, etc.) and query analytics data (trends, funnels, retention, lifecycle, paths, stickiness, web analytics, error tracking, logs, sessions, LLM traces). Also the first stop for a governed business number (MRR, activation, revenue): check the semantic layer (canonical metrics in system.information_schema.metrics) for an approved definition before deriving from raw events. Covers HogQL syntax differences from ClickHouse SQL, system table schemas (system.*), available functions, query examples, and the schema-discovery workflow.'
---

# Querying data in PostHog

The [guidelines](./references/guidelines.md) contain the same instructions as `posthog:execute-sql`. If you've already read `posthog:execute-sql`, you don't need to read them again.

## When to use this skill

### Finding a specific PostHog entity

When the user wants to find a specific entity created in PostHog (insights, dashboards, cohorts, feature flags, experiments, surveys, hog flows, data warehouse items, etc.), or when a list/search tool returns too many results to narrow down:

1. Read the appropriate schema reference under Data Schema to understand the entity's table and columns.
2. Use `posthog:execute-sql` to query the system table and find the matching entity (typically returning its ID).
3. Use the dedicated read tool for that entity type (e.g. `posthog:insight-get`, `posthog:dashboard-get`) to retrieve the full entity by ID.

Don't try to reconstruct the entity from SQL — `execute-sql` is for discovery, the read tool is for retrieval.

### Querying analytics data

When the user wants analytics data (trends, funnels, retention, paths, sessions, LLM traces, web analytics, errors, logs, etc.) and the existing insight schemas don't fit the request:

1. Look for a matching example under Analytics Query Examples. The list is not exhaustive — there may not be an example for every scenario. If one is a close fit (same domain, similar aggregation), read it; otherwise skip this step.
2. Adapt the example query (if one was found) to the user's request and run it via `posthog:execute-sql`. If no example fit, compose the query from scratch using the Data Schema and HogQL References.

### Answering a headline business number (semantic layer)

When the user asks for a governed business number (MRR, activation rate, active users, ...), check the data catalog's semantic layer before deriving it from raw data — the project may have a canonical, human-approved definition to reuse instead of guessing.

1. Look for a canonical metric with `posthog:execute-sql` (there is no list tool). The table is usually empty; an empty result just means no governed definition exists, so derive the number normally.

   ```sql
   SELECT name, description, status, is_drifted, definition_kind, unit
   FROM system.information_schema.metrics
   WHERE name ILIKE '%mrr%' OR description ILIKE '%revenue%'
   ```

2. If an `approved`, non-drifted metric fits, run it with `posthog:data-catalog-metric-run` and cite the canonical definition instead of re-deriving. A result is canonical only when `status` is `approved` AND `is_drifted` is false — never present a `proposed` or drifted metric's result as authoritative. A `MarkdownDefinition` metric returns calculation steps in `instructions` (with `results` null) for you to follow.

3. If none fits, derive it yourself, but derive it well: prefer `certified` tables/views and avoid `deprecated` ones (the `certification` column on `system.information_schema.tables`), and use accepted joins from `system.information_schema.relationships` rather than guessing join keys.

Curating the catalog — creating or approving metrics, certifying sources, reviewing the proposal queue — is a separate job covered by the `setting-up-data-catalog` skill. If a derivation is worth reusing, or you notice a clearly load-bearing or stale table while deriving, that skill covers proposing it. Everything an agent proposes lands unapproved for a human to promote, so never present a proposal as canonical.

## Data Schema

Schema reference for PostHog's core system models, organized by domain:

- [Activity logs](./references/models-activity-logs.md)
- [Actions](./references/models-actions.md)
- [Alerts](./references/models-alerts.md)
- [Annotations](./references/models-annotations.md)
- [APM / tracing (`posthog.trace_spans`)](./references/models-apm-spans.md)
- [Batch exports](./references/models-batch-exports.md)
- [Early Access Features](./references/models-early-access-features.md)
- [Cohorts & Persons](./references/models-cohorts.md)
- [Customer analytics accounts, relationships (CSM, account owner) & custom properties (`system.accounts`, `system.account_relationships`)](./references/models-customer-analytics.md)
- [Dashboards, Tiles & Insights](./references/models-dashboards-insights.md)
- [Data Warehouse](./references/models-data-warehouse.md)
- [Data Modeling Endpoints](./references/models-endpoints.md)
- [Error Tracking](./references/models-error-tracking.md)
- [Flags & Experiments](./references/models-flags-experiments.md)
- [Heatmaps (`heatmaps` data + `system.heatmaps_saved`)](./references/models-heatmaps.md)
- [Hog Flows](./references/models-hog-flows.md)
- [Hog Functions](./references/models-hog-functions.md)
- [Integrations](./references/models-integrations.md)
- [AI observability events (`posthog.ai_events`)](./references/models-ai-observability-events.md)
- [AI observability reviews](./references/models-ai-observability-reviews.md)
- [Logs (`logs` data plane + saved views and alerts)](./references/models-logs.md)
- [MCP analytics (`$mcp_tool_call` events)](./references/models-mcp.md)
- [Metrics (`posthog.metrics`)](./references/models-metrics.md)
- [Notebooks](./references/models-notebooks.md)
- [Session Recording Playlists](./references/models-session-recording-playlists.md)
- [Session Recordings](./references/models-session-recordings.md)
- [Support Tickets](./references/models-support-tickets.md)
- [Surveys](./references/models-surveys.md)
- [Usage Metrics](./references/models-usage-metrics.md)
- [SQL Variables](./references/models-variables.md)
- [Skipped events in the read-data-schema tool](./references/taxonomy-skipped-events.md)
- [Dynamic person and event properties](./references/taxonomy-dynamic-properties.md) — patterns like `$survey_dismissed/{id}`, `$feature/{key}` that don't appear in tool results

## HogQL References

- [Person property modes (event-time vs query-time)](./references/person-property-modes.md). Read when working with `person.properties.*` to understand if values are historical or current.
- [Sparkline, SemVer, Session replays, Actions, Translation, HTML tags and links, Text effects, and more](./references/hogql-extensions.md)
- [SQL variables](./references/models-variables.md).
- [Available functions in HogQL](./references/available-functions.md). IMPORTANT: the list is long, so read data using bash commands like grep.

## Analytics Query Examples

Use the examples below to create optimized analytical queries.

- [Trends (unique users, specific time range, single series)](./references/example-trends-unique-users.md)
- [Trends (total count with multiple breakdowns)](./references/example-trends-breakdowns.md)
- [Funnel (two steps, aggregated by unique users, broken down by the person's role, sequential, 14-day conversion window)](./references/example-funnel-breakdown.md)
- [Conversion trends (funnel, two steps, aggregated by unique groups, 1-day conversion window)](./references/example-funnel-trends.md)
- [Retention (unique users, returned to perform an event in the next 12 weeks, recurring)](./references/example-retention.md)
- [User paths (pageviews, three steps, applied path cleaning and filters, maximum 50 paths)](./references/example-paths.md)
- [Lifecycle (unique users by pageviews)](./references/example-lifecycle.md)
- [Stickiness (counted by pageviews from unique users, defined by at least one event for the interval, non-cumulative)](./references/example-stickiness.md)
- [LLM trace (generations, spans, embeddings, human feedback, captured AI metrics)](./references/example-llm-trace.md)
- [LLM traces list (searching and listing traces with property filters, two-phase query)](./references/example-llm-traces-list.md)
- [Web path stats (paths, visitors, views, bounce rate)](./references/example-web-path-stats.md)
- [Web traffic channels (direct, organic search, etc)](./references/example-web-traffic-channels.md)
- [Web views by devices](./references/example-web-traffic-by-device-type.md)
- [Web overview](./references/example-web-overview.md)
- [Error tracking (search for a value in an error and filtering by custom properties)](./references/example-error-tracking.md)
- [Logs (filtering by severity and searching for a term)](./references/example-logs.md)
- [Cross-signal correlation (metric exemplar → trace → logs)](./references/example-observability-correlation.md)
- [Sessions (listing sessions with duration, pageviews, and bounce rate)](./references/example-sessions.md)
- [Session replay (listing recordings with activity filters)](./references/example-session-replay.md)
- [Team taxonomy (top events by count, paginated)](./references/example-team-taxonomy.md)
- [Event taxonomy (properties of an event, with sample values)](./references/example-event-taxonomy.md)
- [Person property taxonomy (sample values for person properties)](./references/example-person-property-taxonomy.md)
