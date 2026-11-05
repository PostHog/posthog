# Find logs with the same trace ID

For each unique trace ID, use the bounded SQL query below to find services
with logs for that trace, even when retained spans name some services. Add any
service names from the retained trace. `logs-attribute-values-list` cannot
filter service values by trace ID. If no service is found, do not make an
unscoped log query.

Raw `logs.trace_id` values use base64. Convert the validated hex ID in the
predicate, and use a short time window around the error. The 21st row shows
when the first 20 services are incomplete. Narrow the window and retry if a
complete list matters; otherwise report the limit.

```sql
posthog:execute-sql
SELECT service_name, count() AS log_count
FROM logs
WHERE trace_id = base64Encode(unhex('<trace_id>'))
    AND timestamp >= '<before_error>'
    AND timestamp < '<after_error>'
GROUP BY service_name
ORDER BY log_count DESC
LIMIT 21
```

Call `posthog:logs-count`, then `posthog:query-logs` with the same trace ID,
services, and time window. Use this filter shape. Use the same filters without
`limit` for `posthog:logs-count`. Keep the row limit small and narrow the
window if the count is large.

```json
{
  "query": {
    "serviceNames": ["<service_name>"],
    "dateRange": { "date_from": "<before_error>", "date_to": "<after_error>" },
    "filterGroup": [
      {
        "key": "trace_id",
        "type": "log",
        "operator": "exact",
        "value": "<trace_id>"
      }
    ],
    "limit": 50
  }
}
```
