Get compact details for one Error tracking issue.

Use this after `query-error-tracking-issues-list` when you have an `issueId` and need issue status, severity, name/description, first/last seen timestamps, assignee, compact impact counts, top in-app frame, and latest release metadata.

Defaults are intentionally useful: last 7 days, test accounts filtered out, aggregate impact included, and no sparkline unless requested.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for impact counts and latest-event metadata. Defaults to last 7 days.
- `includeSparkline`: set true only if a trend/sparkline helps answer the user. When true, `volumeResolution` defaults to 12 if not provided.
- `volumeResolution`: number of volume buckets when sparkline data is needed.
- `includeBreakdown`: set true when the user asks where, for whom, or on which platforms the issue happens. It adds one aggregate over all matching events: the most common paths, screens, browsers, OS, libraries, library versions, and app versions with a count for each, the number of events with a `$session_id`, and up to 5 sample `$session_id` values. It covers at most the last 30 days of `dateRange`; `range_limited` is true when it covers less than you asked for. Empty dimensions are left out.

# Next steps

Use `query-error-tracking-issue-events` with the same `issueId` only when the user needs a concrete event, a stack trace, code variables, OpenTelemetry trace IDs, or the handled flag. Do not fetch many events to count browsers, URLs, or versions; use `includeBreakdown` instead.

When `sample_session_ids` is not empty and the user asks what happened before the error, call `query-session-recordings-list` with `session_ids`.
