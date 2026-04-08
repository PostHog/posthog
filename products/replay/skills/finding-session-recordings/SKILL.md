---
name: finding-session-recordings
description: >
  Find session recordings via MCP by converting natural language queries into recording filters.
  Use when the user asks to find, search, or list session recordings by person, URL, date, device,
  browser, location, errors, or any other criteria. Covers filter construction, property discovery,
  and common search patterns.
---

# Finding session recordings with MCP tools

## Available tools

| Tool                                 | Purpose                                           |
| ------------------------------------ | ------------------------------------------------- |
| `posthog:session-recordings-list`    | Search recordings with filters                    |
| `posthog:session-recordings-retrieve`| Get a single recording by session ID              |
| `posthog:read-data-schema`           | Discover available properties and their values     |
| `posthog:execute-sql`                | Find session IDs via SQL when filters aren't enough|

## Workflow: natural language to recording filters

### Step 1 — Identify what the user wants to filter on

Map the user's request to filter categories:

| User says                                    | Filter type      | Parameter         |
| -------------------------------------------- | ---------------- | ----------------- |
| "recordings from user X"                     | Person           | `properties`      |
| "recordings visiting /pricing"               | Event property   | `events`          |
| "recordings from mobile devices"             | Session property | `properties`      |
| "recordings with console errors"             | Recording metric | `properties`      |
| "recordings from the US"                     | Person property  | `properties`      |
| "recording for session ABC"                  | Session ID       | `session_ids`     |
| "recordings from last week"                  | Date range       | `date_from`       |
| "recordings where users clicked Sign Up"     | Element property | `events`          |

### Step 2 — Discover properties with read_taxonomy

Before constructing filters, **always verify property names and values exist** using `posthog:read-data-schema`:

```
posthog:read-data-schema { kind: "session_properties" }
posthog:read-data-schema { kind: "person_properties" }
posthog:read-data-schema { kind: "event_properties", event_name: "$pageview" }
posthog:read-data-schema { kind: "event_property_values", event_name: "$pageview", property_name: "$current_url" }
```

**Common properties you can use without discovery:**
- **Session**: `$device_type`, `$browser`, `$os`, `$channel_type`, `$entry_current_url`, `$entry_pathname`, `$is_bounce`, `$pageview_count`
- **Person**: `$geoip_country_code`, `$geoip_city_name`, email (custom)
- **Event**: `$current_url`, `$pathname`, `$event_type`
- **Recording** (built-in metrics, no discovery needed): `console_error_count`, `click_count`, `keypress_count`, `mouse_activity_count`, `activity_score`

### Step 3 — Construct the filter query params

The `session-recordings-list` tool accepts query parameters. Complex types are JSON-encoded strings.

#### Simple filters (scalar query params)

```
session_ids: '["session-abc-123"]'
person_uuid: "0190abcd-1234-7000-8000-abcdef123456"
date_from: "-7d"
date_to: null
order: "start_time"
order_direction: "DESC"
filter_test_accounts: true
```

#### Property filters

The `properties` parameter accepts a JSON array of filter objects:

```json
[
  {
    "key": "$browser",
    "type": "person",
    "value": ["Chrome"],
    "operator": "exact"
  }
]
```

**Filter types:**
- `person` — person properties (browser, country, email, custom fields)
- `session` — session-level properties (device type, OS, entry URL)
- `event` — event properties (current URL, pathname)
- `recording` — recording metrics (console_error_count, click_count, activity_score)
- `cohort` — cohort membership (`key: "id"`, `value: <cohort_id>`)
- `group` — group properties
- `hogql` — raw HogQL expression

**Operators by data type:**
- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`, `is_set`, `is_not_set`
- Numeric: `exact`, `is_not`, `gt`, `gte`, `lt`, `lte`, `is_set`, `is_not_set`
- Boolean: `exact`, `is_not`, `is_set`, `is_not_set`

#### Event filters

The `events` parameter matches recordings containing at least one matching event:

```json
[
  {
    "id": "$pageview",
    "type": "events",
    "properties": [
      {
        "key": "$current_url",
        "type": "event",
        "value": "/pricing",
        "operator": "icontains"
      }
    ]
  }
]
```

For autocaptured interactions (clicks on specific elements):

```json
[
  {
    "id": "$autocapture",
    "type": "events",
    "properties": [
      {
        "key": "text",
        "type": "element",
        "value": "Sign Up",
        "operator": "icontains"
      }
    ]
  }
]
```

Valid element property keys: `tag_name`, `text`, `href`, `selector`.

#### Console log filters

```json
[
  {
    "key": "level",
    "type": "log_entry",
    "value": ["error"],
    "operator": "exact"
  }
]
```

### Step 4 — Call the tool

Combine the filters into a single tool call:

```
posthog:session-recordings-list {
  date_from: "-7d",
  filter_test_accounts: true,
  properties: '[{"key":"$geoip_country_code","type":"person","value":["US"],"operator":"exact"}]',
  events: '[{"id":"$pageview","type":"events","properties":[{"key":"$current_url","type":"event","value":"/pricing","operator":"icontains"}]}]',
  order: "activity_score",
  order_direction: "DESC"
}
```

## Common patterns

### Find recordings by URL visited

```
posthog:session-recordings-list {
  date_from: "-7d",
  events: '[{"id":"$pageview","type":"events","properties":[{"key":"$current_url","type":"event","value":"<url_pattern>","operator":"icontains"}]}]'
}
```

### Find recordings by person email

First discover the email property name, then filter:

```
posthog:session-recordings-list {
  date_from: "-7d",
  properties: '[{"key":"email","type":"person","value":["user@example.com"],"operator":"exact"}]'
}
```

### Find recordings with errors sorted by error count

```
posthog:session-recordings-list {
  date_from: "-7d",
  properties: '[{"key":"console_error_count","type":"recording","value":[0],"operator":"gt"}]',
  order: "console_error_count",
  order_direction: "DESC"
}
```

### Find recordings by partial session ID or UUID match

When the user provides a partial ID (like a booking UUID `3bf9166b-5231-4406-b4e6-c1a86f5b17b7`),
use SQL to find matching session IDs first, then fetch recordings:

```sql
SELECT DISTINCT $session_id
FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY
  AND properties.$current_url ILIKE '%3bf9166b-5231-4406-b4e6-c1a86f5b17b7%'
LIMIT 20
```

Then pass the results to the list tool:

```
posthog:session-recordings-list {
  session_ids: '["found-session-id-1","found-session-id-2"]',
  date_from: "-7d"
}
```

### Find recordings from mobile users in a specific country

```
posthog:session-recordings-list {
  date_from: "-7d",
  filter_test_accounts: true,
  properties: '[{"key":"$device_type","type":"session","value":["Mobile"],"operator":"exact"},{"key":"$geoip_country_code","type":"person","value":["US"],"operator":"exact"}]'
}
```

### Find frustrated users (rageclicks)

```
posthog:session-recordings-list {
  date_from: "-7d",
  events: '[{"id":"$rageclick","type":"events"}]',
  order: "activity_score",
  order_direction: "DESC"
}
```

## Important notes

- **Default date range is 3 days.** Always set `date_from` explicitly for broader searches.
- **Recording properties are NOT events.** `console_error_count`, `click_count`, etc. use `type: "recording"`, not event filters.
- **Element filters go inside event filters**, not at the top level. Only use for `$autocapture` or `$rageclick` events.
- **Use `icontains` for URLs** to handle query params and trailing slashes.
- **Use `exact` for enumerated values** like device type, browser, country codes.
- The response includes a link to watch each recording in PostHog.
