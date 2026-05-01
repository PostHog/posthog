# Cohorts & Persons

## Cohort (`system.cohorts`)

Cohorts are groups of persons used for segmentation and targeting.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`name` | varchar(400) | NULL | Cohort display name
`description` | varchar(1000) | NOT NULL | Cohort description
`deleted` | boolean | NOT NULL | Soft delete flag
`filters` | jsonb | NULL | Modern filter structure for cohort criteria
`query` | jsonb | NULL | HogQL query for analytical cohorts
`version` | integer | NULL | Current calculation version
`pending_version` | integer | NULL | Version being calculated
`count` | integer | NULL | Cached person count
`created_at` | timestamp with tz | NULL | Creation timestamp
`is_calculating` | boolean | NOT NULL | Whether calculation is in progress
`last_calculation` | timestamp with tz | NULL | Timestamp of last successful calculation
`errors_calculating` | integer | NOT NULL | Consecutive error count
`last_error_at` | timestamp with tz | NULL | Timestamp of last calculation error
`is_static` | boolean | NOT NULL | Static (manually uploaded) vs dynamic cohort
`cohort_type` | varchar(50) | NULL | One of: `static`, `person_property`, `behavioral`, `realtime`, `analytical`
`created_by_id` | integer | NULL | Creator user ID

### Cohort Types

Type | Description
`static` | Manually uploaded/managed list of persons
`person_property` | Based on person properties (e.g., email contains "example.com")
`behavioral` | Based on events performed (e.g., "viewed pricing page in last 30 days")
`realtime` | Can be evaluated in real-time (< 20M persons)
`analytical` | Complex queries with temporal/sequential logic via HogQL

### Filters Structure Examples

**Behavioral filter (performed event):**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "address page viewed",
        "type": "behavioral",
        "value": "performed_event",
        "negation": false,
        "event_type": "events",
        "time_value": "30",
        "time_interval": "day"
      }
    ]
  }
}
```

**Person property filter:**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "email",
        "type": "person",
        "value": ["@example.com"],
        "negation": false,
        "operator": "icontains"
      }
    ]
  }
}
```

**Cohort reference filter (nested cohorts):**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "id",
        "type": "cohort",
        "value": 8814,
        "negation": false
      }
    ]
  }
}
```

### Key Relationships

- **Persons**: Many-to-many via `raw_cohort_people` table
- **Calculation History**: One-to-many via `system.cohort_calculation_history`
- **Experiments**: Referenced by `system.experiments.exposure_cohort_id`

### Important Notes

- Cohorts can reference other cohorts creating nested dependencies
- `realtime` cohorts are cleared to `NULL` type if they exceed 20M persons
- Static cohorts are populated via CSV upload or API
- Dynamic cohorts are recalculated periodically

---

## Cohort Calculation History (`system.cohort_calculation_history`)

Audit trail for cohort calculation jobs.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`filters` | jsonb | NOT NULL | Cohort filters at calculation time
`count` | integer | NULL | Number of persons in cohort (>= 0)
`started_at` | timestamp with tz | NOT NULL | Calculation start time
`finished_at` | timestamp with tz | NULL | Calculation end time (NULL = in progress)
`queries` | jsonb | NULL | Array of query statistics
`error` | text | NULL | Full error message if failed
`error_code` | varchar(64) | NULL | Categorized error code
`cohort_id` | integer | NOT NULL | FK to `system.cohorts.id`

### Error Codes

Code | Description
`capacity` | System busy
`interrupted` | Socket timeout
`timeout` | Query timeout (> 1200s)
`memory_limit` | Memory exceeded
`query_size` | Query too large
`invalid_regex` | Regex compilation error
`incompatible_types` | Type mismatch
`no_properties` | No filters defined
`validation_error` | Generic validation error

### Queries Structure

```json
[
  {
    "query": "SELECT ...",
    "query_id": "abc123",
    "query_ms": 1234,
    "memory_mb": 256,
    "read_rows": 1000000,
    "written_rows": 5000
  }
]
```

## Entity Relationships Diagram

```text
system.cohorts (main cohort definition)
├── <- system.cohort_calculation_history.cohort_id
└── persons through `IN COHORT`

system.experiments
└── exposure_cohort_id -> system.cohorts.id
```

---

## Common Query Patterns

**Find cohorts by name:**

```sql
SELECT id, name, count, cohort_type, is_static
FROM system.cohorts
WHERE name ILIKE '%paying%' AND NOT deleted
```

**Get cohort with member count:**

```sql
SELECT c.id, c.name, c.count, c.last_calculation
FROM system.cohorts c
WHERE c.id = 123
```

**List persons in a cohort (via events):**

By cohort ID:

```sql
SELECT DISTINCT person_id, person.properties.email
FROM events
WHERE person_id IN COHORT 123
LIMIT 100
```

**List people in a cohort by its name:**

```sql
select count()
from persons
where id IN COHORT 'Case-sensitive cohort name'
```

**Check cohort calculation history:**

```sql
SELECT id, started_at, finished_at, count, error_code
FROM system.cohort_calculation_history
WHERE cohort_id = 123
ORDER BY started_at DESC
LIMIT 10
```

**Find people in a cohort of a specific version:**

```sql
SELECT
    tuple(coalesce(toString(properties.email), toString(properties.name), toString(properties.username), toString(id)), toString(id)),
    id,
    created_at
FROM
    persons
WHERE
    in(id, (SELECT
            person_id
        FROM
            raw_cohort_people
        WHERE
            and(equals(cohort_id, 212606), equals(version, 2))))
ORDER BY
    id ASC
LIMIT 101
OFFSET 0
```
