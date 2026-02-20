# Flags & Experiments

## Feature Flag (`system.feature_flags`)

Feature flags control rollouts of new features and are used for A/B testing.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`key` | varchar(400) | NOT NULL | Unique flag key per team
`name` | text | NOT NULL | Flag description (not the display name)
`filters` | jsonb | NOT NULL | Targeting conditions and variants
`rollout_percentage` | integer | NULL | Overall rollout percentage
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`deleted` | boolean | NOT NULL | Soft delete flag
`active` | boolean | NOT NULL | Whether flag is enabled
`rollback_conditions` | jsonb | NULL | Automatic rollback configuration
`performed_rollback` | boolean | NULL | Whether rollback was triggered
`ensure_experience_continuity` | boolean | NULL | Sticky bucketing for users
`created_by_id` | integer | NULL | Creator user ID
`usage_dashboard_id` | integer | NULL | FK to `system.dashboards.id`
`has_enriched_analytics` | boolean | NULL | Whether rich analytics enabled
`is_remote_configuration` | boolean | NULL | Whether used as remote config
`has_encrypted_payloads` | boolean | NULL | Whether payloads are encrypted
`last_modified_by_id` | integer | NULL | Last modifier user ID
`version` | integer | NULL | Version number for tracking changes
`evaluation_runtime` | varchar(10) | NULL | `server`, `client`, or `all`
`updated_at` | timestamp with tz | NULL | Last update timestamp
`last_called_at` | timestamp with tz | NULL | Last evaluation timestamp
`bucketing_identifier` | varchar(50) | NULL | `distinct_id` or `device_id`

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

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`name` | varchar(400) | NOT NULL | Experiment name
`description` | varchar(400) | NULL | Experiment description
`filters` | jsonb | NOT NULL | Target metric definition
`parameters` | jsonb | NULL | Experiment configuration
`secondary_metrics` | jsonb | NULL | Additional metrics to track
`start_date` | timestamp with tz | NULL | When experiment started (NULL = draft)
`end_date` | timestamp with tz | NULL | When experiment ended
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`updated_at` | timestamp with tz | NOT NULL | Last update timestamp
`archived` | boolean | NOT NULL | Whether experiment is archived
`deleted` | boolean | NULL | Soft delete flag
`created_by_id` | integer | NULL | Creator user ID
`feature_flag_id` | integer | NOT NULL | FK to `system.feature_flags.id`
`exposure_cohort_id` | integer | NULL | FK to `system.cohorts.id`
`holdout_id` | integer | NULL | Holdout ID
`type` | varchar(40) | NULL | `web` or `product`
`variants` | jsonb | NULL | Variant configuration
`metrics` | jsonb | NULL | Primary metrics (new format)
`metrics_secondary` | jsonb | NULL | Secondary metrics (new format)
`stats_config` | jsonb | NULL | Statistical analysis configuration
`exposure_criteria` | jsonb | NULL | Exposure event criteria
`conclusion` | varchar(30) | NULL | `won`, `lost`, `inconclusive`, `stopped_early`, `invalid`
`conclusion_comment` | text | NULL | Notes about conclusion
`scheduling_config` | jsonb | NULL | Scheduled actions configuration
`primary_metrics_ordered_uuids` | jsonb | NULL | Ordered primary metric UUIDs
`secondary_metrics_ordered_uuids` | jsonb | NULL | Ordered secondary metric UUIDs

### Parameters Structure

```json
{
  "minimum_detectable_effect": 5,
  "recommended_running_time": 14,
  "recommended_sample_size": 1000,
  "feature_flag_variants": [
    {"key": "control", "name": "Control", "rollout_percentage": 50},
    {"key": "test", "name": "Test", "rollout_percentage": 50}
  ],
  "custom_exposure_filter": {...}
}
```

### Key Relationships

- **Feature Flag**: `feature_flag_id` -> `system.feature_flags.id` (required)
- **Exposure Cohort**: `exposure_cohort_id` -> `system.cohorts.id`

### Important Notes

- An experiment is a "draft" if `start_date` is NULL
- Each experiment requires an associated feature flag
- The feature flag controls variant assignment
