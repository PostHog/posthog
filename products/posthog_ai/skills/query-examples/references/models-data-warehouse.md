# Data Warehouse

## External Data Source (`system.data_warehouse_sources`)

External data sources represent connections to third-party data providers (Stripe, Hubspot, Postgres, etc.) that sync data into PostHog.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`source_id` | varchar(400) | NOT NULL | External identifier for the source
`connection_id` | varchar(400) | NOT NULL | Connection identifier
`destination_id` | varchar(400) | NULL | Destination identifier
`source_type` | varchar(128) | NOT NULL | Type of source (Stripe, Hubspot, Postgres, etc.)
`status` | varchar(400) | NOT NULL | Current sync status
`prefix` | varchar(100) | NULL | Prefix applied to synced table names
`description` | varchar(400) | NULL | User-defined description
`are_tables_created` | boolean | NOT NULL | Whether tables have been created
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`deleted` | boolean | NOT NULL | Soft delete flag
`deleted_at` | timestamp with tz | NULL | Deletion timestamp

### Source Types

Common source types include:

- `Stripe` - Payment and subscription data
- `Hubspot` - CRM and marketing data
- `Postgres` - PostgreSQL databases
- `MySQL` - MySQL databases
- `Snowflake` - Snowflake data warehouse
- `BigQuery` - Google BigQuery
- `S3` - Amazon S3 files
- `Zendesk` - Customer support data
- `Salesforce` - CRM data

### Key Relationships

- **Tables**: One source can have many `system.data_warehouse_tables` entries

---

## Data Warehouse Table (`system.data_warehouse_tables`)

Individual tables synced from external sources or manually uploaded. Each table contains columns with their types and metadata.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`name` | varchar(128) | NOT NULL | Table name (may include prefix)
`columns` | jsonb | NULL | Column definitions with types
`row_count` | integer | NULL | Number of rows synced
`external_data_source_id` | uuid | NULL | FK to source
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`deleted` | boolean | NOT NULL | Soft delete flag
`deleted_at` | timestamp with tz | NULL | Deletion timestamp

### Columns JSON Structure

The `columns` field contains column definitions with their types:

```json
{
  "id": {
    "hogql": "IntegerDatabaseField",
    "clickhouse": "Int64",
    "valid": true
  },
  "email": {
    "hogql": "StringDatabaseField",
    "clickhouse": "Nullable(String)",
    "valid": true
  },
  "created_at": {
    "hogql": "DateTimeDatabaseField",
    "clickhouse": "DateTime64(3)",
    "valid": true
  }
}
```

### Key Relationships

- **Source**: `external_data_source_id` -> `system.data_warehouse_sources.id`

### Important Notes

- Table names may include source prefix (e.g., `stripe_customers` for Stripe source with no custom prefix)
- The `columns` field is synced from the actual data schema
- `valid: false` columns may have type mismatches or other issues
- Tables with `external_data_source_id` are managed by the sync system
- Tables without a source are user-uploaded or manually created

---

## Source Schemas (`system.source_schemas`)

Per-table sync configuration for external data sources.
Each schema represents one table or entity being synced from an external source.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`name` | varchar(400) | NOT NULL | Schema/table name (e.g., `customers`, `invoices`)
`source_id` | uuid | NOT NULL | FK to `system.data_warehouse_sources.id`
`table_id` | uuid | NULL | FK to `system.data_warehouse_tables.id`
`should_sync` | boolean | NOT NULL | Whether this schema is enabled for syncing
`status` | varchar(400) | NULL | Current sync status
`sync_type` | varchar(128) | NULL | Sync strategy
`last_synced_at` | timestamp with tz | NULL | Last successful sync timestamp
`latest_error` | text | NULL | Most recent error message
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`deleted` | boolean | NOT NULL | Soft delete flag
`deleted_at` | timestamp with tz | NULL | Deletion timestamp

### Status Values

- `Running` - Sync currently in progress
- `Paused` - Sync paused by user
- `Completed` - Last sync finished successfully
- `Failed` - Last sync encountered an error
- `BillingLimitReached` - Stopped due to billing limit
- `BillingLimitTooLow` - Billing limit too low to sync

### Sync Types

- `full_refresh` - Full data reload each sync
- `incremental` - Only sync new/changed data
- `append` - Append new data without updating existing rows

### Key Relationships

- **Source**: `source_id` -> `system.data_warehouse_sources.id`
- **Table**: `table_id` -> `system.data_warehouse_tables.id`

---

## Source Sync Jobs (`system.source_sync_jobs`)

Individual sync job runs for external data sources.
Each job tracks the status, row count, and timing of a single sync operation.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`pipeline_id` | uuid | NOT NULL | FK to `system.data_warehouse_sources.id`
`schema_id` | uuid | NULL | FK to schema being synced
`status` | varchar | NOT NULL | Job status
`rows_synced` | bigint | NULL | Number of rows synced
`billable` | boolean | NULL | Whether this sync job is billable (non-billable syncs don't appear in the syncs UI)
`latest_error` | text | NULL | Error message if failed
`created_at` | timestamp with tz | NOT NULL | Job start timestamp
`finished_at` | timestamp with tz | NULL | Job completion timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Status Values

- `Running` - Sync currently in progress
- `Completed` - Sync finished successfully
- `Failed` - Sync encountered an error
- `BillingLimitReached` - Stopped due to billing limit
- `BillingLimitTooLow` - Billing limit too low to sync

### Key Relationships

- **Source**: `pipeline_id` -> `system.data_warehouse_sources.id`

---

## Common Query Patterns

**List all data warehouse tables:**

```sql
SELECT name, row_count, created_at
FROM system.data_warehouse_tables
WHERE NOT deleted
ORDER BY created_at DESC
```

**Find tables by source type:**

```sql
SELECT t.name, t.row_count, s.source_type
FROM system.data_warehouse_tables AS t
INNER JOIN system.data_warehouse_sources AS s ON t.external_data_source_id = s.id
WHERE NOT t.deleted AND s.source_type = 'Stripe'
```

**List columns for a specific table:**

```sql
SELECT name, columns
FROM system.data_warehouse_tables
WHERE name = 'stripe_customers' AND NOT deleted
```

**Find tables with specific column:**

```sql
SELECT name, JSONExtractString(columns, 'email', 'clickhouse') AS email_type
FROM system.data_warehouse_tables
WHERE NOT deleted
  AND JSONHas(columns, 'email')
```

**List active data sources with table counts:**

```sql
SELECT
  s.source_type,
  s.prefix,
  count(t.id) AS table_count,
  sum(t.row_count) AS total_rows
FROM system.data_warehouse_sources AS s
LEFT JOIN system.data_warehouse_tables AS t ON t.external_data_source_id = s.id AND NOT t.deleted
WHERE NOT s.deleted
GROUP BY s.source_type, s.prefix
ORDER BY table_count DESC
```

**View recent sync jobs with their source type:**

```sql
SELECT
  j.status,
  j.rows_synced,
  j.created_at,
  j.finished_at,
  j.latest_error,
  s.source_type
FROM system.source_sync_jobs AS j
INNER JOIN system.data_warehouse_sources AS s ON j.pipeline_id = s.id
ORDER BY j.created_at DESC
LIMIT 50
```

**Find failed sync jobs in the last 7 days:**

```sql
SELECT
  j.pipeline_id,
  j.latest_error,
  j.created_at,
  s.source_type,
  s.prefix
FROM system.source_sync_jobs AS j
INNER JOIN system.data_warehouse_sources AS s ON j.pipeline_id = s.id
WHERE j.status = 'Failed'
  AND j.created_at >= now() - INTERVAL 7 DAY
ORDER BY j.created_at DESC
```

**Get sync statistics per source:**

```sql
SELECT
  s.source_type,
  s.prefix,
  count(j.id) AS total_jobs,
  countIf(j.status = 'Completed') AS completed,
  countIf(j.status = 'Failed') AS failed,
  sum(j.rows_synced) AS total_rows_synced
FROM system.source_sync_jobs AS j
INNER JOIN system.data_warehouse_sources AS s ON j.pipeline_id = s.id
GROUP BY s.source_type, s.prefix
ORDER BY total_jobs DESC
```
