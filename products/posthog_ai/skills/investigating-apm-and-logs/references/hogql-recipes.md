# HogQL recipes (fallback when `apm-logs-signal-snapshot` is unavailable)

Run via `posthog:execute-sql` (or project query API) with the same **team / project** context. Replace date bounds via `{filters}` when the client injects `HogQLFilters(dateRange=...)`, or substitute explicit `timestamp` predicates.

**Tables:** team-scoped `logs` ([schema](../../../../../posthog/hogql/database/schema/logs.py)); spans as `posthog.trace_spans` ([schema](../../../../../posthog/hogql/database/schema/spans.py)).

## Joinable `trace_id` heuristic (logs)

Treat `trace_id` as joinable when it is non-empty and not all zeros (common placeholder):

```sql
SELECT
    count() AS logs_total,
    countIf(
        trace_id != ''
        AND replaceRegexpAll(lower(trace_id), '0', '') != ''
    ) AS logs_with_joinable_trace_id
FROM logs
WHERE {filters}
```

Optional service filter:

```sql
AND service_name IN ('svc-a', 'svc-b')
```

## Distinct log service names (top by volume)

```sql
SELECT service_name, count() AS c
FROM logs
WHERE {filters}
GROUP BY service_name
ORDER BY c DESC
LIMIT 100
```

## Distinct trace service names

```sql
SELECT DISTINCT service_name
FROM posthog.trace_spans
WHERE {filters}
LIMIT 200
```

Use the same `dateRange` / `{filters}` semantics as your other HogQL queries so the window matches MCP tools.

## Sample joinable trace IDs

```sql
SELECT DISTINCT trace_id
FROM logs
WHERE {filters}
  AND trace_id != ''
  AND replaceRegexpAll(lower(trace_id), '0', '') != ''
LIMIT 10
```
