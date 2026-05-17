Get compact details for one Error tracking issue.

Use this after `query-error-tracking-issues-list` when you have an `issueId` and need issue status, name/description, first/last seen timestamps, assignee, compact impact counts, top in-app frame, latest release metadata, and the latest session pivot.

Defaults are intentionally useful: last 7 days, test accounts filtered out, aggregate impact included, and no sparkline unless requested.

# Parameters

- `issueId`: required Error tracking issue UUID.
- `dateRange`: time range for impact counts and latest-event metadata. Defaults to last 7 days.
- `includeSparkline`: set true only if a trend/sparkline helps answer the user. When true, `volumeResolution` defaults to 12 if not provided.
- `volumeResolution`: number of volume buckets when sparkline data is needed.

# Response highlights

- `latest_session`: identifiers from the most recent exception event in the date range — `session_id` (pivot to Session replay), `distinct_id` (pivot to person/actor), `timestamp`, and `event_uuid`. Use this for a one-shot 'error → session → replay' jump without a follow-up tool call.
- `top_in_app_frame`, `latest_release`, `impact`, optional `sparkline`.

# Next steps

Use `query-error-tracking-issue-events` with the same `issueId` only when you need additional samples beyond the latest one — for example, multiple stack traces, multiple `$session_id` values across users, or browser/OS/URL spread. For a single representative session to drill into, `latest_session` on this response is enough.
