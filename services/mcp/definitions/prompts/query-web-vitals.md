Per-page Core Web Vitals breakdown — one metric at one percentile, with pages bucketed into `good` / `needs_improvements` / `poor` bands. Mirrors the in-product **Web analytics → Web vitals** tab.

# When to use this vs `query-trends` / `execute-sql`

Use `query-web-vitals` for **page-level** vitals questions: "which pages are slow?", "where is LCP bad?", "audit our Core Web Vitals". One call replaces a hand-written percentile query over `$web_vitals` and classifies each page against the band thresholds for you.

Use `query-trends` on the `$web_vitals` event (property math on `$web_vitals_LCP_value` etc.) for a **site-wide trend over time** — this tool has no time axis; it aggregates the whole window.

Reach for `execute-sql` only for shapes neither covers (e.g. per-page sample counts, device splits per page, or custom baselines).

Requires the project to capture the `$web_vitals` event (`capture_performance` in posthog-js). If results come back empty, check capture with `read-data-schema` before concluding pages are fine.

# Inputs

- `metric` (required): `LCP` (load, ms), `INP` (interactivity, ms), `CLS` (layout stability, unitless), or `FCP` (first paint, ms). One metric per call — run up to four calls for a full audit.
- `percentile` (required): use `p75` unless the user asks otherwise — the Google bands are defined at p75. `p90`/`p99` show the slow tail.
- `thresholds` (required): `[good, poor]` boundaries for the chosen metric. Standard Google values:

| Metric | thresholds     |
| ------ | -------------- |
| LCP    | `[2500, 4000]` |
| INP    | `[200, 500]`   |
| CLS    | `[0.1, 0.25]`  |
| FCP    | `[1800, 3000]` |

- `dateRange`: defaults to the last 7 days — a good window for a stable percentile; shorter windows get noisy on low-traffic pages.
- `properties`: event/person/session/cohort filters — e.g. an event filter on `$host` to scope one domain of a multi-domain project, or on `$device_type` (`Mobile`/`Desktop`) to isolate a population.
- `filterTestAccounts`, `doPathCleaning`: same semantics as the other web analytics tools.

# Reading the result

Each band lists `{path, value}` pairs. A page in `poor` at p75 on a high-traffic route is a real, citable problem even if it never changed. Percentiles on low-traffic pages wobble — corroborate a surprising result with a sample count via `execute-sql` before making strong claims. Mobile values run 2–3× desktop, so a pooled percentile can hide a mobile-only problem: when a page looks borderline, re-run with a `$device_type` filter.

# Example

Worst LCP pages at p75, last 7 days, marketing site only:

```json
{
  "metric": "LCP",
  "percentile": "p75",
  "thresholds": [2500, 4000],
  "properties": [{ "type": "event", "key": "$host", "operator": "exact", "value": ["example.com"] }]
}
```
