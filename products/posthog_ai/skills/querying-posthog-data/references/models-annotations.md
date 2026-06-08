# Annotations

## Annotation (`system.annotations`)

Annotations are timestamped notes used to mark product changes, incidents, or releases directly on charts.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`team_id` | integer | NOT NULL | Project/team ID for isolation
`content` | varchar(8192) | NULL | Annotation text content
`scope` | varchar(24) | NOT NULL | Annotation scope: `project`, `organization`, `dashboard`, `dashboard_item`, `recording`
`creation_type` | varchar(3) | NOT NULL | Creation source: `USR` (user) or `GIT` (GitHub/bot)
`date_marker` | timestamp with tz | NULL | Timestamp shown on charts
`deleted` | boolean | NOT NULL | Soft delete flag
`dashboard_item_id` | integer | NULL | Linked insight ID (if scoped to insight)
`dashboard_id` | integer | NULL | Linked dashboard ID (if scoped to dashboard)
`created_by_id` | integer | NULL | Creator user ID
`created_at` | timestamp with tz | NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Key Relationships

- **Insights**: `dashboard_item_id` -> `system.insights.id`
- **Dashboards**: `dashboard_id` -> `system.dashboards.id`

### Important Notes

- The API usually hides `deleted=true` rows; SQL queries should filter them explicitly when needed.
- `scope='organization'` annotations can appear across multiple projects in the same organization.

---

## Common Query Patterns

**List recent non-deleted annotations:**

```sql
SELECT id, scope, content, date_marker, created_at
FROM system.annotations
WHERE NOT deleted
ORDER BY date_marker DESC NULLS LAST
LIMIT 100
```

**Find annotations around a release window:**

```sql
SELECT id, content, scope, date_marker
FROM system.annotations
WHERE NOT deleted
  AND date_marker >= toDateTime('2026-03-01 00:00:00')
  AND date_marker < toDateTime('2026-03-08 00:00:00')
ORDER BY date_marker ASC
```

**Get organization-scoped annotations only:**

```sql
SELECT id, content, date_marker, created_by_id
FROM system.annotations
WHERE NOT deleted
  AND scope = 'organization'
ORDER BY date_marker DESC NULLS LAST
```
