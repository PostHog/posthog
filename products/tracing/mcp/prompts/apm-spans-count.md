Return a scalar count of trace spans matching a filter set. Use this as a cheap pre-flight before `query-apm-spans` — if the count is large, narrow the filters (or set `excludeAttributes`) before pulling rows.

All parameters must be nested inside a `query` object.

# When to use

- Before `query-apm-spans`, to confirm the filter set returns a tractable number of spans rather than pulling rows blind.
- When the user asks "how many X spans are there?" and you don't need to see individual spans.
- To check whether a filter combination matches anything at all before committing to a full query.

This counts **spans**, not traces. A single trace contains many spans, so a count of matching spans will exceed the number of matching traces.

# Parameters

All parameters go inside `query`.

## query.dateRange

Date range for the count. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

Filter by service names. Unlike `query-apm-spans`, an unfiltered count is cheap and useful for sizing up a filter before narrowing. Use `apm-services-list` to discover services.

## query.statusCodes

Filter by OTel span status codes (list of integers: `0` Unset, `1` OK, `2` Error) — **not** HTTP status codes. Use `[2]` to select error spans.

## query.filterGroup

Property filters to narrow the count. Same format as `query-apm-spans` filters — each filter specifies `key`, `operator`, `type` (span/span_attribute/span_resource_attribute), and optionally `value`.

# Examples

## Count error spans in a service over the last day

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "statusCodes": [2],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Count how many spans match a name before fetching them

```json
{
  "query": {
    "filterGroup": [{ "key": "name", "operator": "exact", "type": "span", "value": "redis_cluster.discovery" }],
    "dateRange": { "date_from": "-6h" }
  }
}
```
