# Hog Flows

## Hog Flow (`system.hog_flows`)

Hog flows are automated user journeys — multi-step workflows that trigger actions (emails, webhooks, etc.) based on user behavior.

### Columns

Column | Type | Nullable | Description
`id` | string (UUID) | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NULL | Display name
`description` | text | NOT NULL | Description of the flow
`status` | varchar(20) | NOT NULL | `draft`, `active`, or `archived`
`version` | integer | NOT NULL | Version number (incremented on each publish)
`exit_condition` | varchar(100) | NOT NULL | When a user exits the flow (see values below)
`trigger` | jsonb | NOT NULL | Entry trigger configuration
`edges` | jsonb | NOT NULL | Graph edges connecting flow steps
`actions` | jsonb | NOT NULL | Action definitions for each step
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp

### Status Values

- `draft` — not yet published, not running
- `active` — published and evaluating users
- `archived` — disabled and hidden from default views

### Exit Condition Values

- `exit_on_conversion` — user exits when they convert (complete the goal)
- `exit_on_trigger_not_matched` — user exits if they no longer match the trigger
- `exit_on_trigger_not_matched_or_conversion` — user exits on either condition
- `exit_only_at_end` — user always completes the full flow

### Query Examples

```sql
-- Count flows by status
SELECT status, count() AS total
FROM system.hog_flows
GROUP BY status
ORDER BY total DESC

-- List active flows with their names
SELECT id, name, version, created_at
FROM system.hog_flows
WHERE status = 'active'
ORDER BY created_at DESC

-- Find flows updated in the last 7 days
SELECT id, name, status, updated_at
FROM system.hog_flows
WHERE updated_at > now() - toIntervalDay(7)
ORDER BY updated_at DESC
```
