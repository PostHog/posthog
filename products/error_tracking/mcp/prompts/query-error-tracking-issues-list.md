List error tracking issues to find, filter, and prioritize errors in the project. Returns compact issue rows with aggregate counts, not stack traces or full event payloads.

Use `query-error-tracking-issue` with an issue ID from this tool to inspect one issue's metadata, impact, top in_app application frame, and latest release. Use `query-error-tracking-issue-events` only when you need a sample exception event or stack trace.

CRITICAL: Be minimalist. Defaults are usually enough: active issues, last 7 days, sorted by occurrences, compact counts only.

# Parameters

## status

Filter by issue status. Available values: `active`, `resolved`, `suppressed`, `pending_release`, `archived`, `all`. Defaults to `active`.

## orderBy

Sort by `occurrences`, `last_seen`, `first_seen`, `users`, or `sessions`. Defaults to `occurrences`.

## searchQuery

Free-text search across exception type, message, and stack frames. Use this when the user names a specific error.

## Common filters

Prefer these typed fields over `filterGroup` when they fit:

- `library`: SDK/library from `$lib`, for example `posthog-js`, `posthog-node`, or `posthog-android`.
- `release`: exact release ID, version, or git commit ID from `$exception_releases`.
- `fingerprint`: exact `$exception_fingerprint` hash.
- `user`: user/email search text.
- `personId`: exact PostHog person UUID.
- `url`: substring match against `$current_url`.
- `filePath`: stack-frame source/file path search text.

## filterGroup

A flat list of property filters. Filters are combined with AND. Nested `AND`/`OR` filter groups are not accepted by this MCP tool; use one `exact` filter with multiple values when you need "any of these values" for the same property.

Use `searchQuery` for exception text, type, message, and stack-frame searches. Use the typed fields above for common error-tracking filters. Use `filterGroup` only for less common structured event/person/session properties.

Each filter has:

- `type`: usually `event`, `person`, or `session`. `group`, `cohort`, `hogql`, `feature`, and `flag` are also supported when you have a known property.
- `key`: property name, for example `$browser`, `$os`, `$current_url`, `$lib`, `email`, or a custom property.
- `operator`: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`, `gt`, `lt`, `is_date_exact`, `is_date_before`, `is_date_after`, `is_set`, or `is_not_set`.
- `value`: string, number, boolean string, or array of strings depending on the operator. Omit `value` for `is_set` / `is_not_set`.

When `read-data-schema` is available, use it to discover property names and values before guessing. If it is not available in the connected MCP tool set, only use well-known SDK/system properties or properties the user explicitly provided.

## volumeResolution

Defaults to `0` for compact aggregate counts. Use a nonzero value only when the user asks for volume buckets or sparkline-like data.

## limit / offset

Defaults to 25. Use `nextOffset` from the previous response to fetch the next page.

# Examples

## Top active errors

```json
{}
```

## Recent resolved errors

```json
{
  "status": "resolved",
  "dateRange": { "date_from": "-30d" },
  "orderBy": "last_seen"
}
```

## Search for a specific exception

```json
{
  "searchQuery": "TypeError: Cannot read property",
  "limit": 10
}
```

## Filter by library and URL

```json
{
  "library": "posthog-js",
  "url": "/checkout"
}
```

## Filter by fingerprint and file path

```json
{
  "fingerprint": "012a0ac2ab9ad1a858f753798c0e7d92ed2075bd861416a93faf4414021079af18873b1e07729870c94fe3fd4b789a29118772ce39eab9a7637e5d181d7fbc8e",
  "filePath": "src/components/Checkout.tsx"
}
```

# Session recordings

Each error issue is linked to sessions via `$session_id` on the underlying `$exception` events. When a user asks "what were they doing," "can I see what happened," or wants visual context for an error, fetch the session recording.

Use `query-error-tracking-issue-events` to fetch sample exception events for the issue; those event samples include `$session_id` when available. Then use `query-session-recordings-list` with the `session_ids` parameter to fetch multiple recordings in one call. If no `$session_id` is available, use `query-session-recordings-list` with an event filter for `$exception` matching the error, and set `date_from` to cover the issue's time range.
