# Hog Functions

## Hog Function (`system.hog_functions`)

Hog functions are programmable event handlers in PostHog's CDP (Customer Data Platform). They process events in real time to send data to external destinations, transform events during ingestion, or run site-side apps.

### Function Types

- `destination` — sends event data to external services (Slack, webhooks, CRMs, etc.)
- `site_destination` — client-side destination running in the browser
- `internal_destination` — PostHog internal processing (e.g. triggering workflows)
- `source_webhook` — receives inbound webhooks and converts them to PostHog events
- `warehouse_source_webhook` — receives webhooks for data warehouse ingestion
- `site_app` — client-side app running in the browser (e.g. surveys, feedback widgets)
- `transformation` — modifies events during ingestion before they reach ClickHouse

### Columns

Column | Type | Nullable | Description
`id` | string (UUID) | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NULL | Display name
`description` | text | NOT NULL | What the function does
`type` | varchar(24) | NULL | Function type (see values above)
`enabled` | boolean | NOT NULL | Whether the function is active (1 = yes, 0 = no)
`deleted` | boolean | NOT NULL | Soft-delete flag (1 = deleted, 0 = active)
`icon_url` | text | NULL | URL for the function's icon
`template_id` | varchar(400) | NULL | ID of the template this function was created from
`execution_order` | integer | NULL | Execution priority for transformations (lower runs first)
`inputs_schema` | jsonb | NULL | Schema defining configurable input parameters
`filters` | jsonb | NULL | Event filters controlling which events trigger the function
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Query Examples

```sql
-- List all enabled destinations
SELECT id, name, template_id, updated_at
FROM system.hog_functions
WHERE type = 'destination' AND enabled = 1 AND deleted = 0
ORDER BY updated_at DESC

-- Count functions by type
SELECT type, count() AS total
FROM system.hog_functions
WHERE deleted = 0
GROUP BY type
ORDER BY total DESC

-- List transformations in execution order
SELECT id, name, execution_order, enabled
FROM system.hog_functions
WHERE type = 'transformation' AND deleted = 0
ORDER BY execution_order ASC

-- Find functions created from a specific template
SELECT id, name, enabled, created_at
FROM system.hog_functions
WHERE template_id = 'template-slack' AND deleted = 0

-- Find functions updated in the last 7 days
SELECT id, name, type, updated_at
FROM system.hog_functions
WHERE updated_at > now() - toIntervalDay(7) AND deleted = 0
ORDER BY updated_at DESC
```
