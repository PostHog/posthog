# Batch exports

## BatchExport (`system.batch_exports`)

Batch exports define recurring data export jobs that send events, persons, or sessions to external destinations.

### Columns

| Column            | Type              | Nullable | Description                                                                      |
| ----------------- | ----------------- | -------- | -------------------------------------------------------------------------------- |
| `id`              | uuid              | NOT NULL | Primary key                                                                      |
| `team_id`         | integer           | NOT NULL | Team this export belongs to                                                      |
| `name`            | text              | NOT NULL | Human-readable name                                                              |
| `model`           | varchar(64)       | NULL     | Data model: `events`, `persons`, or `sessions`                                   |
| `interval`        | varchar(64)       | NOT NULL | Schedule frequency: `hour`, `day`, `week`, `every 5 minutes`, `every 15 minutes` |
| `paused`          | integer           | NOT NULL | Whether the export is paused (1 = paused, 0 = active)                            |
| `deleted`         | integer           | NOT NULL | Soft-delete flag (1 = deleted, 0 = active)                                       |
| `destination_id`  | uuid              | NOT NULL | FK to the destination configuration (not queryable as a system table)            |
| `timezone`        | varchar(240)      | NOT NULL | IANA timezone for scheduling (e.g. `UTC`, `America/New_York`)                    |
| `interval_offset` | integer           | NULL     | Offset in seconds from the default interval start time                           |
| `created_at`      | timestamp with tz | NOT NULL | Creation timestamp                                                               |
| `last_updated_at` | timestamp with tz | NOT NULL | Last modification timestamp                                                      |
| `last_paused_at`  | timestamp with tz | NULL     | When the export was last paused                                                  |
| `start_at`        | timestamp with tz | NULL     | Earliest time for scheduled runs                                                 |
| `end_at`          | timestamp with tz | NULL     | Latest time for scheduled runs                                                   |

### Key Relationships

- Each batch export belongs to a **Team** (`team_id`)
- Backfills reference this table via `system.batch_export_backfills.batch_export_id`

### Important Notes

- Filter with `deleted = 0` to exclude soft-deleted exports
- Filter with `paused = 0` to find actively running exports
- Destination details (type, connection config) are not in this table; use the `batch-export-get` MCP tool instead
- Run history is not directly queryable via SQL; use the `batch-export-runs-list` MCP tool

---

## BatchExportBackfill (`system.batch_export_backfills`)

Backfills are one-time historical data export jobs triggered for a batch export.

### Columns

| Column                | Type              | Nullable | Description                                         |
| --------------------- | ----------------- | -------- | --------------------------------------------------- |
| `id`                  | uuid              | NOT NULL | Primary key                                         |
| `team_id`             | integer           | NOT NULL | Team this backfill belongs to                       |
| `batch_export_id`     | uuid              | NOT NULL | FK to the parent batch export                       |
| `start_at`            | timestamp with tz | NULL     | Start of the backfill time range                    |
| `end_at`              | timestamp with tz | NULL     | End of the backfill time range                      |
| `status`              | varchar(64)       | NOT NULL | Current status (see values below)                   |
| `created_at`          | timestamp with tz | NOT NULL | Creation timestamp                                  |
| `finished_at`         | timestamp with tz | NULL     | Completion timestamp                                |
| `last_updated_at`     | timestamp with tz | NOT NULL | Last modification timestamp                         |
| `total_records_count` | bigint            | NULL     | Total records exported (populated after completion) |

### Key Relationships

- Each backfill belongs to a **BatchExport** (`batch_export_id` → `system.batch_exports.id`)
- Each backfill belongs to a **Team** (`team_id`)

### Important Notes

- Status values: `Starting`, `Running`, `Completed`, `Failed`, `FailedRetryable`, `Cancelled`, `ContinuedAsNew`, `Terminated`, `TimedOut`
- A `NULL` `start_at` means backfilling from the earliest available data
- A `NULL` `end_at` means backfilling up to the current time
