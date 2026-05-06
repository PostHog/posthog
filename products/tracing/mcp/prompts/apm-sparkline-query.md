Aggregates OpenTelemetry span volume into time buckets per `service_name` for trend questions (RED-style traffic), without returning raw spans.

Each row has `time` (ISO 8601 UTC), `service` (service name), and `count` (number of spans in that bucket).

Use this for traffic trends, error spikes by service, or comparing activity across services over a window. For individual spans or traces, use `query-apm-spans` and `apm-trace-get` instead.

All parameters must be nested inside a `query` object.

## query.dateRange

Same as span query: `date_from` / `date_to` relative (`-1h`, `-24h`) or ISO timestamps. Defaults to last hour.

## query.serviceNames

Optional list of service names to restrict the breakdown.

## query.statusCodes

Filter by OpenTelemetry span `status_code` integers: 0 Unset, 1 OK, 2 Error.

## query.filterGroup

Same property filter shape as `query-apm-spans` (`span`, `span_attribute`, `span_resource_attribute`).

## Examples

### Last 24 hours of span volume by service (default aggregation)

```json
{
  "query": {
    "dateRange": { "date_from": "-24h" }
  }
}
```

### One service over 6 hours

```json
{
  "query": {
    "dateRange": { "date_from": "-6h" },
    "serviceNames": ["checkout-api"]
  }
}
```

## Reminders

- Bucketing follows the server interval derived from the date range; expect on the order of tens to low hundreds of points, not per-span rows.
- Combine with `apm-services-list` when you are unsure which `serviceNames` exist.
