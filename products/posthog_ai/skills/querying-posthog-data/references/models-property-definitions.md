# Property definitions

## Property definition (`system.property_definitions`)

One row per property name PostHog has seen in the project, per property type. Use this table to audit the project's property taxonomy, and join against other system tables to find where a property is referenced (for example, to find unused person properties worth cleaning up).

### Columns

Column | Type | Nullable | Description
`id` | string (UUID) | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Owning team
`name` | varchar(400) | NOT NULL | Property name as sent in events or person profiles
`type` | integer | NOT NULL | What the property is defined on: 1 = event, 2 = person, 3 = group, 4 = session
`property_type` | varchar | NULL | Value type: String, Numeric, Boolean, DateTime, or Duration
`is_numerical` | boolean | NOT NULL | Whether the property holds numeric values (1 = yes, 0 = no)
`group_type_index` | integer | NULL | Which group type the property belongs to; only set when type = 3

### Finding where a property is used

Saved insights extract their referenced properties into `query_metadata.properties` (a JSON array of `{"name": ..., "type": ...}` entries, where `type` is a property filter type such as `person` or `event`). Feature flags, cohorts, and hog functions store property references inside their `filters` JSON as `{"key": ..., "type": ...}` entries.

For a one-call answer, prefer the API tools: `property-definitions-used-in-retrieve` lists the objects referencing one property, and `property-definitions-usage-summary-retrieve` returns per-name usage counts plus person-profile coverage for a list of names. The `property-definitions-list` tool accepts `in_use=true/false` to filter directly.

### Query examples

```sql
-- List person properties in the project
SELECT name, property_type
FROM system.property_definitions
WHERE type = 2
ORDER BY name

-- Person properties referenced by at least one saved insight
SELECT DISTINCT JSONExtractString(ref, 'name') AS property_name
FROM (
    SELECT arrayJoin(JSONExtractArrayRaw(toString(query_metadata), 'properties')) AS ref
    FROM system.insights
    WHERE deleted = 0
)
WHERE JSONExtractString(ref, 'type') = 'person'

-- Share of person profiles carrying each property
SELECT key, count() AS profiles
FROM (SELECT arrayJoin(JSONExtractKeys(properties)) AS key FROM persons)
GROUP BY key
ORDER BY profiles DESC
```
