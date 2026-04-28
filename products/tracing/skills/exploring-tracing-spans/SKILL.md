---
name: exploring-tracing-spans
description: >
  Investigate and debug distributed traces using PostHog's tracing MCP tools.
  Use when the user asks to explore trace spans, debug a slow request,
  find error traces, inspect a specific trace by ID, or analyze service
  performance and latency across their distributed system.
---

# Exploring tracing spans with MCP tools

PostHog captures distributed traces via OpenTelemetry. Each trace is a tree of spans representing
a request's journey through services — from the entry point down to individual operations.

## Code map (repo)

- **`products/tracing/mcp/tools.yaml`** — Enables each tool, `url_prefix: /tracing`, scopes `tracing:read`, UI apps (`trace-span`, `trace-span-list`), prompt file for query.
- **`services/mcp/src/tools/generated/tracing.ts`** — Generated handlers: `POST/GET` to `/api/environments/{projectId}/tracing/spans/...` (from OpenAPI operation IDs).
- **`services/mcp/src/tools/generated/index.ts`** — Merges `...tracing` into `GENERATED_TOOL_MAP`.
- **`services/mcp/schema/generated-tool-definitions.json`** — Tool metadata (`required_scopes`, `new_mcp`, descriptions).
- **`products/tracing/backend/presentation/views.py`** — `SpansViewSet` actions; each action uses `required_scopes=["tracing:read"]`.

## MCP connectivity (why tools can be “missing”)

The MCP server **only registers** a tool if the session’s API key passes `hasScopes` for that tool’s `required_scopes`. Tracing tools need **`tracing:read`** (or `*`).

Local dev: `setup_local_api_key` defaults to **empty scopes** unless you pass `--scopes` / `--add-scopes`. If your key has no `tracing:read`, tracing tools never appear and clients report **tool not found**. Fix:

```bash
python manage.py setup_local_api_key --add-scopes tracing:read
# or --scopes "*" for full access (local DEBUG only)
```

Also ensure the MCP binary matches a build whose OpenAPI includes tracing (`hogli build:openapi` and MCP generate per `services/mcp/CONTRIBUTING.md`), then restart the MCP process.

**Tool name prefixes:** Some hosts document `posthog:tracing-spans-query-create`. **Cursor’s local PostHog MCP** lists tools as **`tracing-spans-query-create`** (no `posthog:` prefix). Use the names your client actually exposes.

## Available tools

| Tool (typical local / Cursor name)        | Purpose                                                |
| ----------------------------------------- | ------------------------------------------------------ |
| `tracing-spans-query-create`              | Search and filter spans (by service, status, duration) |
| `tracing-spans-trace-create`              | Get all spans for a specific trace by hex trace ID     |
| `tracing-spans-service-names-retrieve`    | List available service names                           |
| `tracing-spans-attributes-retrieve`       | List available span/resource attribute names           |
| `tracing-spans-values-retrieve`           | List values for a specific attribute key               |
| `execute-sql` (or `query-run` with HogQL) | Ad-hoc SQL for complex trace analysis                  |

## Span data model

Each span contains:

| Field            | Description                                                                      |
| ---------------- | -------------------------------------------------------------------------------- |
| `trace_id`       | Hex ID linking all spans in a single trace                                       |
| `span_id`        | Unique hex ID for this span                                                      |
| `parent_span_id` | Hex ID of the parent span (null for root)                                        |
| `name`           | Operation name (e.g. `HTTP GET /api/users`)                                      |
| `kind`           | Span kind: 0=Unspecified, 1=Internal, 2=Server, 3=Client, 4=Producer, 5=Consumer |
| `service_name`   | Service that emitted the span                                                    |
| `status_code`    | 0=Unset, 1=OK, 2=Error                                                           |
| `timestamp`      | Start time (ISO 8601)                                                            |
| `end_time`       | End time (ISO 8601)                                                              |
| `duration_nano`  | Duration in nanoseconds                                                          |
| `is_root_span`   | Whether this is the trace's entry point                                          |

### Property filter types

- `span` — built-in fields: trace_id, span_id, duration, name, kind, status_code
- `span_attribute` — span-level attributes: http.method, http.status_code, db.system, etc.
- `span_resource_attribute` — resource-level attributes: k8s.pod.name, service.version, etc.

## Workflow: investigate a performance issue

### Step 1 — Discover services

```json
tracing-spans-service-names-retrieve
{}
```

### Step 2 — Find slow or error spans

```json
tracing-spans-query-create
{
  "query": {
    "serviceNames": ["api-gateway"],
    "filterGroup": [{ "key": "duration", "operator": "gt", "type": "span", "value": "1000000000" }],
    "dateRange": { "date_from": "-1d" },
    "limit": 20
  }
}
```

Duration is in nanoseconds: 1s = 1,000,000,000 ns, 1ms = 1,000,000 ns.

### Step 3 — Drill into a specific trace

```json
tracing-spans-trace-create
{
  "trace_id": "<hex_trace_id_from_step_2>"
}
```

This returns all spans in the trace tree. Analyze the parent-child relationships
and durations to find the bottleneck.

### Step 4 — Analyze with SQL (advanced)

For aggregate analysis beyond what the tools provide:

```sql
-- Top 10 slowest operations in the last hour
SELECT
    name,
    service_name,
    avg(duration_nano) / 1000000 as avg_ms,
    max(duration_nano) / 1000000 as max_ms,
    count() as cnt
FROM posthog.trace_spans
WHERE timestamp >= now() - INTERVAL 1 HOUR
GROUP BY name, service_name
ORDER BY avg_ms DESC
LIMIT 10
```

## Workflow: find error traces

```json
tracing-spans-query-create
{
  "query": {
    "filterGroup": [{ "key": "status_code", "operator": "exact", "type": "span", "value": "2" }],
    "dateRange": { "date_from": "-6h" },
    "limit": 20
  }
}
```

Status code 2 = Error in OpenTelemetry.

## Workflow: explore attributes

When you don't know what attributes are available:

1. List attribute names:

```json
tracing-spans-attributes-retrieve
{ "attribute_type": "span", "search": "http" }
```

2. List values for an attribute:

```json
tracing-spans-values-retrieve
{ "key": "http.method", "attribute_type": "span" }
```

3. Use discovered attributes in filters:

```json
tracing-spans-query-create
{
  "query": {
    "filterGroup": [
      { "key": "http.method", "operator": "exact", "type": "span_attribute", "value": "POST" },
      { "key": "http.status_code", "operator": "gt", "type": "span_attribute", "value": "499" }
    ],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Key reminders

- Always discover attributes with `tracing-spans-attributes-retrieve` before guessing filter keys
- Always discover services with `tracing-spans-service-names-retrieve` before filtering by service
- Duration values are in nanoseconds (1 second = 1,000,000,000)
- The `prefetchSpans` parameter on query lets you preview child spans without fetching full traces
- Use `rootSpans: false` when you need to see all spans, not just trace entry points
- Default time range is last hour (`-1h`); adjust based on the user's question
