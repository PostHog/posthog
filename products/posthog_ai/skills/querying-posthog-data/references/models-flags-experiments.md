# Flags & Experiments

## Feature Flag (`system.feature_flags`)

Feature flags control rollouts of new features and are used for A/B testing.

### Columns

These are the only columns exposed via HogQL — the full flag model (e.g. `active`, `ensure_experience_continuity`, `last_called_at`, rollback settings) is not queryable here; fetch the flag via the feature flag API tools instead.

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`team_id` | integer | NOT NULL | Project scope
`key` | varchar(400) | NOT NULL | Unique flag key per team
`name` | text | NOT NULL | Flag description (not the display name)
`filters` | jsonb | NOT NULL | Targeting conditions and variants
`rollout_percentage` | integer | NULL | Overall rollout percentage
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`deleted` | integer (0/1) | NOT NULL | Soft delete flag

### Filters Structure

```json
{
  "groups": [
    {
      "properties": [...],
      "rollout_percentage": 50,
      "variant": "test"
    }
  ],
  "multivariate": {
    "variants": [
      {"key": "control", "rollout_percentage": 50},
      {"key": "test", "rollout_percentage": 50}
    ]
  },
  "payloads": {
    "control": {"value": "A"},
    "test": {"value": "B"}
  },
  "aggregation_group_type_index": null
}
```

### Key Relationships

- **Experiments**: Referenced by `system.experiments.feature_flag_id`
- **Surveys**: Can be linked via `system.surveys`

### Important Notes

- `key` must be unique per team
- Flag evaluation results are cached in Redis
- `aggregation_group_type_index` enables group-based targeting (company-level flags)

---

## Experiment (`system.experiments`)

Experiments are A/B tests that compare variants against a control group.

### Columns

These are the only columns exposed via HogQL — the full experiment model (e.g. `deleted`, `conclusion`, `metrics`, `metrics_secondary`, `stats_config`, `exposure_criteria`, `holdout_id`, `type`) is not queryable here; fetch the experiment via the experiment API tools instead.

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`team_id` | integer | NOT NULL | Project scope
`name` | varchar(400) | NOT NULL | Experiment name
`description` | varchar(400) | NULL | Experiment description
`filters` | jsonb | NOT NULL | Legacy target metric definition
`parameters` | jsonb | NULL | Experiment configuration (variants, MDE, sample size)
`start_date` | timestamp with tz | NULL | When experiment started (NULL = draft)
`end_date` | timestamp with tz | NULL | When experiment ended
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`archived` | integer (0/1) | NOT NULL | Whether experiment is archived
`feature_flag_id` | integer | NOT NULL | FK to `system.feature_flags.id`

### Parameters Structure

```json
{
  "minimum_detectable_effect": 5,
  "recommended_sample_size": 1000,
  "custom_exposure_filter": {...}
}
```

Feature-flag config (variant split, rollout %, payloads, group-type index, experience continuity) no longer lives in `parameters` — it lives on the linked feature flag. Query `system.feature_flags` and join via `experiments.feature_flag_id` to get the variant split and rollout percentages.

### Key Relationships

- **Feature Flag**: `feature_flag_id` -> `system.feature_flags.id` (required)

### Important Notes

- An experiment is a "draft" if `start_date` is NULL
- Soft-deleted experiments still appear in this table — there is no `deleted` column to filter them out; confirm via the experiment API tools when deletion status matters
- Each experiment requires an associated feature flag
- The feature flag controls variant assignment
