Get compact details for one Error tracking issue.

Use this after `query-error-tracking-issues-list` when you have an `issueId` and need issue status, severity, name/description, first/last seen timestamps, assignee, compact impact counts, top in-app frame, and latest release metadata.

Defaults are intentionally useful: last 7 days, test accounts filtered out, aggregate impact included, and no sparkline unless requested.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for impact counts and latest-event metadata. Defaults to last 7 days.
- `includeSparkline`: set true only if a trend/sparkline helps answer the user. When true, `volumeResolution` defaults to 12 if not provided.
- `volumeResolution`: number of volume buckets when sparkline data is needed.

# Issue membership

- The name and description come from the event that created the issue. Later events and merged fingerprints can have different exception values.
- To count this issue in `query-trends` or `execute-sql`, filter on the HogQL expression `issue_id = toUUID('<issueId>')`, not on `$exception_fingerprint` or `$exception_issue_id`. Set the same date range and test account filter to get the same impact counts.

# Next steps

Use `query-error-tracking-issue-events` with the same `issueId` when the user needs concrete event examples, stack traces, browser/OS/URL context, or `$session_id` values for Session replay.
