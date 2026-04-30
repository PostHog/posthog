# Dynamic person and event properties

Some properties follow dynamic naming patterns with IDs or keys.
These are **not returned** by the `read-data-schema` tool because they are generated per survey, feature flag, or product tour.
If a user's question involves these features, construct the property name using the patterns below.

## Person properties

Pattern | Type | Description
`$survey_dismissed/{survey_id}` | Boolean | Whether a person dismissed a specific survey
`$survey_responded/{survey_id}` | Boolean | Whether a person responded to a specific survey
`$feature_enrollment/{flag_key}` | Boolean | Whether a person opted into an early access feature
`$feature_interaction/{feature_key}` | Boolean | Whether a person interacted with a specific feature
`$product_tour_dismissed/{tour_id}` | Boolean | Whether a person dismissed a product tour
`$product_tour_shown/{tour_id}` | Boolean | Whether a person was shown a product tour
`$product_tour_completed/{tour_id}` | Boolean | Whether a person completed a product tour

## Event properties

Pattern | Type | Description
`$feature/{flag_key}` | String | The feature flag value for a specific flag

## Querying dynamic properties with SQL

Because these properties are not discoverable via the `read-data-schema` tool, you must know the ID or key.
Use these queries to find the IDs, then construct the property name.

### Find survey IDs

```sql
SELECT id, name, description, type
FROM system.surveys
WHERE NOT archived
ORDER BY created_at DESC
LIMIT 20
```

Then query person properties like `$survey_dismissed/{id}` or `$survey_responded/{id}`.

### Find feature flag keys

```sql
SELECT id, key, name, rollout_percentage
FROM system.feature_flags
WHERE NOT deleted
ORDER BY created_at DESC
LIMIT 20
```

Then query event properties like `$feature/{key}` or person properties like `$feature_enrollment/{key}`.

### Find early access features

```sql
SELECT id, name, feature_flag_id
FROM system.early_access_features
WHERE NOT deleted
ORDER BY created_at DESC
LIMIT 20
```

Then look up the flag key and query `$feature_enrollment/{flag_key}`.

## Event taxonomy omit list

The `read-data-schema` tool's event property results automatically filter out these dynamic patterns
(and other noisy properties) to keep results clean:

Pattern | Reason
`$feature/{flag_key}` | Feature flag values — one per flag, high cardinality
`$feature_enrollment/{flag_key}` | Early access enrollment — dynamic per flag
`$feature_interaction/{feature_key}` | Feature interaction tracking — dynamic per feature
`$product_tour_*` | Product tour lifecycle — dynamic per tour
`survey_dismiss*`, `survey_responded*` | Survey tracking — dynamic per survey
`$set`, `$set_once` | Person property setting, not analytics properties
`$ip` | Privacy-related
`__*` | Flatten-properties-plugin artifacts
`phjs*` | Internal SDK metadata
