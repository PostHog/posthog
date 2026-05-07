---
name: investigating-apm-and-logs
description: >
  Triages incidents and performance questions using PostHog logs and APM (OpenTelemetry spans) together.
  Use when the user asks about logs plus traces, correlation on trace_id, 502 or HTTP errors vs span status,
  service mismatch between logs UI and trace services, infra vs application signals, or "why is error rate high".
  Prefer posthog:apm-logs-signal-snapshot when the project has the tracing feature flag and the tool succeeds; otherwise MCP logs/tracing tools and HogQL recipes.
---

# Investigating APM and logs (cross-signal)

PostHog stores **logs** (OTLP log records, including `service_name`, `trace_id`, `body`) and **trace spans** (`posthog.trace_spans` in HogQL, `service_name`, OTEL `status_code`, HTTP attributes) as separate pipelines. Treat them as **parallel evidence**, not one guaranteed join.

For **span-only** deep dives (attributes, pagination, exemplar traces), use [`exploring-apm-traces`](../../../tracing/skills/exploring-apm-traces/SKILL.md). For arbitrary HogQL and system tables, use [`querying-posthog-data`](../querying-posthog-data/SKILL.md).

## MCP tools (compose, do not assume one mega-tool)

| Tool                               | Role                                                                                                                                                                                                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `posthog:apm-logs-signal-snapshot` | One-shot joinability + service overlap + resolved window. Requires **`tracing`** feature flag for the project, plus `tracing:read` and `logs:read` scopes. **403** or flag message → treat as unavailable. **Call first** when investigating both signals and the gate passes. |
| `posthog:logs-count`               | Cheap volume before `query-logs`.                                                                                                                                                                                                                                              |
| `posthog:query-logs`               | Raw log lines; requires `serviceNames` or resource filters per tool schema.                                                                                                                                                                                                    |
| `posthog:apm-services-list`        | Distinct **trace** `service_name` values (not the same set as log services).                                                                                                                                                                                                   |
| `posthog:apm-sparkline-query`      | Time-bucketed span counts (OTEL `statusCodes` or `filterGroup` on `http.status_code`).                                                                                                                                                                                         |
| `posthog:query-apm-spans`          | Span rows + `exemplarTraceIds`, `hasMore`, `warnings`, `resolvedDateRange`.                                                                                                                                                                                                    |
| `posthog:apm-trace-get`            | Full trace for a hex `trace_id`; use `maxSpans` to cap payload.                                                                                                                                                                                                                |
| `posthog:execute-sql`              | Escape hatch when MCP filters are insufficient (see references).                                                                                                                                                                                                               |

## Gate 0 — Semantics (always)

Do **not** treat top-level APM `statusCodes` as HTTP response codes. It is **OpenTelemetry span status**: `0` Unset, `1` OK, `2` Error.

- **OTEL errors in spans:** `query.statusCodes: [2]` on `query-apm-spans` / `apm-sparkline-query`.
- **HTTP 4xx/5xx in spans:** `query.filterGroup` with `type: span_attribute`, `key: http.status_code`, numeric or string operators as appropriate.
- **Log "error rate" or JSON `status`:** log severity / payload — comparable in _meaning_ to HTTP or OTEL only after you map fields.

Details: [decision-tree](./references/decision-tree.md).

## Gate 1 — Joinability (before promising `apm-trace-get`)

1. Prefer **`posthog:apm-logs-signal-snapshot`** with the same `dateRange` you will use for logs and spans. Read `joinableTraceIdPercent` and `sampleJoinableTraceIds`. The REST/MCP endpoint is gated on the PostHog **`tracing`** feature flag for the project; if you get **403** (or the response says the `tracing` flag must be enabled), skip the snapshot and go to step 2.
2. If the snapshot is unavailable (**403**, missing tool, or errors), run the HogQL checks in [hogql-recipes](./references/hogql-recipes.md).
3. If joinability is **low** or samples are empty: **do not** promise a trace tree for every log line. Proxy or host logs often lack valid `trace_id`. Stay on logs + infra narrative; use spans for **different** services (e.g. compose health checks) without forcing a shared ID.

## Discovery — two "service" namespaces

| Source                                           | What "service" means                                         |
| ------------------------------------------------ | ------------------------------------------------------------ |
| Logs MCP / `logs.service_name`                   | Log record resource service name (what the logs UI filters). |
| `apm-services-list` / `trace_spans.service_name` | Name on exported spans.                                      |

Overlap is **not guaranteed**. The snapshot response includes `logServiceNames`, `traceServiceNames`, `serviceNamesOverlap`, `logOnlyServiceNames`, `traceOnlyServiceNames`.

## Volume and tokens

1. `logs-count` (and sparkline for span volume trends) before pulling large `query-apm-spans` / `query-logs` pages.
2. Use `query-apm-spans` `limit` / `prefetchSpans` and `apm-trace-get` `maxSpans` intentionally; read `warnings` and `resolvedDateRange` on span query responses.

See [mcp-contracts](./references/mcp-contracts.md).

## Parallel signals — expect divergence

Run **both**:

- Logs: errors for the relevant `serviceNames` (severity / message patterns).
- APM: `apm-sparkline-query` with `statusCodes: [2]` and, if the question is HTTP-shaped, a second call or `query-apm-spans` with `filterGroup` on `http.status_code`.

**OTEL quiet + logs red** usually means missing span instrumentation on the failing path, proxy-only errors, or traces emitted under a different `service_name` than log `service_name` — not "everything is fine."

## Drill-down when joinable

1. `sampleJoinableTraceIds` or a `trace_id` from `query-apm-spans`.
2. `apm-trace-get` with path `trace_id` and body `{ "maxSpans": <N> }`.
3. Optional: `query-logs` filtered by that `trace_id` for the same window.

## Pagination

Span pages: when `hasMore` is true, pass `nextCursor` as `query.after` on the next `query-apm-spans` call (same `query` otherwise).
