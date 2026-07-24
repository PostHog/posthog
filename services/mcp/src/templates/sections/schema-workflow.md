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

After the schema-first steps, choose the `query-*` tool matching the question, construct a minimal query (only the filters, breakdowns, and settings essential to the answer — each tool's description documents its schema with examples), execute, and analyze. Optionally save as an insight with `insight-create` or add to a dashboard.

For complex investigations, combine multiple query types. For example, use `query-trends` to identify when a metric changed, then `query-funnel` to check if conversion was affected, then `query-trends` with breakdowns to isolate the segment.
