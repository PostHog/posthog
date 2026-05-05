# Logs

## LogsView (`system.logs_views`)

Saved log views — named filter configurations that users create to quickly access frequently-used log queries.

### Columns

| Column       | Type              | Nullable | Description                                                           |
| ------------ | ----------------- | -------- | --------------------------------------------------------------------- |
| `id`         | uuid              | NOT NULL | Primary key                                                           |
| `team_id`    | integer           | NOT NULL | Team this view belongs to                                             |
| `short_id`   | varchar(12)       | NOT NULL | URL-friendly short identifier                                         |
| `name`       | varchar(400)      | NOT NULL | Display name                                                          |
| `filters`    | jsonb             | NOT NULL | Saved filter criteria (severity levels, service names, filter groups) |
| `pinned`     | boolean           | NOT NULL | Whether the view is pinned for quick access                           |
| `created_at` | timestamp with tz | NOT NULL | Creation timestamp                                                    |
| `updated_at` | timestamp with tz | NOT NULL | Last update timestamp                                                 |

### Key Relationships

- Views belong to a **Team** (`team_id`)
- The `filters` field stores the same filter structure used by the logs viewer UI

### Important Notes

- The `short_id` is auto-generated and unique per team
- `filters` typically contains `severityLevels`, `serviceNames`, and `filterGroup` keys

---

## LogsAlertConfiguration (`system.logs_alerts`)

Alerts that monitor log volume and notify users when thresholds are breached. Uses an N-of-M evaluation model (similar to AWS CloudWatch alarms).

### Columns

| Column                   | Type              | Nullable | Description                                                         |
| ------------------------ | ----------------- | -------- | ------------------------------------------------------------------- |
| `id`                     | uuid              | NOT NULL | Primary key                                                         |
| `team_id`                | integer           | NOT NULL | Team this alert belongs to                                          |
| `name`                   | varchar(255)      | NOT NULL | Alert name                                                          |
| `enabled`                | boolean           | NOT NULL | Whether the alert is actively evaluated                             |
| `filters`                | jsonb             | NOT NULL | Log filter criteria (severity levels, service names, filter groups) |
| `threshold_count`        | integer           | NOT NULL | Number of log entries that triggers the alert                       |
| `threshold_operator`     | varchar(10)       | NOT NULL | `above` or `below`                                                  |
| `window_minutes`         | integer           | NOT NULL | Time window in minutes to evaluate                                  |
| `check_interval_minutes` | integer           | NOT NULL | How often the alert is checked (minutes)                            |
| `state`                  | varchar(20)       | NOT NULL | Current alert state (see State Values below)                        |
| `evaluation_periods`     | integer           | NOT NULL | Number of periods in the evaluation window (M in N-of-M)            |
| `datapoints_to_alarm`    | integer           | NOT NULL | Breaches needed to fire (N in N-of-M)                               |
| `cooldown_minutes`       | integer           | NOT NULL | Minutes to wait after firing before re-evaluating                   |
| `snooze_until`           | timestamp with tz | NULL     | Snooze expiry (UTC)                                                 |
| `next_check_at`          | timestamp with tz | NULL     | When the next evaluation is scheduled                               |
| `last_notified_at`       | timestamp with tz | NULL     | When subscribers were last notified                                 |
| `last_checked_at`        | timestamp with tz | NULL     | When the alert was last evaluated                                   |
| `consecutive_failures`   | integer           | NOT NULL | Number of consecutive evaluation failures                           |
| `created_at`             | timestamp with tz | NOT NULL | Creation timestamp                                                  |
| `updated_at`             | timestamp with tz | NOT NULL | Last update timestamp                                               |

### State Values

| State             | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `not_firing`      | Alert is within normal thresholds                     |
| `firing`          | Threshold breached, notifications sent                |
| `pending_resolve` | Was firing, waiting for confirmation that it resolved |
| `errored`         | Evaluation failed                                     |
| `snoozed`         | Temporarily silenced until `snooze_until`             |

### Key Relationships

- Alerts belong to a **Team** (`team_id`)
- Alert checks are stored in `LogsAlertEvent` (not exposed as a system table)

### Important Notes

- The N-of-M model: alert fires when `datapoints_to_alarm` (N) out of the last `evaluation_periods` (M) checks breach the threshold
- `datapoints_to_alarm` must be <= `evaluation_periods`
- Disabled alerts automatically have their state set to `not_firing`

---

## Common Query Patterns

**List all saved log views:**

```sql
SELECT id, name, short_id, pinned, created_at
FROM system.logs_views
ORDER BY created_at DESC
LIMIT 20
```

**Find pinned log views:**

```sql
SELECT id, name, short_id
FROM system.logs_views
WHERE pinned
ORDER BY name
```

**List active log alerts:**

```sql
SELECT id, name, state, threshold_count, threshold_operator, window_minutes
FROM system.logs_alerts
WHERE enabled
  AND state != 'snoozed'
ORDER BY created_at DESC
```

**Find firing log alerts:**

```sql
SELECT id, name, state, last_checked_at, last_notified_at
FROM system.logs_alerts
WHERE state = 'firing'
ORDER BY last_notified_at DESC
```

**Count log alerts by state:**

```sql
SELECT state, count() AS count
FROM system.logs_alerts
WHERE enabled
GROUP BY state
ORDER BY count DESC
```

**Find errored or failing log alerts:**

```sql
SELECT id, name, state, consecutive_failures, last_checked_at
FROM system.logs_alerts
WHERE state = 'errored' OR consecutive_failures > 0
ORDER BY consecutive_failures DESC
```
