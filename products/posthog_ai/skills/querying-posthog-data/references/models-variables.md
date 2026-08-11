# SQL Variables and Filters

## Variables

Variables enable dynamic value injection in HogQL queries using `{variables.<code_name>}` syntax.

### Schema (`system.insight_variables`)

Column | Type | Description
`id` | uuid | Primary key
`name` | varchar(400) | Display name in UI
`code_name` | varchar(400) | Query key (auto-generated from name)
`type` | varchar(128) | `String`, `Number`, `Boolean`, `List`, or `Date`
`default_value` | jsonb | Default value
`values` | jsonb | Available values (List type only)
`is_multi` | boolean | Whether a List variable accepts multiple selected values
`values_query` | text | HogQL query whose first result column supplies List options
`values_query_connection_id` | text | External data source connection `values_query` runs against (null for PostHog)

### Types

Type | Example `default_value`
`String` | `"example"`
`Number` | `42`
`Boolean` | `true`
`List` | `"$pageview"` or `["$pageview", "$autocapture"]` when `is_multi` is enabled
`Date` | `"2024-01-01"` or a rolling value such as `"-7d"`

### Usage

```sql
-- Basic
SELECT * FROM events WHERE event = {variables.event_names}

-- Optional string (empty check)
WHERE (coalesce({variables.org}, '') = '' OR properties.org = {variables.org})

-- Optional nullable (null check)
WHERE ({variables.browser} IS NULL OR properties.$browser = {variables.browser})

-- Multiselect List variable
WHERE event IN {variables.event_names}
```

List options can be entered manually or loaded from a HogQL query. For query-backed options, the first result column becomes the option values, and an optional second column supplies their display labels. Queries without a `LIMIT` return at most 100 rows, and the UI keeps at most 1000 options. The query can run against an external data source connection via `values_query_connection_id`.

Relative Date defaults resolve each time a query runs. For example, `-7d` means seven days before the current time.

### code_name Generation

Auto-generated from `name`: strips non-alphanumeric characters (except spaces/underscores), replaces spaces with underscores, lowercases. Example: `"Event Names"` -> `"event_names"`

### Queries

```sql
-- List all
SELECT id, name, code_name, type, default_value FROM system.insight_variables

-- Find by name
SELECT * FROM system.insight_variables WHERE name ILIKE '%event%'

-- Find by type
SELECT * FROM system.insight_variables WHERE type = 'List'

-- Get by code_name
SELECT * FROM system.insight_variables WHERE code_name = 'event_names'
```

---

## Filter Placeholders

Dashboard/query-level filters injected into HogQL queries.

### Available Placeholders

Placeholder | Description | When not set
`{filters}` | Full filter expression | Returns `TRUE`
`{filters.dateRange.from}` | Start date/time | Comparison skipped
`{filters.dateRange.to}` | End date/time | Comparison skipped

### Usage

```sql
-- Full filter (includes properties, date range, test account exclusions)
SELECT * FROM events WHERE {filters}

-- Direct date access
SELECT * FROM events
WHERE timestamp >= {filters.dateRange.from}
  AND timestamp < {filters.dateRange.to}

-- Combined with variables
SELECT * FROM events
WHERE event = {variables.event_names}
  AND timestamp >= {filters.dateRange.from}
```

### Notes

- `filterTestAccounts` and `properties` only apply via `{filters}`, not directly accessible
- Date values support ISO format (`2024-01-01`) and relative strings (`-7d`, `-1w`)
- When unset, date comparisons become `TRUE = TRUE`

### Table-Specific Behavior

Table | Timestamp field
`events` | `timestamp`
`sessions` | `$start_timestamp`
`logs` / `log_attributes` | `timestamp`
`groups` | `created_at`
