Query error tracking issues to find, filter, and inspect errors in the project. Returns aggregated metrics per issue including occurrence count, affected users, sessions, and volume data.

This is a unified query tool — use it both to list issues and to get details on a specific issue:

- **List issues**: omit `issueId` to get a filtered, sorted list of error tracking issues.
- **Get issue details**: provide `issueId` to get aggregated metrics for a single issue.

Use `error-tracking-issues-retrieve` to get the full issue model (description, assignee, external references) and `error-tracking-issues-partial-update` to change status or assignee.

# Parameters

## issueId (optional)

When provided, returns aggregated metrics for a single error tracking issue. When omitted, returns a paginated list of issues matching the filters.

## status

Filter by issue status. Available values: `active`, `resolved`, `suppressed`, `pending_release`, `archived`, `all`. Defaults to `active`.

## orderBy

Field to sort results by: `occurrences`, `last_seen`, `first_seen`, `users`, `sessions`. Defaults to `occurrences`.

## searchQuery

Free-text search across exception type, message, and stack frames. Use this when the user is looking for a specific error by name or message content.

## assignee

Filter issues by assignee. The value is a user ID. Use this when the user asks to see errors assigned to a specific person.

## volumeResolution

Controls the granularity of the volume chart data returned with each issue. Use `1` (default) for list views where you want a volume sparkline. Use `0` when you only need aggregate counts without volume data.

## dateRange

Date range to filter results. Defaults to the last 7 days (`-7d`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps (e.g., `2024-01-15T00:00:00Z`) or relative formats: `-7d`, `-2w`, `-1m`, `-1h`, `-1mStart`, `-1yStart`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## limit / offset

Pagination controls. `limit` defaults to 50.

# Examples

## List all active errors sorted by occurrence count

```json
{}
```

All defaults apply: `status: "active"`, `orderBy: "occurrences"`, `dateRange: { "date_from": "-7d" }`.

## Search for a specific error

```json
{
  "searchQuery": "TypeError: Cannot read property",
  "limit": 10
}
```

## Get details for a specific issue

```json
{
  "issueId": "01234567-89ab-cdef-0123-456789abcdef",
  "volumeResolution": 0
}
```

## List resolved errors from the last 30 days

```json
{
  "status": "resolved",
  "dateRange": { "date_from": "-30d" },
  "orderBy": "last_seen"
}
```

## Find most recent errors

```json
{
  "orderBy": "first_seen",
  "orderDirection": "DESC",
  "dateRange": { "date_from": "-24h" }
}
```
