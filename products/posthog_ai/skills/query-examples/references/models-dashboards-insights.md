# Dashboards, Tiles & Insights

## Dashboard (`system.dashboards`)

Dashboards are collections of insights that provide a unified view of analytics data.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`name` | varchar(400) | NULL | Dashboard name
`description` | text | NOT NULL | Dashboard description
`pinned` | boolean | NOT NULL | Whether dashboard is pinned
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`deleted` | boolean | NOT NULL | Soft delete flag
`last_accessed_at` | timestamp with tz | NULL | Last access timestamp
`filters` | jsonb | NOT NULL | Dashboard-level filters applied to all insights
`creation_mode` | varchar(16) | NOT NULL | How dashboard was created: `default`, `template`, `duplicate`, `unlisted`
`restriction_level` | smallint | NOT NULL | Access restriction: `21` (everyone can edit), `37` (only collaborators)
`created_by_id` | integer | NULL | Creator user ID
`variables` | jsonb | NULL | Dashboard variables for dynamic filtering
`breakdown_colors` | jsonb | NULL | Custom breakdown color assignments
`data_color_theme_id` | integer | NULL | Color theme ID
`last_refresh` | timestamp with tz | NULL | Last refresh timestamp

### Important Notes

- The default manager excludes soft-deleted dashboards (`deleted=True`)
- `creation_mode='unlisted'` dashboards are hidden from general lists (used for product dashboards like LLM Analytics)
- Use `filters` to store dashboard-level date ranges and property filters

---

## Insight (`system.insights`)

Insights are saved analytics queries that visualize data.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`name` | varchar(400) | NULL | User-defined insight name
`derived_name` | varchar(400) | NULL | Auto-generated name from query
`description` | varchar(400) | NULL | Insight description
`filters` | jsonb | NOT NULL | Filter configuration (legacy, prefer `query`)
`filters_hash` | varchar(400) | NULL | Hash for caching
`query` | jsonb | NULL | Modern HogQL query definition (preferred)
`query_metadata` | jsonb | NULL | Extracted query metadata for indexing
`order` | integer | NULL | Display order
`deleted` | boolean | NOT NULL | Soft delete flag
`saved` | boolean | NOT NULL | Whether insight is saved (vs temporary)
`created_at` | timestamp with tz | NULL | Creation timestamp
`refreshing` | boolean | NOT NULL | Whether currently refreshing
`is_sample` | boolean | NOT NULL | Whether this is sample data
`short_id` | varchar(12) | NOT NULL | Unique short identifier for URLs
`favorited` | boolean | NOT NULL | Whether favorited by user
`refresh_attempt` | integer | NULL | Number of refresh attempts
`last_modified_at` | timestamp with tz | NOT NULL | Last modification timestamp
`updated_at` | timestamp with tz | NOT NULL | Auto-updated timestamp
`created_by_id` | integer | NULL | Creator user ID
`last_modified_by_id` | integer | NULL | Last modifier user ID

### Key Relationships

- **Survey**: Can be linked to surveys via `system.surveys.linked_insight_id`

### Important Notes

- `short_id` is unique per team and used in URLs: `/insights/{short_id}`
- Only insights with `saved=True` appear in the insights list
- The default manager excludes soft-deleted insights
