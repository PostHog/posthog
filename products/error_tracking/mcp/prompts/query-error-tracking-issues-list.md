List and filter Error tracking issues. Returns compact issue rows with aggregate impact counts (`occurrences`, `users`, `sessions`) and optional volume buckets.

Use this first when the user asks which errors are happening, which errors are most common, or wants to narrow issues by status, severity, release, library, fingerprint, URL, user, person, or properties.

Defaults are intentionally useful: active issues, last 7 days, sorted by occurrences, test accounts filtered out, 10 rows per page, and compact aggregate counts. Each row carries a short `description` preview. Use `query-error-tracking-issue` for the full description.

Keep `limit` small. When `hasMore` is true and you need more rows, fetch the next page with `offset` set to `nextOffset`. Set `volumeResolution` only when the user asks for volume over time. It is an integer count of equal-width buckets across `dateRange`, from 0 to 200, not a unit such as `hour` or `day`. For daily volume over the default 7-day range, send `7`. For hourly volume over the last 24 hours, send `24` with `dateRange.date_from` set to `-24h`.

For all-time issue counts by status or severity, query `system.error_tracking_issues` with `posthog:execute-sql`. The table follows the connected user's Error tracking access and only returns issues from the current project. This list tool only includes issues observed during `dateRange`.

Be minimalist. Only add filters needed to answer the user’s question. Do not add "is set" filters unless the user explicitly asks for them.

# Common filters

- `status`: `active`, `resolved`, `suppressed`, `pending_release`, `archived`, or `all`. Defaults to `active`.
- `searchQuery`: free-text search for exception names, values, stack frames, and email text.
- `library`: exact `$lib` match, for example `posthog-js`.
- `release`: exact release ID, release version, or git commit ID captured in `$exception_releases`. This intentionally does not match project name, branch, or timestamp fragments.
- `fingerprint`: exact `$exception_fingerprint` match.
- `url`: substring match on `$current_url`.
- `personId`: exact PostHog person UUID.
- `user`: user/email text search.
- `filePath`: stack-frame file/source text search.
- `filterGroup`: advanced flat AND property filters. Prefer typed fields above when they fit. For severity, use type `error_tracking_issue`, key `severity`, and `exact`, `is_set`, or `is_not_set`.

Use `dateRange` for time, not property filters. Omit `date_to` for now.

# Next steps

- Use `query-error-tracking-issue` with `issueId` to inspect one issue.
- Use `query-error-tracking-issue-events` with `issueId` to fetch sampled exception events, stack traces, URLs, and `$session_id` values.
- If the user asks what people were doing before the error, use `$session_id` values from issue events with `query-session-recordings-list` and its `session_ids` parameter.
