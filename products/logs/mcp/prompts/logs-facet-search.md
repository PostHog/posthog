Search one facet's values by substring, with cross-filtered counts.

Use this when you know the facet and want only the values matching a fragment — service names
containing `kafka`, namespaces containing `prod`. To get a facet's top values instead, or several
facets at once, use `logs-facet-values-create`.

The match runs before the row limit, so a value ranked below the facet's top 100 still comes back.
That is the reason this is its own tool: the search has to run against one key, so it can't be
combined with the multi-key form.

## query.facetField / query.facetResourceAttribute / query.facetAttribute

The facet whose values to search. Provide exactly one.

- `facetField` — a top-level column, either `severity_text` or `service_name`.
- `facetResourceAttribute` — a resource attribute key, e.g. `k8s.namespace.name`.
- `facetAttribute` — a log attribute key, e.g. `log.iostream`.

**Limitation:** the two attribute forms are served from a pre-aggregated rollup that has no body
dimension, so `searchTerm` and log-attribute filters are **ignored** for them. `serviceNames`,
`severityLevels` and resource-attribute filters do apply. Search a column instead if you need those.

## query.facetSearch

Required. Case-insensitive substring the returned values must contain. Distinct from `searchTerm`,
which searches log bodies.

## Response

A flat list of `{value, count}`, ordered by count descending. The searched facet's own filter is
excluded from the counts, so searching a facet you have already filtered on still returns its other
values.
