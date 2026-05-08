Get compact details for one Error tracking issue.

Use this after `query-error-tracking-issues-list` when you have an `issueId` and need issue status, name/description, first/last seen timestamps, assignee, compact impact counts, top in-app frame, and latest release metadata.

Defaults are intentionally useful: last 7 days, test accounts filtered out, aggregate impact included, and no sparkline unless requested.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for impact counts and latest-event metadata. Defaults to last 7 days.
- `includeSparkline`: set true only if a trend/sparkline helps answer the user. When true, `volumeResolution` defaults to 12 if not provided.
- `volumeResolution`: number of volume buckets when sparkline data is needed.

# Next steps

Use `query-error-tracking-issue-events` with the same `issueId` when the user needs concrete event examples, stack traces, browser/OS/URL context, or `$session_id` values for Session replay.
