# Endpoints

## Endpoint (`system.endpoints`)

API endpoints that expose saved HogQL or insight queries as callable API routes.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`name` | varchar(128) | NOT NULL | URL-safe endpoint name (unique per team)
`is_active` | integer | NOT NULL | Whether endpoint is available via the API (0/1)
`current_version` | integer | NOT NULL | Latest version number
`derived_from_insight` | varchar(12) | NULL | Short ID of the source insight
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`last_executed_at` | timestamp with tz | NULL | When endpoint was last executed
`deleted` | integer | NOT NULL | Soft delete flag (0 = active, 1 = deleted)

### Example Queries

    -- List all active endpoints with their current version
    SELECT name, is_active, current_version
    FROM system.endpoints
    WHERE is_active = 1 AND deleted = 0

    -- Find endpoints that haven't been executed recently
    SELECT name, last_executed_at
    FROM system.endpoints
    WHERE last_executed_at < now() - INTERVAL 30 DAY AND deleted = 0

    -- Join with versions to get current version description
    SELECT e.name, ev.description, ev.version
    FROM system.endpoints e
    LEFT JOIN system.endpoint_versions ev
      ON ev.endpoint_id = e.id AND ev.version = e.current_version
    WHERE e.deleted = 0

### Important Notes

- Endpoints are looked up by `name`, not `id`
- Use `system.endpoint_versions` to access version-specific details
- Boolean fields (`is_active`, `deleted`) are exposed as integers (0/1) for HogQL compatibility

---

## Endpoint Version (`system.endpoint_versions`)

Immutable query snapshots.
A new version is created each time an endpoint's query changes.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`endpoint_id` | uuid | NOT NULL | FK to endpoints.id
`version` | integer | NOT NULL | Version number (1-based, ascending)
`description` | text | NOT NULL | Version description
`query` | jsonb | NOT NULL | Immutable query snapshot
`cache_age_seconds` | integer | NULL | Cache TTL in seconds
`is_active` | integer | NOT NULL | Whether this version can be executed (0/1)
`columns` | jsonb | NULL | Column names and types
`created_at` | timestamp with tz | NOT NULL | When this version was created

### Example Queries

    -- Get version history for an endpoint
    SELECT ev.version, ev.description, ev.created_at
    FROM system.endpoint_versions ev
    LEFT JOIN system.endpoints e ON e.id = ev.endpoint_id
    WHERE e.name = 'my-endpoint'
    ORDER BY ev.version DESC
