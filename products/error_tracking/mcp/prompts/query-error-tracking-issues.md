Query error tracking issues to find, filter, and inspect errors in the project. Returns aggregated metrics per issue including occurrence count, affected users, sessions, and volume data.

Use 'read-data-schema' to discover available events, actions, and properties for filters.

This is a unified query tool — use it both to list issues and to get details on a specific issue:

- **List issues**: omit `issueId` to get a filtered, sorted list of error tracking issues.
- **Get issue details**: provide `issueId` to get aggregated metrics for a single issue.

Use `error-tracking-issues-retrieve` to get the full issue model (description, assignee, external references) and `error-tracking-issues-partial-update` to change status or assignee.

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

# Data narrowing

## Property filters

Use property filters via the `filterGroup` field to narrow results. Only include property filters when they are essential to directly answer the user's question. Avoid adding them if the question can be addressed without additional filtering and always use the minimum set of property filters needed.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you should:

- **Prioritize properties directly related to the context or objective of the user's query.** Avoid using properties for identification like IDs. Instead, prioritize filtering based on general properties like `$browser`, `$os`, or `$geoip_country_code`.
- **Ensure that you find both the property group and name.** Property groups should be one of the following: event, person, session, group.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`).
- If the operator requires a value, use the `read-data-schema` tool to find the property values.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group.

Supported operators for the String type are:

- equals (exact)
- doesn't equal (is_not)
- contains (icontains)
- doesn't contain (not_icontains)
- matches regex (regex)
- doesn't match regex (not_regex)
- is set
- is not set

Supported operators for the Numeric type are:

- equals (exact)
- doesn't equal (is_not)
- greater than (gt)
- less than (lt)
- is set
- is not set

Supported operators for the DateTime type are:

- equals (is_date_exact)
- doesn't equal (is_not for existence check)
- before (is_date_before)
- after (is_date_after)
- is set
- is not set

Supported operators for the Boolean type are:

- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values (as an array).

## Time period

You should not filter events by time using property filters. Instead, use the `dateRange` field. If the question doesn't mention time, the default is the last 7 days.

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

## filterGroup

A flat list of property filters to narrow results. Each filter specifies a property key, operator, type (event/person/session/group), and value. See the "Property filters" section above for usage guidelines and supported operators.

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

## Errors from Chrome users only

```json
{
  "filterGroup": [{ "key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"] }]
}
```

## Errors from US users in the last 30 days

```json
{
  "filterGroup": [{ "key": "$geoip_country_code", "operator": "exact", "type": "event", "value": ["US"] }],
  "dateRange": { "date_from": "-30d" }
}
```

# Session recordings

Each error issue is linked to sessions via `$session_id` on the underlying `$exception` events. When a user asks "what were they doing," "can I see what happened," or wants visual context for an error, fetch the session recording.

If you have specific `$session_id` values from event data, use `query-session-recordings-list` with the `session_ids` parameter to fetch multiple recordings in a single call. Otherwise, use `query-session-recordings-list` with an event filter for `$exception` matching the error. If a specific person is involved, also filter by `person_uuid` to see all their sessions. If no person context is available, filter by `$exception` alone to find all sessions with that error. Use `date_from` to match the issue's time range — e.g., if the error was first seen 10 days ago, set `date_from` accordingly so recordings from that period are included.

# Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution.
