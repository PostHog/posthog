---
name: query-examples
description: 'HogQL query examples and reference material for PostHog data. Read when writing SQL queries to find patterns for analytics (trends, funnels, retention, lifecycle, paths, stickiness, web analytics, error tracking, logs, sessions, LLM traces) and system data (insights, dashboards, cohorts, feature flags, experiments, surveys, hog flows, data warehouse). Includes HogQL syntax differences, system model schemas, and available functions.'
---

# Querying data in PostHog

If the MCP server haven't provided instructions on querying data in PostHog, read the [guidelines](./references/guidelines.md).

## Data Schema

Schema reference for PostHog's core system models, organized by domain:

- [Activity logs](./references/models-activity-logs.md)
- [Actions](./references/models-actions.md)
- [Alerts](./references/models-alerts.md)
- [Annotations](./references/models-annotations.md)
- [Batch exports](./references/models-batch-exports.md)
- [Early Access Features](./references/models-early-access-features.md)
- [Cohorts & Persons](./references/models-cohorts.md)
- [Dashboards, Tiles & Insights](./references/models-dashboards-insights.md)
- [Data Warehouse](./references/models-data-warehouse.md)
- [Data Modeling Endpoints](./references/models-endpoints.md)
- [Error Tracking](./references/models-error-tracking.md)
- [Flags & Experiments](./references/models-flags-experiments.md)
- [Hog Flows](./references/models-hog-flows.md)
- [Hog Functions](./references/models-hog-functions.md)
- [Integrations](./references/models-integrations.md)
- [Logs](./references/models-logs.md)
- [Notebooks](./references/models-notebooks.md)
- [Session Recording Playlists](./references/models-session-recording-playlists.md)
- [Session Recordings](./references/models-session-recordings.md)
- [Support Tickets](./references/models-support-tickets.md)
- [Surveys](./references/models-surveys.md)
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
- [Sessions (listing sessions with duration, pageviews, and bounce rate)](./references/example-sessions.md)
- [Session replay (listing recordings with activity filters)](./references/example-session-replay.md)
- [Team taxonomy (top events by count, paginated)](./references/example-team-taxonomy.md)
- [Event taxonomy (properties of an event, with sample values)](./references/example-event-taxonomy.md)
- [Person property taxonomy (sample values for person properties)](./references/example-person-property-taxonomy.md)
