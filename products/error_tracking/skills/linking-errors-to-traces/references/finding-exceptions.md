# Find exception occurrences

- For an occurrence UUID, use `posthog:execute-sql` to select the exact
  `$exception` event by `uuid`.
- For a UUID-shaped session ID, use `posthog:execute-sql` to select
  `$exception` events with that exact `$session_id`. Start with a 30-day window
  and 21 rows. The extra row shows when the first 20 do not cover the session.
  Narrow or page through the window for a complete list.
- For a custom session ID, use the exact typed filter below. Session IDs do not
  have to be UUIDs.

Use this query for a UUID-shaped session. For an occurrence, replace the
session predicate with `uuid = '<occurrence_uuid>'` and use `LIMIT 1`. Put only
a validated UUID in either SQL literal.

```sql
posthog:execute-sql
SELECT
    uuid,
    issue_id,
    timestamp,
    properties.$session_id AS session_id,
    properties.$trace_id AS trace_id,
    properties.$span_id AS span_id
FROM events
WHERE event = '$exception'
    AND $session_id = '<session_uuid>'
    AND timestamp >= now() - INTERVAL 30 DAY
ORDER BY timestamp DESC
LIMIT 21
```

For a custom session ID, call `posthog:query-error-tracking-issues-list`
without putting the ID in SQL:

```json
{
  "dateRange": { "date_from": "-30d" },
  "status": "all",
  "filterTestAccounts": false,
  "filterGroup": [{ "key": "$session_id", "type": "event", "operator": "exact", "value": "<session_id>" }],
  "limit": 20
}
```

For each returned issue, call `posthog:query-error-tracking-issue-events` with
the same `dateRange` and `filterGroup`, `filterTestAccounts: false`,
`include: ["exception", "correlation"]`, and a small `limit`. Page with
`offset` if `hasMore` is true and more results matter. Otherwise, state the
limit. This path covers grouped issues and sampled events; say that it may
miss ungrouped exceptions.
