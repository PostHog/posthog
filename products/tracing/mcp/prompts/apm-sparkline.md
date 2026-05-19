Get a time-bucketed sparkline of span volume for a service, broken down implicitly by status. Use this to understand span volume patterns before drilling into individual traces — it is much cheaper than a full `query-apm-spans` call.

All parameters must be nested inside a `query` object.

# Parameters

## query.dateRange

Date range for the sparkline. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

Filter by service names. Use `apm-services-list` to discover available services before filtering.

## query.statusCodes

Filter by HTTP status codes (list of integers).

## query.filterGroup

Property filters to narrow results. Same format as `query-apm-spans` filters (types: `span`, `span_attribute`, `span_resource_attribute`).

# Examples

## Span volume for a service over the last hour

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1h" }
  }
}
```

## Error span volume over the last day

```json
{
  "query": {
    "serviceNames": ["checkout"],
    "statusCodes": [500, 503],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Spans with a specific attribute over the last 6 hours

```json
{
  "query": {
    "serviceNames": ["payments"],
    "filterGroup": [{ "key": "http.status_code", "operator": "gt", "type": "span_attribute", "value": "499" }],
    "dateRange": { "date_from": "-6h" }
  }
}
```

# Reminders

- Always set `dateRange` — unbounded queries are slow.
- Prefer this over `query-apm-spans` when you only need volume shape, not individual spans.
- Use `apm-services-list` to discover available services before filtering.
