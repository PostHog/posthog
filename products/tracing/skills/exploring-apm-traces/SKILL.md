---
name: exploring-apm-traces
description: >
  Investigates distributed application performance using PostHog APM (OpenTelemetry span) data via MCP.
  Use when the user asks about service traces, slow HTTP/database spans, error spans, trace IDs, or span
  attributes — not AI observability traces or product logs. Uses posthog:query-apm-spans, posthog:apm-trace-get,
  posthog:apm-services-list, posthog:apm-attributes-list, and posthog:apm-attribute-values-list.
---

# Exploring APM traces (OpenTelemetry spans)

PostHog captures distributed traces from OpenTelemetry. Each trace is a tree of spans representing a request's path through services.

**Disambiguation:** This skill is for **APM / OpenTelemetry traces**. Do not confuse with **AI observability traces** (agent/model `$ai_*` events) or **logs** (`posthog:query-logs`, `posthog:logs-*`).

## Available tools

| Tool                                | Purpose                                           |
| ----------------------------------- | ------------------------------------------------- |
| `posthog:query-apm-spans`           | Search and filter spans (compact list view)       |
| `posthog:apm-trace-get`             | Get the full span list for one hex `trace_id`     |
| `posthog:apm-spans-aggregate`       | Per-operation aggregates (count, p50/p95, errors) |
| `posthog:apm-spans-tree`            | Call-tree aggregates per `(parent, child)` edge   |
| `posthog:apm-services-list`         | List distinct service names                       |
| `posthog:apm-attributes-list`       | List span or resource attribute keys              |
| `posthog:apm-attribute-values-list` | List values for a specific attribute key          |

See [references/spans-and-fields.md](./references/spans-and-fields.md) for the response schema and the `kind`/`status_code` enums.

## Workflow: debug a trace from a URL

### Step 1 — Fetch the trace

```json
posthog:apm-trace-get
{
  "trace_id": "<hex_trace_id>"
}
```

The response is `{ results: [span, span, …] }` — a flat list of every span in the trace.
The list can be very large for fan-out request flows; when it exceeds the inline limit, Claude Code auto-persists it to a file.

From the result you get:

- Every span with `name`, `service_name`, `kind`, `status_code`, `parent_span_id`, `duration_nano`, `is_root_span`
- The `_posthogUrl` — **always include this in your response** so the user can click through to the UI

### Step 2 — Parse large results with scripts

When the result is persisted to a file (traces with hundreds of spans across services), use the [parsing scripts](./scripts/) to explore it.

**Start with the summary** to get the full picture, then drill into specifics:

```bash
# 1. Overview: services, span count, slowest spans, errors
python3 scripts/print_summary.py /path/to/persisted-file.json

# 2. Indented chronological tree (DFS by parent_span_id)
python3 scripts/print_timeline.py /path/to/persisted-file.json

# 3. Drill into a specific span by name
SPAN="HTTP GET /api/users" python3 scripts/extract_span.py /path/to/persisted-file.json

# 4. Search for a keyword across span names, services, IDs
SEARCH="keyword" python3 scripts/search_spans.py /path/to/persisted-file.json

# 5. When the JSON shape looks unfamiliar
python3 scripts/show_structure.py /path/to/persisted-file.json
```

All scripts support `MAX_LEN=N` env var to control truncation (`0` = unlimited).

## Tree reconstruction (parent_span_id → span_id)

The flat span list is a tree. Each span carries:

- `trace_id` — same on every span in the trace
- `span_id` — this span's unique hex ID
- `parent_span_id` — points to the parent's `span_id` (zero-padded hex `000…000` for the root)
- `is_root_span` — convenience flag for the trace entry

To rebuild the tree:

1. Spans where `is_root_span` is true (or `parent_span_id == "00000000…"`) are **root spans**.
2. Every other span is a child of the span whose `span_id` matches its `parent_span_id`.
3. Group by `parent_span_id`, walk from each root downward.

`scripts/print_timeline.py` does this for you and prints a DFS-indented tree.

## Investigation patterns

### "Where is time going?"

1. Run `print_summary.py` — it surfaces the top-5 slowest spans by `duration_nano`.
2. For a noisy trace, run `print_timeline.py` and scan the indented durations — you can see whether time is dominated by one child span or fan-out across many.
3. To dig into one slow span, `SPAN="<name>" python3 scripts/extract_span.py FILE`.

### "Where did the error happen?"

1. `print_summary.py` lists every span with `status_code == 2` (Error). Each entry shows service, span name, and parent context.
2. Walk up the tree from an error span via `parent_span_id` to see what request path led there.
3. Error detail lives in each span's `attributes` map (e.g. `exception.message`, `exception.type`), which **is** returned in the trace payload — read it directly off the error span. `apm-attribute-values-list` is for discovering values across spans, not a prerequisite for reading one span's attributes.

### "Did the request hit service X?"

1. Run `print_summary.py` — it prints the set of services involved in the trace.
2. If service X is missing, the request never reached it (or instrumentation is missing — check `apm-services-list` to confirm X has emitted spans recently at all).

### "Did the fan-out look right?"

1. `print_timeline.py` shows the indentation — wide trees mean parallel calls, deep trees mean sequential dependencies.
2. Look for spans of kind `Client` (3) followed by matching `Server` (2) spans on the called service — that's a synchronous downstream call.

### Searching by attribute (e.g. `http.method=POST`)

Each span carries an `attributes` map (span-level OTel attributes like `http.method`, `db.statement`) **in the payload** — so for a span you already have, just read it. **Resource** attributes (k8s labels, `service.version`) are not in the payload. To filter the whole dataset by an attribute:

1. Use `apm-attributes-list` / `apm-attribute-values-list` to discover keys and values (resource attributes especially).
2. Re-issue `query-apm-spans` with a `filterGroup` entry of type `span_attribute` or `span_resource_attribute`.

## Constructing UI links

`apm-trace-get` and `query-apm-spans` return `_posthogUrl` — **always surface this to the user** so they can verify in the PostHog UI.

When presenting findings, include the relevant PostHog URL.

## Finding traces

Use `posthog:query-apm-spans` to search and filter spans. Note this returns spans, not a tree — pass `query.traceId` or grab a `trace_id` from the results and feed it to `apm-trace-get` for the tree.

### Discover before filtering

Before constructing filters, discover what's actually in the project:

1. **Confirm services exist** — call `apm-services-list` to see which services have emitted spans.
2. **Find filterable attributes** — call `apm-attributes-list` with `attribute_type: "span"` or `"resource"`.
3. **Get actual values** — call `apm-attribute-values-list` with a key to see the real values in use.

Only then construct `query-apm-spans` filters. Custom attributes vary per project and cannot be guessed.

### By filters

```json
posthog:query-apm-spans
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": {"date_from": "-1h"},
    "filterGroup": [
      {"key": "http.status_code", "operator": "gt", "type": "span_attribute", "value": "499"}
    ]
  }
}
```

### By trace ID (when known)

```json
posthog:apm-trace-get
{
  "trace_id": "0123456789abcdef0123456789abcdef"
}
```

### Common gotchas

- **Durations are nanoseconds.** 1 second = `1_000_000_000`. Filter values in `query-apm-spans` for `duration` are also nanoseconds.
- **`status_code == 2` is Error.** `0` is Unset, `1` is OK. Use `OK` to match `{0, 1}` in the UI filter.
- **`kind`** is an integer 0–5: 0 Unspecified, 1 Internal, 2 Server, 3 Client, 4 Producer, 5 Consumer.
- **`parent_span_id` of a root span** is `"0000000000000000"` (16 zero hex chars, matching the 8-byte span ID width — _not_ the 16-byte trace ID width), not null.

## Parsing large trace results

Trace tool results are JSON. When too large to read inline, Claude Code persists them to a file.

### Persisted file format

```json
[{ "type": "text", "text": "{\"results\": [...], \"_posthogUrl\": \"...\"}" }]
```

Every script in `scripts/` unwraps this envelope before parsing.

### Trace JSON structure

```text
results (array of span dicts)
  └── each span:
        ├── uuid, trace_id, span_id, parent_span_id (hex strings)
        ├── name, kind (int 0–5), service_name
        ├── status_code (int 0–2), is_root_span (bool)
        ├── timestamp, end_time (ISO 8601)
        ├── duration_nano (int, nanoseconds)
        ├── attributes (map of span-level OTel attributes, e.g. db.statement, http.url)
        └── matched_filter (0/1 — 1 if this span matched the query-apm-spans filter, 0 if it
            only shares a trace with a match; always present, only meaningful from query-apm-spans)
```

### Available scripts

| Script                                             | Purpose                                              | Usage                                              |
| -------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| [`print_summary.py`](./scripts/print_summary.py)   | Trace metadata, services, slowest spans, errors      | `python3 scripts/print_summary.py FILE`            |
| [`print_timeline.py`](./scripts/print_timeline.py) | DFS-indented tree from `parent_span_id` walk         | `python3 scripts/print_timeline.py FILE`           |
| [`extract_span.py`](./scripts/extract_span.py)     | Full row + parent/children for spans matching a name | `SPAN="name" python3 scripts/extract_span.py FILE` |
| [`search_spans.py`](./scripts/search_spans.py)     | Find a keyword across name, service_name, IDs        | `SEARCH="kw" python3 scripts/search_spans.py FILE` |
| [`show_structure.py`](./scripts/show_structure.py) | Show JSON keys and types without values              | `python3 scripts/show_structure.py FILE`           |

## Tips

- Always set `dateRange` on `query-apm-spans` — queries without a time range are slow. Default is `-1h`; widen only when needed.
- Always include the `_posthogUrl` in your response so the user can click through.
- Span-level attributes **are** in the `apm-trace-get` / `query-apm-spans` payload (each span's `attributes` map). Resource attributes are not — use `apm-attributes-list` (type `resource`) and `apm-attribute-values-list` for those.
- `is_root_span` is the cheap way to find the trace entry — don't string-match `00000000…`.
- For aggregates (p95 by operation, slowest children of a span), use `apm-spans-aggregate` for a flat view or `apm-spans-tree` for parent→child edges — don't reach for SQL.
