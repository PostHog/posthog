# Early Access Features

## EarlyAccessFeature (`system.early_access_features`)

Early access features let teams manage staged feature rollouts where users can opt in. Each feature is linked to a feature flag that controls access.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Project/team ID for isolation
`feature_flag_id` | integer | NULL | Linked feature flag ID
`name` | varchar(200) | NOT NULL | Feature name
`description` | text | NOT NULL | Longer description shown in the opt-in UI (may be empty string)
`stage` | varchar(40) | NOT NULL | Lifecycle stage (see values below)
`documentation_url` | varchar(800) | NOT NULL | URL to external docs (may be empty string)
`created_at` | timestamp with tz | NOT NULL | Creation timestamp

### Stage Values

Value | Description
`draft` | Initial stage, not visible to users
`concept` | Gauging interest, opt-in tracked but feature flag not enabled
`alpha` | Active stage, opted-in users get the feature flag enabled
`beta` | Active stage, opted-in users get the feature flag enabled
`general-availability` | Active stage, feature available to all users
`archived` | Feature retired, flag enrollment conditions removed

Active stages (where opted-in users get the feature flag enabled): `alpha`, `beta`, `general-availability`.

### Key Relationships

- **Feature flags**: `feature_flag_id` -> `system.feature_flags.id`

### Important Notes

- The `stage` field uses a hyphenated value `general-availability` (not underscore).
- Features without a `feature_flag_id` are rare but possible during creation errors.
- There is no soft-delete column; deleted features are removed from the table.

---

## Common Query Patterns

**List all early access features with their stages:**

```sql
SELECT id, name, stage, feature_flag_id, created_at
FROM system.early_access_features
ORDER BY created_at DESC
LIMIT 100
```

**Find active features (in alpha, beta, or GA):**

```sql
SELECT id, name, stage, feature_flag_id
FROM system.early_access_features
WHERE stage IN ('alpha', 'beta', 'general-availability')
ORDER BY created_at DESC
```

**Join with feature flags to see flag keys:**

```sql
SELECT eaf.id, eaf.name, eaf.stage, ff.key AS flag_key
FROM system.early_access_features AS eaf
LEFT JOIN system.feature_flags AS ff ON eaf.feature_flag_id = ff.id
ORDER BY eaf.created_at DESC
LIMIT 100
```
