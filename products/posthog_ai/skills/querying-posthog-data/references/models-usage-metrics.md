# Usage metrics

## GroupUsageMetric (`system.usage_metrics`)

Usage metrics are team-defined numeric measures that render on Customer Analytics profile pages — for example "weekly active users", "events in the last 7 days", or "revenue over the last 30 days". Each metric compiles a HogQL filter expression over the events table, optionally summing a numeric property.

**Not group-specific.** Despite the model name (`GroupUsageMetric`) and the presence of `group_type_index`, metrics are defined at the **team** level and applied to **both groups and persons**. They were originally built for group profiles and later reused for person profiles without renaming; every metric a team defines surfaces on every profile type.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this metric belongs to
`group_type_index` | integer | NOT NULL | **Legacy / effectively unused.** Retained for backward compatibility but the query runner ignores it — every team-owned metric is evaluated against the current entity regardless of this value. Safe to omit from `SELECT` and do not filter on it
`name` | varchar(255) | NOT NULL | Human-readable metric name
`format` | varchar(64) | NOT NULL | `numeric` or `currency` — controls UI formatting
`interval` | integer | NOT NULL | Rolling time window in days used when computing the metric (default 7)
`display` | varchar(64) | NOT NULL | `number` or `sparkline` — controls UI visualization
`filters` | jsonb | NOT NULL | HogQL filter definition: `{"events": [...], "properties": [...]}`. Same shape as HogFunction filters
`math` | varchar(16) | NOT NULL | Aggregation: `count` (count matching events) or `sum` (sum `math_property`)
`math_property` | varchar(255) | NULL | Event property to sum. Required when `math='sum'`, must be null when `math='count'`

### Key relationships

- Metrics are referenced by the Customer Analytics profile UI for both group and person profiles. There is no direct FK to insights, dashboards, group types, or persons.
- The stored `(team_id, group_type_index, name)` unique constraint is an artifact of the group-only era; treat `name` as unique per team in practice.

### Important notes

- Metric values are not stored here; they are computed on demand by executing `filters` against the events table for the profile being viewed. An internal `bytecode` column (not exposed) caches the compiled filter.
- `interval` is stored in days. The API accepts only integer day values; there is no sub-day granularity.
- Do not assume `group_type_index` filters the scope of metrics — it doesn't. Treat it as historical metadata.

---

## Common query patterns

**List all usage metrics for a team:**

```sql
SELECT id, name, math, interval, display, format
FROM system.usage_metrics
ORDER BY name
```

**Find all `sum`-math metrics in the team:**

```sql
SELECT id, name, math_property, interval
FROM system.usage_metrics
WHERE math = 'sum'
ORDER BY name
```

**Group metrics by the rolling window they use:**

```sql
SELECT interval, count() AS metric_count
FROM system.usage_metrics
GROUP BY interval
ORDER BY interval
```
