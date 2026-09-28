Fetch sampled `$exception` events for one Error tracking issue.

Use this when the user asks for concrete examples, stack traces, code variables, affected URLs, browser/OS/library context, release details, diagnostics, or Session replay links for a specific issue.

Returns sampled events with plural exception fields (`$exception_types`, `$exception_values`), normalized `$exception_list`, `$exception_fingerprint`, `$exception_level`, `$exception_handled`, `$session_id`, OpenTelemetry and AI trace/span IDs, `$lib`, browser/OS fields, and `$current_url`.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for sampled events. Defaults to last 7 days.
- `searchQuery`: search exception types, values, and current URL.
- `filterGroup`: advanced flat AND property filters applied to sampled events.
- `include`: context groups to return. Defaults to compact exception, environment, navigation, and correlation context. Add `stacktrace`, `code_variables`, `release`, or `diagnostics` only when needed. `code_variables` implies stack frames and may contain SDK-masked sensitive values.
- `onlyAppFrames`: defaults to true to reduce vendor-frame noise.
- `limit`: defaults to 1 and maxes at 20. Keep low unless the user asks for multiple examples.

# Stack traces

- A stack trace keeps at most the 50 frames closest to the error. `frames_omitted` gives the number of older frames that were left out.
- When a stack trace is the same as one returned earlier on the page, its `stacktrace` is `{"same_as_event": "<uuid>", "same_as_exception": <index>}`. Read the frames from that event, at that index of its `$exception_list`. The event can be the same event, when two of its exceptions share a stack.

# Session recordings

When `$session_id` is present and the user asks what happened before the error, call `query-session-recordings-list` with `session_ids` to fetch matching recordings. Use multiple `$session_id` values in one call when available.
