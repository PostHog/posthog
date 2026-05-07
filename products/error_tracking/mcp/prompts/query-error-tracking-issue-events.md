Fetch sampled `$exception` events for one Error tracking issue.

Use this when the user asks for concrete examples, stack traces, affected URLs, browser/OS/library context, or Session replay links for a specific issue.

Returns sampled events with plural exception fields (`$exception_types`, `$exception_values`), normalized `$exception_list`, `$exception_fingerprint`, `$exception_issue_id`, `$session_id`, `$lib`, browser/OS fields, and `$current_url`.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for sampled events. Defaults to last 7 days.
- `searchQuery`: search exception types, values, and current URL.
- `filterGroup`: advanced flat AND property filters applied to sampled events.
- `verbosity`: `summary` (default), `stack`, or `raw`. Use `raw` only when exact untruncated exception payloads are needed.
- `onlyAppFrames`: defaults to true to reduce vendor-frame noise.
- `limit`: defaults to 1 and maxes at 20. Keep low unless the user asks for multiple examples.

# Session recordings

When `$session_id` is present and the user asks what happened before the error, call `query-session-recordings-list` with `session_ids` to fetch matching recordings. Use multiple `$session_id` values in one call when available.
