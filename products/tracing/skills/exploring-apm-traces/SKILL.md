---
name: exploring-apm-traces
description: >
  Investigates distributed application performance using PostHog APM (OpenTelemetry span) data via MCP.
  Use when the user asks about service traces, slow HTTP/database spans, error spans, trace IDs, or span
  attributes — not LLM analytics traces or product logs. Uses posthog:query-apm-spans, posthog:apm-trace-get,
  posthog:apm-services-list, posthog:apm-attributes-list, and posthog:apm-attribute-values-list.
---

# Exploring APM traces (OpenTelemetry spans)

PostHog captures distributed traces from OpenTelemetry. Each trace is a tree of spans representing a request’s path through services.

**Disambiguation:** This skill is for **APM / OpenTelemetry traces**. Do not confuse with **LLM analytics traces** (agent/model `$ai_*` events and LLM observability tools) or **logs** (`posthog:query-logs`, `posthog:logs-*`).

## MCP tools

| Tool                                | Purpose                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------ |
| `posthog:query-apm-spans`           | Search and filter spans (analytics-style query; parameters live under `query`) |
| `posthog:apm-trace-get`             | Fetch all spans for a hex `trace_id`                                           |
| `posthog:apm-services-list`         | List distinct service names                                                    |
| `posthog:apm-attributes-list`       | List span or resource attribute keys                                           |
| `posthog:apm-attribute-values-list` | List values for a specific attribute key                                       |

For aggregates or joins not covered by these tools, `posthog:execute-sql` may be appropriate once the span schema is confirmed for the project.

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
2. Find slow spans: `posthog:query-apm-spans` with a `query` that filters by service and `duration` (remember nanoseconds: 1s = 1_000_000_000).
3. Drill in: `posthog:apm-trace-get` with `{ "trace_id": "<hex from step 2>" }`.

## Workflow: find error traces

Use `posthog:query-apm-spans` with `query.filterGroup` on `status_code` `exact` / numeric operators as appropriate — OpenTelemetry status **2** means error.

## Workflow: explore unknown attributes

1. `posthog:apm-attributes-list` — narrow keys (e.g. search `"http"`).
2. `posthog:apm-attribute-values-list` — inspect values for a chosen key.
3. Build filters in `posthog:query-apm-spans` using the discovered keys.

## Reminders

- Prefer discovering attribute keys and services before guessing filters.
- Durations in filters are in **nanoseconds**.
- `query-apm-spans` expects a **`query`** wrapper object; defaults often assume a recent time window — tighten `query.dateRange` when the question implies it.
