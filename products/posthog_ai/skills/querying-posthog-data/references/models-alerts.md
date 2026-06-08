# Alerts

## AlertConfiguration (`system.alerts`)

Alerts monitor insight values and notify subscribed users when thresholds are breached.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this alert belongs to
`name` | varchar(255) | NOT NULL | Human-readable alert name (can be blank)
`insight_id` | integer | NOT NULL | FK to the insight being monitored
`enabled` | boolean | NOT NULL | Whether the alert is actively evaluated
`state` | varchar(10) | NOT NULL | `Firing`, `Not firing`, `Errored`, or `Snoozed`
`calculation_interval` | varchar(10) | NULL | Check frequency: `hourly`, `daily`, `weekly`, or `monthly`
`condition` | jsonb | NOT NULL | Alert condition: `{"type": "absolute_value" | "relative_increase" | "relative_decrease"}`
`config` | jsonb | NULL | Trends config: `{"type": "TrendsAlertConfig", "series_index": int, "check_ongoing_interval": bool}`
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`last_notified_at` | timestamp with tz | NULL | When subscribers were last notified
`last_checked_at` | timestamp with tz | NULL | When the alert was last evaluated
`next_check_at` | timestamp with tz | NULL | When the next evaluation is scheduled
`snoozed_until` | timestamp with tz | NULL | Snooze expiry (UTC)
`skip_weekend` | boolean | NULL | Whether to skip evaluation on Saturday and Sunday

### Key Relationships

- Each alert monitors exactly one **Insight** (`insight_id` → `system.insights.id`)
- Alerts belong to a **Team** (`team_id`)
- Subscribers are managed via `AlertSubscription` (not exposed as a system table)

### Important Notes

- The `condition.type` determines evaluation mode:
  - `absolute_value` — fires when the value crosses the threshold bounds
  - `relative_increase` — fires when the value increases beyond the threshold
  - `relative_decrease` — fires when the value decreases beyond the threshold
- The `config.series_index` selects which series in a multi-series insight to monitor
- Alerts have a per-team limit (2 on the free tier, higher on paid plans)
