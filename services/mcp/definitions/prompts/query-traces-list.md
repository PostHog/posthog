List LLM traces to inspect AI/LLM usage across your application. Returns traces with their events, latency, token usage, costs, errors, and other metadata. Use this tool for AI observability — debugging slow generations, investigating errors, analyzing token spend, and auditing LLM behavior.

Use 'read-data-schema' to discover available event properties for filtering (e.g. `$ai_model`, `$ai_provider`).

Examples of use cases include:

- How much are we spending on LLM tokens per day?
- Which LLM generations are the slowest?
- Are there any traces with errors in the last 24 hours?
- What models are being used and how do their costs compare?
- Show me traces for a specific user to debug their experience.
- Are there any traces with unusually high token usage?

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

# Data narrowing

## Property filters

Use property filters to narrow results. Only include property filters when they are essential to directly answer the user's question. Avoid adding them if the question can be addressed without additional segmentation and always use the minimum set of property filters needed.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you should:

- **Prioritize properties directly related to the context or objective of the user's query.** Common AI properties include `$ai_model`, `$ai_provider`, `$ai_trace_id`, `$ai_latency`, `$ai_input_tokens`, `$ai_output_tokens`, `$ai_total_cost_usd`, `$ai_is_error`.
- **Ensure that you find both the property group and name.** Property groups should be one of the following: event, person, session, group.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`).
- If the operator requires a value, use the `read-data-schema` tool to find the property values.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group.

Supported operators for the String type are:

- equals (exact)
- doesn't equal (is_not)
- contains (icontains)
- doesn't contain (not_icontains)
- matches regex (regex)
- doesn't match regex (not_regex)
- is set
- is not set

Supported operators for the Numeric type are:

- equals (exact)
- doesn't equal (is_not)
- greater than (gt)
- less than (lt)
- is set
- is not set

Supported operators for the DateTime type are:

- equals (is_date_exact)
- doesn't equal (is_not for existence check)
- before (is_date_before)
- after (is_date_after)
- is set
- is not set

Supported operators for the Boolean type are:

- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values (as an array).

## Time period

You should not filter events by time using property filters. Instead, use the `dateRange` field. If the question doesn't mention time, use last 7 days as a default time period.

# Traces guidelines

This is a listing tool, not a visualization/insight tool. It returns a paginated list of LLM traces — it does NOT support series, breakdowns, math aggregations, or chart types.

## Response shape

Each trace in the results contains:

- `id` — unique trace ID
- `traceName` — name of the trace (if set via SDK)
- `createdAt` — timestamp of the first event in the trace
- `distinctId` — the person's distinct ID
- `totalLatency` — total latency in seconds
- `inputTokens` / `outputTokens` — token counts across all generations in the trace
- `inputCost` / `outputCost` / `totalCost` — costs in USD
- `errorCount` — number of errors in the trace
- `tools` — list of tool names called during the trace
- `events` — list of direct child events (generations, metrics, feedback)

## Pagination

Use `limit` and `offset` for pagination. The default limit is 100. The response includes a `hasMore` field indicating whether more results are available.

## Filtering

- `filterTestAccounts` — exclude internal/test users
- `filterSupportTraces` — exclude support impersonation traces
- `personId` — filter by a specific person UUID
- `groupKey` + `groupTypeIndex` — filter by a specific group
- `randomOrder` — use random ordering instead of newest-first (useful for representative sampling)

# Examples

## Recent traces with errors

```json
{
  "kind": "TracesQuery",
  "dateRange": { "date_from": "-7d" },
  "filterTestAccounts": true,
  "properties": [{ "key": "$ai_is_error", "operator": "exact", "type": "event", "value": ["true"] }],
  "limit": 50
}
```

## Traces for a specific model

```json
{
  "kind": "TracesQuery",
  "dateRange": { "date_from": "-7d" },
  "filterTestAccounts": true,
  "properties": [{ "key": "$ai_model", "operator": "exact", "type": "event", "value": ["gpt-4o"] }]
}
```

## Traces for a specific person

```json
{
  "kind": "TracesQuery",
  "dateRange": { "date_from": "-30d" },
  "personId": "01234567-89ab-cdef-0123-456789abcdef",
  "filterTestAccounts": true
}
```

## Random sample of traces (avoids recency bias)

```json
{
  "kind": "TracesQuery",
  "dateRange": { "date_from": "-30d" },
  "filterTestAccounts": true,
  "randomOrder": true,
  "limit": 20
}
```

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
- This tool returns raw trace data — it does not aggregate or visualize. For aggregated LLM metrics over time (e.g. total token usage per day), use `query-trends` with AI events like `$ai_generation` instead.
- Use `filterTestAccounts: true` by default to exclude internal users unless the user asks otherwise.
- The default time range is last 7 days. LLM trace data tends to be recent, so shorter ranges are usually appropriate.
