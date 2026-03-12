# Activity logs

## Activity log (`system.activity_logs`)

Activity logs track user and system actions across PostHog entities, providing an audit trail of changes to feature flags, insights, dashboards, experiments, and more.

> **Note:** Only team-scoped activity logs are visible. Organisation-level logs (e.g. membership changes) are not included because they are not associated with a specific team.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key (auto-generated UUID)
`team_id` | integer | NULL | Team the activity belongs to
`activity` | varchar(79) | NOT NULL | Action performed (e.g., `created`, `updated`, `deleted`)
`item_id` | varchar(72) | NULL | ID of the entity being logged (may be numeric ID, short ID, or UUID)
`scope` | varchar(79) | NOT NULL | Entity type being logged (e.g., `FeatureFlag`, `Insight`)
`detail` | jsonb | NULL | Structured details about the change
`created_at` | timestamp with tz | NOT NULL | When the activity occurred

### Detail JSON Structure

```json
{
  "name": "My Feature Flag",
  "short_id": "abc123",
  "type": "FeatureFlag",
  "changes": [
    {
      "type": "FeatureFlag",
      "action": "changed",
      "field": "active",
      "before": false,
      "after": true
    }
  ]
}
```

### Detail Fields

Field | Description
`name` | Display name of the entity
`short_id` | Short identifier (if applicable)
`type` | Entity type
`changes` | Array of individual field changes
`changes[].type` | Entity type for this change
`changes[].action` | `changed`, `created`, `deleted`, `merged`, `split`, `exported`, `revoked`, `copied`
`changes[].field` | Name of the field that changed
`changes[].before` | Previous value
`changes[].after` | New value

### Common Scopes

`FeatureFlag`, `Insight`, `Dashboard`, `Experiment`, `Cohort`, `Survey`, `Notebook`, `Action`,
`HogFunction`, `Person`, `Replay`, `Comment`, `BatchExport`, `Team`, `Project`,
`ErrorTrackingIssue`, `EarlyAccessFeature`, `Annotation`, `AlertConfiguration`

### Common Activities

`created`, `updated`, `deleted`, `exported`, `logged_in`, `logged_out`

---

## Common Query Patterns

**Find recent activity for a scope:**

```sql
SELECT id, activity, item_id, detail, created_at
FROM system.activity_logs
WHERE scope = 'FeatureFlag'
ORDER BY created_at DESC
LIMIT 50
```

**Find all changes to a specific entity:**

```sql
SELECT activity, detail, created_at
FROM system.activity_logs
WHERE scope = 'Insight' AND item_id = '42'
ORDER BY created_at DESC
```

**Search for a specific change in detail JSON:**

```sql
SELECT id, scope, activity, detail, created_at
FROM system.activity_logs
WHERE JSONExtractString(detail, 'name') ILIKE '%signup%'
ORDER BY created_at DESC
LIMIT 20
```
