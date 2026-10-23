# Query reference index

## Data Schema

- [Customer analytics tasks (`system.customer_tasks`)](./models-customer-tasks.md)

Schema reference for PostHog's core system models, organized by domain.

Every column table below is generated from the live HogQL catalog, so it lists exactly what `execute-sql` resolves. `system.*` tables expose a curated subset of each Django model, so a field returned by a REST tool such as `insight-get` is not necessarily queryable — trust these tables over the REST response shape.

- [Activity logs](./models-activity-logs.md)
- [Actions](./models-actions.md)
- [Alerts](./models-alerts.md)
- [Annotations](./models-annotations.md)
- [Autoresearch](./models-autoresearch.md)
- [APM / tracing (`posthog.trace_spans`)](./models-apm-spans.md)
- [Batch exports](./models-batch-exports.md)
- [Early Access Features](./models-early-access-features.md)
- [Cohorts & Persons](./models-cohorts.md)
- [Customer analytics accounts, relationships, custom properties & feature requests (`system.accounts`, `system.feature_requests`)](./models-customer-analytics.md)
- [Dashboards, Tiles & Insights](./models-dashboards-insights.md)
- [Data Warehouse](./models-data-warehouse.md)
- [Data Modeling Endpoints](./models-endpoints.md)
- [Error Tracking](./models-error-tracking.md)
- [Flags & Experiments](./models-flags-experiments.md)
- [Heatmaps (`heatmaps` data + `system.heatmaps_saved`)](./models-heatmaps.md)
- [Hog Flows](./models-hog-flows.md)
- [Hog Functions](./models-hog-functions.md)
- [Integrations](./models-integrations.md)
- [AI observability events (`posthog.ai_events`)](./models-ai-observability-events.md)
- [AI observability evaluations](./models-ai-observability-evaluations.md)
- [AI observability reviews](./models-ai-observability-reviews.md)
- [AI observability datasets](./models-datasets.md)
- [Logs (`logs` data plane + saved views and alerts)](./models-logs.md)
- [MCP analytics (`$mcp_tool_call` events)](./models-mcp.md)
- [Messaging opt-outs (`system.message_recipient_preferences`, `system.message_categories`)](./models-messaging-opt-outs.md)
- [Metrics (`posthog.metrics`)](./models-metrics.md)
- [Notebooks](./models-notebooks.md)
- [Session Recording Playlists](./models-session-recording-playlists.md)
- [Session Recordings](./models-session-recordings.md)
- [Replay Vision scanners](./models-replay-vision.md)
- [Support Tickets](./models-support-tickets.md)
- [Surveys](./models-surveys.md)
- [Usage Metrics](./models-usage-metrics.md)
- [SQL Variables](./models-variables.md)
- [Skipped events in the read-data-schema tool](./taxonomy-skipped-events.md)
- [Dynamic person and event properties](./taxonomy-dynamic-properties.md) — patterns like `$survey_dismissed/{id}`, `$feature/{key}` that don't appear in tool results

## HogQL References

- [Person property modes (event-time vs query-time)](./person-property-modes.md). Read when working with `person.properties.*` to understand if values are historical or current.
- [Sparkline, SemVer, Session replays, Actions, Translation, HTML tags and links, Text effects, and more](./hogql-extensions.md)
- [SQL variables](./models-variables.md).
- [Available functions in HogQL](./available-functions.md). IMPORTANT: the list is long, so read data using bash commands like grep.

## Analytics Query Examples

These references include a direct typed-query example and SQL examples for analytics and data inspection. Choose the method before adapting an example. An example's format does not require you to use that method for every similar question.

- [Trends (unique users, specific time range, single series)](./example-trends-unique-users.md)
- [Trends (total count with multiple breakdowns)](./example-trends-breakdowns.md)
- [Funnel (two steps, aggregated by unique users, broken down by the person's role, sequential, 14-day conversion window)](./example-funnel-breakdown.md)
- [Conversion trends (funnel, two steps, aggregated by unique groups, 1-day conversion window)](./example-funnel-trends.md)
- [Retention (unique users, returned to perform an event in the next 12 weeks, recurring)](./example-retention.md)
- [User paths (pageviews, three steps, applied path cleaning and filters, maximum 50 paths)](./example-paths.md)
- [Lifecycle (unique users by pageviews)](./example-lifecycle.md)
- [Stickiness (counted by pageviews from unique users, defined by at least one event for the interval, non-cumulative)](./example-stickiness.md)
- [LLM trace (generations, spans, embeddings, human feedback, captured AI metrics)](./example-llm-trace.md)
- [LLM traces list (searching and listing traces with property filters, two-phase query)](./example-llm-traces-list.md)
- [Web path stats (paths, visitors, views, bounce rate)](./example-web-path-stats.md)
- [Web traffic channels (direct, organic search, etc)](./example-web-traffic-channels.md)
- [Web views by devices](./example-web-traffic-by-device-type.md)
- [Web overview](./example-web-overview.md)
- [Error tracking (search for a value in an error and filtering by custom properties)](./example-error-tracking.md)
- [Logs (filtering by severity and searching for a term)](./example-logs.md)
- [Cross-signal correlation (metric exemplar → trace → logs)](./example-observability-correlation.md)
- [Sessions (listing sessions with duration, pageviews, and bounce rate)](./example-sessions.md)
- [Session replay (listing recordings with activity filters)](./example-session-replay.md)
- [Team taxonomy (top events by count, paginated)](./example-team-taxonomy.md)
- [Event taxonomy (properties of an event, with sample values)](./example-event-taxonomy.md)
- [Person property taxonomy (sample values for person properties)](./example-person-property-taxonomy.md)
