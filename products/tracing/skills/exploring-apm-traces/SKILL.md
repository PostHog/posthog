---
name: exploring-apm-traces
description: >
  Investigates distributed application performance using PostHog APM (OpenTelemetry span) data via MCP.
  Use when the user asks about service traces, slow HTTP/database spans, error spans, trace IDs, or span
  attributes — not LLM analytics traces or product logs. Uses posthog:query-apm-spans, posthog:apm-trace-get,
  posthog:apm-sparkline-query, posthog:apm-services-list, posthog:apm-attributes-list, and
  posthog:apm-attribute-values-list. Composes with posthog:query-logs on trace_id for cross-signal triage.
---

# Exploring APM traces (OpenTelemetry spans)

PostHog captures distributed traces from OpenTelemetry. Each trace is a tree of spans representing a request’s path through services.

**Disambiguation:** This skill is for **APM / OpenTelemetry traces**. Do not confuse with **LLM analytics traces** (agent/model `$ai_*` events and LLM observability tools). **Logs** are a separate signal; use `posthog:query-logs` alongside spans when correlating (see below).

## MCP tools

| Tool                                | Purpose                                                                                 |
| ----------------------------------- | --------------------------------------------------------------------------------------- |
| `posthog:query-apm-spans`           | Search and filter spans (parameters under `query`); returns pagination + exemplar hints |
| `posthog:apm-trace-get`             | Fetch spans for a hex `trace_id` (body may set `maxSpans`, default 2000)                |
| `posthog:apm-sparkline-query`       | Time-bucketed span counts per service (aggregates only)                                 |
| `posthog:apm-services-list`         | List distinct service names                                                             |
| `posthog:apm-attributes-list`       | List span or resource attribute keys                                                    |
| `posthog:apm-attribute-values-list` | List values for a specific attribute key                                                |

For aggregates or joins not covered by these tools, `posthog:execute-sql` against HogQL table `posthog.trace_spans` may be appropriate once the schema is confirmed (see MCP v2 / `querying-posthog-data` skill).

## Span data model

| Field            | Description                                                           |
| ---------------- | --------------------------------------------------------------------- |
| `trace_id`       | Hex ID linking spans in one trace                                     |
| `span_id`        | Hex ID for this span                                                  |
| `parent_span_id` | Parent span hex ID (null for root)                                    |
| `name`           | Operation name (e.g. `HTTP GET /api/users`)                           |
| `kind`           | 0=Unspecified, 1=Internal, 2=Server, 3=Client, 4=Producer, 5=Consumer |
| `service_name`   | Emitting service                                                      |
| `status_code`    | 0=Unset, 1=OK, 2=Error                                                |
| `timestamp`      | Start time (ISO 8601)                                                 |
| `end_time`       | End time (ISO 8601)                                                   |
| `duration_nano`  | Duration in nanoseconds                                               |
| `is_root_span`   | Whether this is the trace entry                                       |

### Property filter types (`query.filterGroup`)

- `span` — built-in fields: `trace_id`, `span_id`, `duration`, `name`, `kind`, `status_code`
- `span_attribute` — span-level attributes (e.g. `http.method`)
- `span_resource_attribute` — resource attributes (e.g. Kubernetes labels)

## Workflow: investigate slow requests

1. Discover services: call `posthog:apm-services-list` with `{}` (or applicable filters per tool schema).
2. Find slow spans: `posthog:query-apm-spans` with a `query` that filters by service and `duration` (remember nanoseconds: 1s = 1_000_000_000). Use `exemplarTraceIds.slowest_trace_id` when returned.
3. Drill in: `posthog:apm-trace-get` with path `trace_id` and optional body `{ "maxSpans": 400 }` for large traces (lower token use). If `truncated` is true, increase `maxSpans` (cap 5000) or narrow `dateRange`.

## Workflow: find error traces

Use `posthog:query-apm-spans` with **`query.statusCodes: [2]`** for OpenTelemetry error status, or `query.filterGroup` on span attribute **`http.status_code`** when the question is about HTTP 4xx/5xx. Top-level `statusCodes` is **not** HTTP status.

## Workflow: correlate traces with logs

1. Obtain a `trace_id` (hex) from `query-apm-spans` results or `exemplarTraceIds`.
2. Call `posthog:query-logs` with a filter on `trace_id` (same hex) for that project’s log query shape — see logs tool schema.
3. Optional: if spans include `session.id` (or project links sessions another way), use session replay tools when the user needs UI context; linkage depends on instrumentation.

## Workflow: traffic or error trends by service

Use `posthog:apm-sparkline-query` with a `query` object (`dateRange`, optional `serviceNames`, `filterGroup`) for compact time series before drilling into spans.

## Pagination

When `hasMore` is true, pass the prior response’s `nextCursor` string as `query.after` on the next `query-apm-spans` call; keep other `query` fields identical unless intentionally changing filters.

## Workflow: explore unknown attributes

1. `posthog:apm-attributes-list` — narrow keys (e.g. search `"http"`).
2. `posthog:apm-attribute-values-list` — inspect values for a chosen key.
3. Build filters in `posthog:query-apm-spans` using the discovered keys.

## Reminders

- Prefer discovering attribute keys and services before guessing filters.
- Durations in filters are in **nanoseconds**.
- `query-apm-spans` expects a **`query`** wrapper object; defaults often assume a recent time window — tighten `query.dateRange` when the question implies it.
- Read `warnings` and `resolvedDateRange` on span query responses; progressive time-slice search favors recent data inside wide windows.
- Zero spans does **not** prove a healthy service — it may mean no data in range or missing OTEL export.
