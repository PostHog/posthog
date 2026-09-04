Return per-value counts for a facet — the distribution of a log dimension across a filter set, ordered by count descending. This is the cheap way to see the _shape_ of a log stream (e.g. "which services produce the errors?") without pulling raw rows.

Counts are cross-filtered: every active filter is applied _except the faceted field's own filter_, so you see the full distribution rather than collapsing to your own selection. Faceting `service_name` with `serviceNames: ["api"]` still returns every service, not just `api`.

All parameters must be nested inside a `query` object. Provide **exactly one** of `query.facetField`, `query.facetResourceAttribute` or `query.facetAttribute` — or, to count several attribute keys in one call, the plural `query.facetResourceAttributes` / `query.facetAttributes` lists. A single target and the plural lists cannot be mixed in one request: they apply different filters (see below).

# Response

`results` always carries the same three keys, and the request decides which are populated:

- `facetField`: `[{value, count}]` — set when you asked on `facetField`.
- `facetResourceAttributes` and `facetAttributes`: `[{key, values: [{value, count}]}]` — one entry per key you asked for, whether you used the singular field or the plural list.

So a `facetResourceAttribute: "k8s.pod.name"` request returns its counts under `results.facetResourceAttributes[0].values`.

# When to use

- To find how log volume is distributed across severity or service under a filter — e.g. "of the logs matching 'timeout', which services emit them?" Facet `service_name` with `searchTerm: "timeout"`.
- As the drill-down loop for an investigation: facet `service_name` filtered to `severity=error` → find the hot service → add it to `serviceNames` → facet a resource attribute like `k8s.pod.name` → find the bad pod. Each call is one cheap aggregation that narrows the search space before you pull raw rows with `query-logs`.
- To confirm the severity mix in a window before committing to a query: facet `severity_text`.

## Pick the right tool

- Counts for an arbitrary **attribute** value (any log or resource attribute key) → use `logs-attribute-values-list`. It returns `{value, count}` for any key and is the general-purpose choice for attributes.
- Per-service log/error counts and error rates with a sparkline → use `logs-services-create`.
- Use **this** tool for `severity_text` / `service_name` distribution cross-filtered by the full query (severity + body `searchTerm` + `filterGroup`) — the one thing the tools above can't do.

# Parameters

## query.facetField

Top-level column to facet on: `severity_text` or `service_name`. Counts are grouped on the raw logs table with all _other_ filters applied — so this path honors `severityLevels`, `serviceNames`, `searchTerm`, and `filterGroup`.

## query.facetResourceAttribute

Resource attribute key to facet on, e.g. `k8s.namespace.name`, `k8s.pod.name`, `host.name`. Its own filter is excluded and `facetSearch` applies; use `facetResourceAttributes` to ask for several keys instead.

**Limitation:** this path is served from a pre-aggregated rollup that has no severity or body dimension. It honors only `serviceNames` and other resource-attribute filters — `severityLevels`, `searchTerm`, and log-attribute filters are **ignored**. If you need those applied, facet a column instead, or narrow with `logs-attribute-values-list`.

## query.facetResourceAttributes / query.facetAttributes

Lists of attribute keys to count in one call, which is far cheaper than a request per key. Use these when you want the distribution of several attributes at once — e.g. namespace, pod and node together.

**They are not the same query as the singular fields.** All the keys share one filter set, so a key's own filter is _not_ excluded (ask for `k8s.pod.name` while filtering on `k8s.pod.name` and you get back only the pod you filtered to), and `facetSearch` does not apply. When you need either, ask for that key on the singular field instead. Up to 50 keys per request.

## query.facetSearch

Case-insensitive substring match over the faceted field's _own_ values (e.g. return only service names containing `kafka`). Distinct from `searchTerm`, which searches log bodies. Use it to search past the 100-value result cap. Only applies to a single-target request.

## query.dateRange

Date range for the counts. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels. Ignored when faceting on `severity_text` (that field's own filter is excluded) and when faceting a resource attribute (rollup has no severity dimension).

## query.serviceNames

Filter by service names. Ignored when faceting on `service_name` (that field's own filter is excluded).

## query.searchTerm

Full-text search across log bodies. Ignored when faceting a resource attribute.

## query.filterGroup

Property filters to narrow results. Same format as `query-logs` filters.

# Examples

## Severity distribution in the last hour

```json
{
  "query": {
    "facetField": "severity_text",
    "dateRange": { "date_from": "-1h" }
  }
}
```

## Which services produce errors over the last day

```json
{
  "query": {
    "facetField": "service_name",
    "severityLevels": ["error", "fatal"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Which pods a service's logs come from

```json
{
  "query": {
    "facetResourceAttribute": "k8s.pod.name",
    "serviceNames": ["checkout"],
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Several attributes at once

```json
{
  "query": {
    "facetResourceAttributes": ["k8s.namespace.name", "k8s.pod.name"],
    "facetAttributes": ["log.iostream"],
    "dateRange": { "date_from": "-1h" }
  }
}
```

## Which services emit a specific error message

```json
{
  "query": {
    "facetField": "service_name",
    "searchTerm": "connection reset",
    "dateRange": { "date_from": "-1d" }
  }
}
```
