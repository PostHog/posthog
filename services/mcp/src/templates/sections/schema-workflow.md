#### Schema-first workflow

Verify the data schema before constructing any insight query. Canonical-looking events
(`$pageview`, `$identify`, `$autocapture`, …) still need confirmation — they can be absent,
renamed, or filtered per team.

Every `read-data-schema` call takes one `query` object, so send the whole payload under `query`.

1. **Discover events** - `{"query": {"kind": "events"}}` to find events matching the user's intent.
2. **Discover properties** - `{"query": {"kind": "event_properties", "event_name": "<event>"}}` for an event, or `{"query": {"kind": "entity_properties", "entity": "<entity>"}}` for a person, session, or group type (use the group type name for a group).
3. **Verify property values** - `{"query": {"kind": "event_property_values", "event_name": "<event>", "property_name": "<property>"}}` when the value must match (e.g., "US" vs "United States").
4. **Then construct the query** using the appropriate `query-*` tool.

If the required events or properties don't exist, tell the user instead of running an empty query.

#### Insight query workflow

After the schema-first steps, choose the `query-*` tool matching the question, construct a minimal query (only the filters, breakdowns, and settings essential to the answer — each tool's description documents its schema with examples), execute, and analyze. Optionally save as an insight with `insight-create` or add to a dashboard.

For complex investigations, combine multiple query types. For example, use `query-trends` to identify when a metric changed, then `query-funnel` to check if conversion was affected, then `query-trends` with breakdowns to isolate the segment.
