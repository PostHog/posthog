#### Schema-first workflow

Verify the data schema before constructing any insight query. Canonical-looking events
(`$pageview`, `$identify`, `$autocapture`, …) still need confirmation — they can be absent,
renamed, or filtered per team.

1. **Discover events** - `read-data-schema` with `kind: events` to find events matching the user's intent.
2. **Discover properties** - `read-data-schema` with `kind: event_properties` (or `person_properties`, `session_properties`).
3. **Verify property values** - `read-data-schema` with `kind: event_property_values` when the value must match (e.g., "US" vs "United States").
4. **Then construct the query** using the appropriate `query-*` tool.

If the required events or properties don't exist, tell the user instead of running an empty query.

#### Insight query workflow

1. Discover the data schema with `read-data-schema` (see schema-first workflow above).
2. Choose the appropriate `query-*` tool based on the user's question.
3. Construct the query schema. Each tool's description includes detailed schema documentation with examples. Be minimalist: only include filters, breakdowns, and settings essential to answer the question.
4. Execute the query and analyze the results.
5. Optionally save as an insight with `insight-create` or add to a dashboard.

For complex investigations, combine multiple query types. For example, use `query-trends` to identify when a metric changed, then `query-funnel` to check if conversion was affected, then `query-trends` with breakdowns to isolate the segment.
