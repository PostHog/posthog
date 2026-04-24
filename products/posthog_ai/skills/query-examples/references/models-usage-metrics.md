# Usage metrics

## GroupUsageMetric (`system.usage_metrics`)

Usage metrics are team-defined numeric measures attached to a group type. They power the sparklines and summary numbers shown on customer analytics profiles — for example "weekly active users per account" or "revenue per workspace over the last 30 days".

Each metric is scoped to a single group type (by `group_type_index`) and evaluates a HogQL filter expression over events to produce a value, optionally summing a numeric property.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this metric belongs to
`group_type_index` | integer | NOT NULL | Zero-based index of the group type the metric applies to. Join against `system.group_type_mappings.group_type_index` to resolve the human-readable group type name
`name` | varchar(255) | NOT NULL | Human-readable metric name (unique per `(team_id, group_type_index)`)
`format` | varchar(64) | NOT NULL | `numeric` or `currency` — controls UI formatting
`interval` | integer | NOT NULL | Rolling time window in days used when computing the metric (default 7)
`display` | varchar(64) | NOT NULL | `number` or `sparkline` — controls UI visualization
`filters` | jsonb | NOT NULL | HogQL filter definition: `{"events": [...], "properties": [...]}`. Same shape as HogFunction filters
`math` | varchar(16) | NOT NULL | Aggregation: `count` (count matching events) or `sum` (sum `math_property`)
`math_property` | varchar(255) | NULL | Event property to sum. Required when `math='sum'`, must be null when `math='count'`

### Key relationships

- **Group types**: `group_type_index` → `system.group_type_mappings.group_type_index` (scoped to the same `team_id`)
- Metrics are referenced by the Customer Analytics profile UI; there is no direct FK from metrics to insights or dashboards

### Important notes

- `name` is unique within `(team_id, group_type_index)` — creating a duplicate raises a validation error on the API.
- Metric values are not stored in this table; they are computed on demand by executing `filters` against the events table. Read `bytecode` (not exposed here) internally caches the compiled filter.
- `interval` is stored in days. The API accepts only integer day values; there is no sub-day granularity.

---

## Common query patterns

**List all usage metrics for a group type (resolved to group type name):**

```sql
SELECT um.id, um.name, um.math, um.interval, um.display, gtm.group_type
FROM system.usage_metrics AS um
LEFT JOIN system.group_type_mappings AS gtm
  ON um.group_type_index = gtm.group_type_index
WHERE um.group_type_index = 0
ORDER BY um.name
```

**Find all `sum`-math metrics across every group type:**

```sql
SELECT id, name, group_type_index, math_property, interval
FROM system.usage_metrics
WHERE math = 'sum'
ORDER BY group_type_index, name
```

**Count metrics per group type:**

```sql
SELECT group_type_index, count() AS metric_count
FROM system.usage_metrics
GROUP BY group_type_index
ORDER BY group_type_index
```
