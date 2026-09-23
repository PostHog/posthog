Return per-value counts for a single facet — the distribution of a log dimension across a filter set, ordered by count descending. This is the cheap way to see the _shape_ of a log stream (e.g. "which services produce the errors?") without pulling raw rows.

All parameters go inside `query` — top-level fields are rejected. Provide **exactly one** of `query.facetField` or `query.facetResourceAttribute` — not both, not neither:

```json
{ "query": { "facetField": "service_name", "dateRange": { "date_from": "-1h" } } }
```

Counts are cross-filtered: every active filter is applied _except the faceted field's own filter_, so you see the full distribution rather than collapsing to your own selection. Faceting `service_name` with `serviceNames: ["api"]` still returns every service, not just `api`.

# When to use

- As the drill-down loop for an investigation: facet `service_name` filtered to `severity=error` → find the hot service → add it to `serviceNames` → facet a resource attribute like `k8s.pod.name` → find the bad pod. Each call is one cheap aggregation that narrows the search space before you pull raw rows with `query-logs`.
- To confirm the severity mix in a window before committing to a query: facet `severity_text`.
- To find how log volume is distributed across severity or service for one person's or session's logs — e.g. "which services logged for this session?" Facet `service_name` with `sessionId` set; unlike the general case this honors every active filter, including `searchTerm`.

## Pick the right tool

- Counts for an arbitrary **attribute** value (any log or resource attribute key) → use `logs-attribute-values-list`. It returns `{value, count}` for any key and is the general-purpose choice for attributes.
- Per-service log/error counts and error rates with a sparkline → use `logs-services-create`.
- Use **this** tool for `severity_text` / `service_name` distribution cross-filtered by severity, service, and `filterGroup` — the one thing the tools above can't do. For body-search-filtered service/severity counts, scope to `personId`/`sessionId` (see below) or use `query-logs` directly.

# Parameters

## query.facetField

Top-level column to facet on: `severity_text` or `service_name`. Provide this OR `facetResourceAttribute`, not both. Counts come from a pre-aggregated rollup, so this path honors `severityLevels`, `serviceNames`, and this field's own-filter exclusion, but not `searchTerm`, log-attribute filters, or resource-attribute filters. When `personId` or `sessionId` is set, counts come from the logs table directly instead, honoring every filter exactly.

## query.facetResourceAttribute

Resource attribute key to facet on, e.g. `k8s.namespace.name`, `k8s.pod.name`, `host.name`. Provide this OR `facetField`, not both.

**Limitation:** this path is served from a pre-aggregated rollup that has no body dimension. It honors `severityLevels`, `serviceNames`, and other resource-attribute filters — `searchTerm` and log-attribute filters are **ignored**. If you need those applied, narrow with `logs-attribute-values-list`.

## query.facetSearch

Case-insensitive substring match over the faceted field's _own_ values (e.g. return only service names containing `kafka`). Distinct from `searchTerm`, which searches log bodies. Use it to search past the 100-value result cap.

## query.dateRange

Date range for the counts. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels. Ignored when faceting on `severity_text` (that field's own filter is excluded).

## query.serviceNames

Filter by service names. Ignored when faceting on `service_name` (that field's own filter is excluded).

## query.searchTerm

Full-text search across log bodies. Ignored when faceting a resource attribute, and ignored when faceting a column (`severity_text`/`service_name`) unless `personId` or `sessionId` is set.

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

## Which services logged for a specific session

```json
{
  "query": {
    "facetField": "service_name",
    "sessionId": "0198f6c2-9a3b-7c9e-9e2e-6a1e8e6a9b3f",
    "searchTerm": "connection reset",
    "dateRange": { "date_from": "-1d" }
  }
}
```
