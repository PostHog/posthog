---
name: exploring-llm-traces
description: >
  How to query, inspect, and debug LLM traces using PostHog's MCP tools.
  Use when the user asks to debug an AI agent trace, investigate LLM behavior,
  inspect token usage or costs, find why an agent made a decision, or explore
  AI/LLM observability data.
---

# Exploring LLM traces with MCP tools

PostHog captures LLM/AI agent activity as traces. Each trace is a tree of events representing
a single AI interaction — from the top-level agent invocation down to individual LLM API calls.

## Available tools

| Tool                            | Purpose                                                   |
| ------------------------------- | --------------------------------------------------------- |
| `posthog:query-llm-traces-list` | Search and list traces (compact — no large content)       |
| `posthog:query-llm-trace`       | Get a single trace by ID with configurable content detail |
| `posthog:execute-sql`           | Ad-hoc SQL for complex trace analysis                     |

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

### Step 1 — Get a structural overview (cheap)

Load the trace with `contentDetail: "none"` to see the event tree without large properties.
This is small enough to read inline.

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id>",
  "dateRange": {"date_from": "-30d"},
  "contentDetail": "none"
}
```

From this you get:

- Every event with its type (`$ai_span`, `$ai_generation`, etc.)
- Span names (`$ai_span_name`) — these are the tool/step names
- Latency, error flags, models used
- Parent-child relationships via `$ai_parent_id`
- `_posthogUrl` — **always include this in your response** so the user can click through to the UI

### Step 2 — Preview the interesting parts

Once you've identified the suspicious event(s), re-fetch with `"preview"` to see
truncated input/output (first/last 300 chars). This is usually enough to understand
what happened without blowing up the context.

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id>",
  "dateRange": {"date_from": "-30d"},
  "contentDetail": "preview"
}
```

### Step 3 — Deep dive into full content (dump to file)

Only when you need to read actual messages or full tool outputs.
The result will be large — it auto-persists to a file.

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id>",
  "dateRange": {"date_from": "-30d"},
  "contentDetail": "full"
}
```

Then use the [parsing scripts](./scripts/) on the persisted file:

```bash
python3 scripts/print_timeline.py /path/to/persisted-file.json    # event timeline
python3 scripts/extract_conversation.py /path/to/persisted-file.json  # LLM messages
SEARCH="keyword" python3 scripts/search_traces.py /path/to/persisted-file.json  # find text
```

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

### By filters

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-7d"},
  "filterTestAccounts": true,
  "limit": 20,
  "properties": [
    {"type": "event", "key": "$ai_model", "value": "gpt-4o", "operator": "exact"}
  ]
}
```

### By external identifiers

Customers often store their own IDs as event or person properties.
Use `read-data-schema` to discover available properties, then filter:

```json
posthog:query-llm-traces-list
{
  "dateRange": {"date_from": "-7d"},
  "properties": [
    {"type": "event", "key": "project_id", "value": "proj_abc123", "operator": "exact"}
  ]
}
```

### By content (SQL)

```sql
SELECT
    properties.$ai_trace_id AS trace_id,
    properties.$ai_model AS model,
    timestamp
FROM events
WHERE
    event = '$ai_generation'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND properties.$ai_input ILIKE '%search term%'
ORDER BY timestamp DESC
LIMIT 20
```

## Parsing large trace results

Trace tool results are JSON. When too large to read inline, Claude Code persists them to a file.

### Persisted file format

```json
[{ "type": "text", "text": "{\"results\": [...], \"_posthogUrl\": \"...\"}" }]
```

### Trace JSON structure

```
results (array for list, object for single trace)
  ├── id, traceName, createdAt, totalLatency, totalCost
  ├── inputState, outputState (trace-level state)
  └── events[]
        ├── event ($ai_trace | $ai_span | $ai_generation | $ai_embedding)
        ├── id, createdAt
        └── properties
              ├── $ai_span_name, $ai_latency, $ai_is_error
              ├── $ai_input_state, $ai_output_state (span tool I/O)
              ├── $ai_input, $ai_output_choices (generation messages)
              ├── $ai_model, $ai_provider
              └── $ai_input_tokens, $ai_output_tokens, $ai_total_cost_usd
```

### Available scripts

| Script                                                         | Purpose                                          | Usage                                                    |
| -------------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------- |
| [`print_timeline.py`](./scripts/print_timeline.py)             | Chronological event timeline with I/O summaries  | `python3 scripts/print_timeline.py FILE`                 |
| [`extract_conversation.py`](./scripts/extract_conversation.py) | Extract user/assistant messages from generations | `python3 scripts/extract_conversation.py FILE`           |
| [`search_traces.py`](./scripts/search_traces.py)               | Find a keyword across all event properties       | `SEARCH="keyword" python3 scripts/search_traces.py FILE` |
| [`show_structure.py`](./scripts/show_structure.py)             | Show JSON keys and types without values          | `cat blob.json \| python3 scripts/show_structure.py`     |

## Tips

- Always set `dateRange` — queries without a time range are slow
- Use progressive content detail: `none` → `preview` → `full` (dumped to file)
- Always include the `_posthogUrl` in your response so the user can click through
- `$ai_input_state` / `$ai_output_state` on spans contain tool call inputs and outputs
- `$ai_input` / `$ai_output_choices` on generations contain the full LLM conversation — can be megabytes, always dump to file
- Use `filterTestAccounts: true` to exclude internal/test traffic when searching
