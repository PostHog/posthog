# Groups

## Group Type Mapping (`system.group_type_mappings`)

Maps group types (like "company", "organization") to their numeric index for analytics.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`group_type` | varchar(400) | NOT NULL | Group type identifier (e.g., "company")
`group_type_index` | integer | NOT NULL | Numeric index (0-5)
`name_singular` | varchar(400) | NULL | Display name singular (e.g., "Company")
`name_plural` | varchar(400) | NULL | Display name plural (e.g., "Companies")
`detail_dashboard_id` | integer | NULL | FK to group detail dashboard
`default_columns` | text[] | NULL | Default columns to display
`created_at` | timestamp with tz | NULL | Creation timestamp

### Constraints

- `group_type_index` must be <= 5 (max 6 group types per team)
- `group_type` must be unique per team
- `group_type_index` must be unique per team

### Key Relationships

- **Detail Dashboard**: `detail_dashboard_id` -> `system.dashboards.id`

### Important Notes

- This table lives in the persons database (separate from main DB)
- `group_type_index` is used in events as `$group_0`, `$group_1`, etc.
- Maximum of 6 group types per team (indices 0-5)

---

## Group (`system.groups`)

Stores group entities (companies, organizations) and their properties.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`group_key` | varchar(400) | NOT NULL | Unique identifier for the group
`group_type_index` | integer | NOT NULL | Reference to group type (0-5)
`group_properties` | jsonb | NOT NULL | Group properties/attributes
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`properties_last_updated_at` | jsonb | NOT NULL | Per-property update timestamps
`properties_last_operation` | jsonb | NOT NULL | Per-property operation type (`set`/`set_once`)
`version` | bigint | NOT NULL | Version for ClickHouse sync

### Key Relationships

- **Group Type**: `group_type_index` matches `system.group_type_mappings.group_type_index`

### Important Notes

- This table lives in the persons database (separate from main DB)
- `version` is used for ClickHouse row collapsing during sync
- Properties support `$set` and `$set_once` operations
