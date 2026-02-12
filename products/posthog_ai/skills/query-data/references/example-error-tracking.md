# Error tracking (search for a value in an error and filtering by custom properties)

```sql
SELECT
    issue_id AS id,
    max(timestamp) AS last_seen,
    min(timestamp) AS first_seen,
    argMax(properties.$exception_functions[length(properties.$exception_functions)], timestamp) AS function,
    argMax(properties.$exception_sources[length(properties.$exception_sources)], timestamp) AS source,
    count(DISTINCT uuid) AS occurrences,
    count(DISTINCT nullIf($session_id, '')) AS sessions,
    count(DISTINCT e.person.id) AS users,
    sumForEach(arrayMap(bin -> if(and(greater(timestamp, bin), lessOrEquals(dateDiff('seconds', bin, timestamp), divide(dateDiff('seconds', toDateTime(toDateTime('2026-01-28 01:03:27.941192')), toDateTime(toDateTime('2026-01-29 01:03:27.941276'))), 20))), 1, 0), arrayMap(i -> dateAdd(toDateTime(toDateTime('2026-01-28 01:03:27.941192')), toIntervalSecond(multiply(i, divide(dateDiff('seconds', toDateTime(toDateTime('2026-01-28 01:03:27.941192')), toDateTime(toDateTime('2026-01-29 01:03:27.941276'))), 20)))), range(0, 20)))) AS volumeRange,
    argMax(properties.$lib, timestamp) AS library
FROM
    events AS e
WHERE
    and(equals(event, '$exception'), isNotNull(issue_id), equals(properties.tag, 'max_ai'), greaterOrEquals(timestamp, toDateTime(toDateTime('2026-01-28 01:10:10.583396'))), lessOrEquals(timestamp, toDateTime(toDateTime('2026-01-29 01:10:10.583487'))), or(greater(position(lower(properties.$exception_types), lower('constant')), 0), greater(position(lower(properties.$exception_values), lower('constant')), 0), greater(position(lower(properties.$exception_sources), lower('constant')), 0), greater(position(lower(properties.$exception_functions), lower('constant')), 0), greater(position(lower(properties.email), lower('constant')), 0), greater(position(lower(person.properties.email), lower('constant')), 0)))
GROUP BY
    id
ORDER BY
    last_seen DESC
LIMIT 51
```
