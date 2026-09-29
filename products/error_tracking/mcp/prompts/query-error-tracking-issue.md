Get compact details for one Error tracking issue.

Use this after `query-error-tracking-issues-list` when you have an `issueId` and need issue status, severity, name/description, first/last seen timestamps, assignee, compact impact counts, top in-app frame, and latest release metadata.

Defaults are intentionally useful: last 7 days, test accounts filtered out, aggregate impact included, and no sparkline unless requested.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for impact counts and latest-event metadata. Defaults to last 7 days. Without `date_from`, the range starts 7 days before `date_to`. A relative `date_to` such as `-1d` counts back from now. A date-only `date_to` such as `2026-01-31` includes that whole day. Dates without an offset use the project timezone.
- `includeSparkline`: set true only if a trend/sparkline helps answer the user. When true, `volumeResolution` defaults to 12 if not provided.
- `volumeResolution`: number of volume buckets when sparkline data is needed.

# Response

- `dateRange` echoes the resolved `date_from`, `date_to`, and `timezone` that the impact counts use.
- `impact` holds `occurrences`, `users`, and `sessions` for that range. Counts of 0 mean the issue has no matching events in the range.

# Next steps

Use `query-error-tracking-issue-events` with the same `issueId` when the user needs concrete event examples, stack traces, browser/OS/URL context, or `$session_id` values for Session replay.
