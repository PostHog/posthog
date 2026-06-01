---
name: exploring-llm-traces
description: >
  ABSOLUTE MUST to debug and inspect LLM/AI agent traces using PostHog's MCP tools.
  Use when the user pastes a trace URL (e.g. /llm-observability/traces/<id>),
  asks to debug a trace, figure out what went wrong, check if an agent used a tool correctly,
  verify context/files were surfaced, inspect subagent behavior, investigate LLM decisions,
  or analyze token usage and costs.
---

# Exploring LLM traces with MCP tools

PostHog captures LLM/AI agent activity as traces. Each trace is a tree of events representing
a single AI interaction — from the top-level agent invocation down to individual LLM API calls.

## Available tools

| Tool                            | Purpose                                             |
| ------------------------------- | --------------------------------------------------- |
| `posthog:query-llm-traces-list` | Search and list traces (compact — no large content) |
| `posthog:query-llm-trace`       | Get a single trace by ID with full event tree       |
| `posthog:execute-sql`           | Ad-hoc SQL for complex trace analysis               |

## Event hierarchy

See the [event reference](./references/events-and-properties.md) for the full schema.

```text
$ai_trace (top-level container)
  └── $ai_span (logical groupings, e.g. "RAG retrieval", "tool execution")
        ├── $ai_generation (individual LLM API call)
        └── $ai_embedding (embedding creation)
```

Events are linked via `$ai_parent_id` → parent's `$ai_span_id` or `$ai_trace_id`.

## Workflow: debug a trace from a URL

### Step 1 — Fetch the trace

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id>",
  "dateRange": {"date_from": "-7d"}
}
```

The result contains the full event tree with all properties.
The response may be large — when it exceeds the inline limit, Claude Code auto-persists it to a file.

From the result you get:

- Every event with its type (`$ai_span`, `$ai_generation`, etc.)
- Span names (`$ai_span_name`) — these are the tool/step names
- Latency, error flags, models used
- Parent-child relationships via `$ai_parent_id`
- `_posthogUrl` — **always include this in your response** so the user can click through to the UI

### Step 2 — Parse large results with scripts

When the result is persisted to a file (large traces with full `$ai_input`/`$ai_output_choices`),
use the [parsing scripts](./scripts/) to explore it.

**Start with the summary** to get the full picture, then drill into specifics:

```bash
# 1. Overview: metadata, tool calls, final output, errors
python3 scripts/print_summary.py /path/to/persisted-file.json

# 2. Timeline: chronological event list with truncated I/O
python3 scripts/print_timeline.py /path/to/persisted-file.json

# 3. Drill into a specific span's full input/output
SPAN="tool_name" python3 scripts/extract_span.py /path/to/persisted-file.json

# 4. Full conversation with thinking blocks and tool calls
python3 scripts/extract_conversation.py /path/to/persisted-file.json

# 5. Search for a keyword across all properties
SEARCH="keyword" python3 scripts/search_traces.py /path/to/persisted-file.json
```

All scripts support `MAX_LEN=N` env var to control truncation (0 = unlimited).

## Investigation patterns

### "Did the agent use the tool correctly?"

1. Find the `$ai_span` for the tool call (look at `$ai_span_name`)
2. Check `$ai_input_state` — what arguments were passed to the tool?
3. Check `$ai_output_state` — what did the tool return?
4. Check `$ai_is_error` — did the tool call fail?

### "Was the context correct?" / "Were the right files surfaced?"

1. Find the `$ai_generation` event where the LLM made the decision
2. Check `$ai_input` — this is the full message history the LLM saw
3. Look at preceding `$ai_span` events for retrieval/search steps
4. Check their `$ai_output_state` — what content was retrieved and fed to the LLM?

### "Did the subagent work?"

1. In the structural overview, find spans that are children of other spans (via `$ai_parent_id`)
2. The parent span is the orchestrator; child spans are subagent steps
3. Check each child's `$ai_output_state` and `$ai_is_error`
4. If a child span contains `$ai_generation` events, those are the subagent's LLM calls

### "Why did the LLM say X?"

1. Use `search_traces.py` to find where the text appears: `SEARCH="the text" python3 scripts/search_traces.py FILE`
2. This shows which event and property path contains it
3. Check the `$ai_input` of that generation to see what the LLM was told before it said X

## Constructing UI links

The trace tools return `_posthogUrl` — always surface this to the user.

You can also construct links manually:

- **Trace detail**: `https://app.posthog.com/llm-observability/traces/<trace_id>?timestamp=<url_encoded_timestamp>&event=<optional_event_id>`
- **Traces list with filters**: returned in `_posthogUrl` from `query-llm-traces-list`

The `timestamp` query param is **required** — use the `createdAt` of the earliest event in the trace, URL-encoded (e.g. `timestamp=2026-04-01T19%3A39%3A20Z`).

When presenting findings, always include the relevant PostHog URL so the user can verify.

## Finding traces

Use `posthog:query-llm-traces-list` to search and filter traces.

**CRITICAL: Never assume event names, property names, or property values from training data.**
Every project instruments different custom properties. Always call `posthog:read-data-schema` first
to discover what properties and values actually exist in the project's data before constructing filters.

### Discovering the schema first

Before filtering traces, discover what's available:

1. **Confirm AI events exist** — call `posthog:read-data-schema` with `kind: "events"` and look for `$ai_*` events
2. **Find filterable properties** — call `posthog:read-data-schema` with `kind: "event_properties"` and `event_name: "$ai_generation"` (or another AI event) to see what properties are captured
3. **Get actual values** — call `posthog:read-data-schema` with `kind: "event_property_values"`, `event_name: "$ai_generation"`, and `property_name: "$ai_model"` to see real model names in use

Only then construct the `query-llm-traces-list` call with property filters.

This is especially important for custom properties like `project_id`, `conversation_id`, `user_tier`, etc. — these vary per project and cannot be guessed.

Do not confirm `$ai_*` properties, but confirm any other like `email` of a person.

### By filters

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-1h"},
  "filterTestAccounts": true,
  "limit": 20,
  "properties": [
    {"type": "event", "key": "$ai_model", "value": "gpt-4o", "operator": "exact"}
  ]
}
```

Multiple filters are AND-ed together:

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-1h"},
  "filterTestAccounts": true,
  "properties": [
    {"type": "event", "key": "$ai_provider", "value": "anthropic", "operator": "exact"},
    {"type": "event", "key": "$ai_is_error", "value": ["true"], "operator": "exact"}
  ]
}
```

You can also filter by person properties (discover them via `read-data-schema` with `kind: "entity_properties"` and `entity: "person"`):

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-1h"},
  "filterTestAccounts": true,
  "properties": [
    {"type": "person", "key": "email", "value": "@company.com", "operator": "icontains"}
  ]
}
```

### By external identifiers

Customers often store their own IDs as event or person properties.
Use `posthog:read-data-schema` to discover what custom properties exist, then filter:

1. Call `posthog:read-data-schema` with `kind: "event_properties"` and `event_name: "$ai_trace"` to find custom properties
2. Review the returned properties and their sample values
3. Construct the filter using the discovered property key and a known value

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-7d"},
  "properties": [
    {"type": "event", "key": "project_id", "value": "proj_abc123", "operator": "exact"}
  ]
}
```

For more complex SQL patterns, read these references:

- [Single trace retrieval](./references/example-llm-trace.md.j2) — fetches a single trace by ID with all events and properties (renders the `TraceQuery` HogQL)
- [Traces list with aggregated metrics](./references/example-llm-traces-list.md) — two-phase query: find trace IDs first, then fetch aggregated latency, tokens, costs, and error counts

## Parsing large trace results

Trace tool results are JSON. When too large to read inline, Claude Code persists them to a file.

### Persisted file format

```json
[{ "type": "text", "text": "{\"results\": [...], \"_posthogUrl\": \"...\"}" }]
```

### Trace JSON structure

```text
results (array for list, object for single trace)
  ├── id, traceName, createdAt, totalLatency, totalCost
  ├── inputState, outputState (trace-level state)
  └── events[]
        ├── event ($ai_span | $ai_generation | $ai_embedding | $ai_metric | $ai_feedback)
        ├── id, createdAt
        └── properties
              ├── $ai_span_name, $ai_latency, $ai_is_error
              ├── $ai_input_state, $ai_output_state (span tool I/O)
              ├── $ai_input, $ai_output_choices (generation messages)
              ├── $ai_model, $ai_provider
              └── $ai_input_tokens, $ai_output_tokens, $ai_total_cost_usd
```

### Available scripts

| Script                                                         | Purpose                                                  | Usage                                                    |
| -------------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------- |
| [`print_summary.py`](./scripts/print_summary.py)               | Trace metadata, tool calls, errors, and final LLM output | `python3 scripts/print_summary.py FILE`                  |
| [`print_timeline.py`](./scripts/print_timeline.py)             | Chronological event timeline with I/O summaries          | `python3 scripts/print_timeline.py FILE`                 |
| [`extract_span.py`](./scripts/extract_span.py)                 | Full input/output of a specific span by name             | `SPAN="name" python3 scripts/extract_span.py FILE`       |
| [`extract_conversation.py`](./scripts/extract_conversation.py) | LLM messages with thinking blocks and tool calls         | `python3 scripts/extract_conversation.py FILE`           |
| [`search_traces.py`](./scripts/search_traces.py)               | Find a keyword across all event properties               | `SEARCH="keyword" python3 scripts/search_traces.py FILE` |
| [`show_structure.py`](./scripts/show_structure.py)             | Show JSON keys and types without values                  | `cat blob.json \| python3 scripts/show_structure.py`     |

## Tips

- Always set `dateRange` — queries without a time range are slow. Use narrow windows (`-30m`, `-1h`) for broad listing queries; wider windows (`-7d`, `-30d`) are fine for narrow queries filtered by trace ID or specific property values
- Always include the `_posthogUrl` in your response so the user can click through
- `$ai_input_state` / `$ai_output_state` on spans contain tool call inputs and outputs
- `$ai_input` / `$ai_output_choices` on generations contain the full LLM conversation — can be megabytes; when the result is persisted to a file, use the parsing scripts
- Use `filterTestAccounts: true` to exclude internal/test traffic when searching
- `$ai_trace` events are NOT in the `events` array — their data is surfaced via trace-level `inputState`, `outputState`, and `traceName`
