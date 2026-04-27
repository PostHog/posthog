List session recordings in the project. Returns recording metadata including duration, activity counts, console errors, start URL, and interaction metrics. Use this tool to find, filter, and explore session recordings.

Use 'read-data-schema' to discover available person, session, and event properties for filtering.

Examples of use cases include:

- Find recordings with console errors in the last week
- Show me recordings from users in a specific country
- List the longest recordings from today
- Find recordings where users visited a specific page
- Show recordings with high activity scores
- Find recordings for a specific person

CRITICAL: Be minimalist. Only include filters and settings essential to answer the user's question. Default settings are usually sufficient.

# Property filters

Use property filters to narrow results. Only include filters directly relevant to the user's question.

When using a property filter, you should:

- **Prioritize properties directly related to the user's query.**
- **Ensure the correct filter type.** Types: `person`, `session`, `event`, `recording`, `cohort`.
- **Use `read-data-schema` to discover property names and values** before creating filters.

## Common properties

**Recording** (type: `recording`): `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `activity_score`. These are built-in metrics, not events.

**Session** (type: `session`): `$session_duration`, `$channel_type`, `$entry_current_url`, `$entry_pathname`, `$is_bounce`, `$pageview_count`.

**Person** (type: `person`): `$geoip_country_code`, `$geoip_city_name`, `email`, and custom person properties.

**Event** (type: `event`): `$current_url`, `$pathname`, `$browser`, `$os`, `$device_type`, `$screen_width`.

**Cohort** (type: `cohort`): scope recordings to persons belonging to a cohort. `key` is always `"id"`, `value` is the cohort ID, operator is `in` (or `not_in` to exclude). Example: `{ "type": "cohort", "key": "id", "value": 42, "operator": "in" }`. Use `cohorts-list` to find cohort IDs.

## Operators

**String**: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`, `is_set`, `is_not_set`
**Numeric**: `exact`, `is_not`, `gt`, `gte`, `lt`, `lte`, `is_set`, `is_not_set`
**DateTime**: `is_date_exact`, `is_date_before`, `is_date_after`, `is_set`, `is_not_set`
**Boolean**: `exact`, `is_not`, `is_set`, `is_not_set`

`exact` and `is_not` accept arrays of values. Use `icontains` for URLs, `exact` for enumerated values, `gt`/`lt` for counts.

# Ordering

Sort recordings by: `start_time` (default), `duration`, `activity_score`, `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `active_seconds`, `inactive_seconds`.

Default direction is `DESC` (newest/highest first).

# Date range

- `date_from`: Relative (`-7d`, `-24h`) or absolute (`2025-01-15`). Default: `-3d`.
- `date_to`: Relative or absolute. Default: now.

Do not use property filters for time-based filtering. Use the `date_from`/`date_to` fields instead.

# Pagination

Use `limit` to control page size and `after` (from the previous response's `next_cursor`) for cursor-based pagination.

# Response shape

Each recording in results contains:

- `id` — session recording ID
- `distinct_id` — the person's distinct ID
- `start_time` / `end_time` — recording time range (ISO 8601)
- `recording_duration` — length in seconds
- `active_seconds` / `inactive_seconds` — activity breakdown
- `click_count`, `keypress_count`, `mouse_activity_count` — interaction counts
- `console_log_count`, `console_warn_count`, `console_error_count` — console output counts
- `start_url` — first page URL visited
- `activity_score` — engagement score (higher = more active)
- `ongoing` — whether the session is still active

# Examples

## Recent recordings with console errors

```json
{
  "date_from": "-7d",
  "filter_test_accounts": true,
  "properties": [{ "key": "console_error_count", "operator": "gt", "type": "recording", "value": 0 }],
  "order": "console_error_count"
}
```

## Longest recordings today

```json
{
  "date_from": "-1d",
  "filter_test_accounts": true,
  "order": "duration",
  "limit": 10
}
```

## Recordings for a specific person

```json
{
  "date_from": "-30d",
  "person_uuid": "01234567-89ab-cdef-0123-456789abcdef",
  "filter_test_accounts": true
}
```

## Recordings from mobile users

```json
{
  "date_from": "-7d",
  "filter_test_accounts": true,
  "properties": [{ "key": "$device_type", "operator": "exact", "type": "event", "value": ["Mobile"] }]
}
```

## Recordings from a cohort of users

```json
{
  "date_from": "-7d",
  "filter_test_accounts": true,
  "properties": [{ "key": "id", "operator": "in", "type": "cohort", "value": 42 }]
}
```

# Reminders

- Use `filter_test_accounts: true` by default to exclude internal users.
- Only include property filters directly relevant to the user's question.
- Default time range is last 3 days. Adjust based on the user's needs.
- For detailed analysis of a single recording, use `session-recording-get` with the recording's `id`.
