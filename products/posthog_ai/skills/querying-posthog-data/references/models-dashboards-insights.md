# Dashboards, Tiles & Insights

## Dashboard (`system.dashboards`)

Dashboards are collections of insights that provide a unified view of analytics data.

### Columns

The `system.dashboards` HogQL view exposes a deliberately narrow set of columns — these are exactly what `SELECT *` returns:

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NULL | Dashboard name
`description` | text | NOT NULL | Dashboard description
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`deleted` | integer | NOT NULL | Soft delete flag (`0`/`1`)
`filters` | jsonb | NOT NULL | Dashboard-level filters applied to all insights
`variables` | jsonb | NULL | Dashboard variables for dynamic filtering

### Important Notes

- The view only exposes the columns above. Other Django model fields (`pinned`, `creation_mode`, `restriction_level`, `created_by_id`, `last_accessed_at`, color/theme fields, etc.) are **not** queryable here — selecting them fails with `Unable to resolve field: <col>`. Run `SELECT *` or `read-data-warehouse-schema` if unsure.
- The default manager excludes soft-deleted dashboards (`deleted=1`)
- Use `filters` to store dashboard-level date ranges and property filters

---

## Insight (`system.insights`)

Insights are saved analytics queries that visualize data.

### Columns

The `system.insights` HogQL view exposes a deliberately narrow set of columns — these are exactly what `SELECT *` returns:

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`short_id` | varchar(12) | NOT NULL | Unique short identifier for URLs
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NULL | User-defined insight name
`description` | varchar(400) | NULL | Insight description
`filters` | jsonb | NOT NULL | Filter configuration (legacy, prefer `query`)
`query` | jsonb | NULL | Modern HogQL query definition (preferred)
`query_metadata` | jsonb | NULL | Extracted query metadata for indexing
`deleted` | integer | NOT NULL | Soft delete flag (`0`/`1`)
`saved` | integer | NOT NULL | Whether insight is saved vs temporary (`0`/`1`)
`favorited` | integer | NOT NULL | Whether favorited by user (`0`/`1`)
`created_at` | timestamp with tz | NULL | Creation timestamp
`created_by_id` | integer | NULL | Creator user ID
`last_modified_at` | timestamp with tz | NOT NULL | Last modification timestamp
`last_modified_by_id` | integer | NULL | Last modifier user ID
`updated_at` | timestamp with tz | NOT NULL | Auto-updated timestamp

### Important Notes

- The view only exposes the columns above. Other Django model fields (`derived_name`, `filters_hash`, `order`, `refreshing`, `is_sample`, `refresh_attempt`, etc.) are **not** queryable here — selecting them fails with `Unable to resolve field: <col>`. Run `SELECT *` or `read-data-warehouse-schema` if unsure.
- `short_id` is unique per team and used in URLs: `/insights/{short_id}`
- Only insights with `saved=1` appear in the insights list
- The default manager excludes soft-deleted insights
