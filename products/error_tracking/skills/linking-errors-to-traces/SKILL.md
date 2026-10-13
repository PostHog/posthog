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

For an issue ID or URL, call `posthog:query-error-tracking-issue-events` with
`include: ["exception", "correlation"]`, `filterTestAccounts: false`, and a small
`limit`. Choose one occurrence unless the user asks for several. Say when the
result is a sample.

For an occurrence ID or session ID, read
[finding-exceptions.md](./references/finding-exceptions.md) for the exact lookup.
Use the user's time range when given. If no event appears, state the window
you checked. Do not claim that an event never existed based on a bounded search.

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
4. **Same-trace logs:** When an event has a trace ID, read
   [finding-trace-logs.md](./references/finding-trace-logs.md) for the bounded
   service lookup and exact log filter. Include every severity, including
   `info`. A trace can have logs even when no span was retained.

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
