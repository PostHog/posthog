---
name: linking-errors-to-traces
description: >
  Links a PostHog error occurrence or session's errors to OpenTelemetry traces, logs with the
  same trace ID, and Session Replay. Use when the user asks for trace or span IDs on an error,
  same-trace logs, or backend traces for errors in a session. Starts from an occurrence UUID,
  session ID, or error tracking issue URL. For a general issue diagnosis or replay summary,
  use investigating-error-issue or investigating-replay.
---

# Link errors to traces and logs

Use a shared ID to connect records. A matching service and time do not prove
that a log or span belongs to an error.

## Find the exception

- For an issue ID or URL, call
  `posthog:query-error-tracking-issue-events` with
  `include: ["exception", "correlation"]`, `filterTestAccounts: false`,
  and a small `limit`. Choose one occurrence unless the user asks for several.
  Say when the result is a sample.
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

Use the user's time range when given. If no event appears, state the window you checked.
Do not claim that an event never existed based on a bounded search.

## Follow the IDs

1. **Replay:** If the event has `$session_id`, call
   `posthog:session-recording-get` with that ID. `found: false` means no
   recording was found; the error or session may still exist. Use
   `posthog:generate-app-url` with `/replay/{id}` when a recording exists.
2. **Exact trace:** For each unique, nonzero, 32-character hex `$trace_id`,
   call `posthog:apm-trace-get` with that ID and `excludeAttributes: true`.
   Use its `_posthogUrl` for the trace link. If the event has `$span_id`,
   compare it with returned span IDs as hex, ignoring case. An empty result
   means no retained span was found for that trace ID. Logs may still exist.
3. **Session trace candidates:** If an event lacks `$trace_id` and the user
   asked about session traces, use `posthog:apm-attributes-list` to find a
   span attribute that stores the session ID. If a clear key exists, call
   `posthog:query-apm-spans` with an exact `span_attribute` filter, a short
   window around the error, `flatSpans: true`, and a small `limit`. This finds
   matching child spans as well as root spans. Call `posthog:apm-trace-get`
   for a candidate that needs a link. Label these as session matches. Time
   alone does not prove which request raised the error.
4. **Same-trace logs:** For each unique trace ID, run the bounded SQL query
   below to find services with logs for that trace, even when retained spans
   name some services. Add any service names from the retained trace.
   `logs-attribute-values-list` cannot filter service values by trace ID.
   Call `posthog:logs-count`, then `posthog:query-logs` with the same trace ID,
   services, and time window. Include every severity, including `info`. If no
   service is found, do not make an unscoped log query.

Raw `logs.trace_id` values use base64. Convert the validated hex ID in the
predicate, and use a short time window around the error. The 21st row shows
when the first 20 services are incomplete. Narrow the window and retry if a
complete list matters; otherwise report the limit.

```sql
posthog:execute-sql
SELECT service_name, count() AS log_count
FROM logs
WHERE trace_id = base64Encode(unhex('<trace_id>'))
    AND timestamp >= '<before_error>'
    AND timestamp < '<after_error>'
GROUP BY service_name
ORDER BY log_count DESC
LIMIT 21
```

For `posthog:query-logs`, use this filter shape. Use the same filters without
`limit` for `posthog:logs-count`. Keep the row limit small and narrow the
window if the count is large.

```json
{
  "query": {
    "serviceNames": ["<service_name>"],
    "dateRange": { "date_from": "<before_error>", "date_to": "<after_error>" },
    "filterGroup": [
      {
        "key": "trace_id",
        "type": "log",
        "operator": "exact",
        "value": "<trace_id>"
      }
    ],
    "limit": 50
  }
}
```

Use `posthog:generate-app-url` with `/error_tracking/{id}` when the issue ID is known.
Do not build PostHog links by hand.

## Report the result

For each checked occurrence, show the error time, IDs used for the join, and
links to the issue, replay, and retained trace when available. Summarize
matching logs with their time and severity. Exclude secrets and unneeded
personal data from log excerpts.

Name each gap separately: no trace ID on the event, trace ID but no retained
span, no session attribute on spans, no recording, or no logs with that trace
ID in the checked window. A session-matched span is a candidate until an
exact trace or span ID connects it to the error. State any row limit or time
range that kept the search from being complete. If a lookup fails, say that its
result is unknown instead of reporting that no matching data exists.
