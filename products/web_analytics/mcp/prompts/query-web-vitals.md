Per-page Core Web Vitals breakdown — one metric at one percentile, with pages bucketed into `good` / `needs_improvements` / `poor` bands. Mirrors the in-product **Web analytics → Web vitals** tab.

# When to use this vs `query-trends` / `execute-sql`

Use `query-web-vitals` for **page-level** vitals questions: "which pages are slow?", "where is LCP bad?", "audit our Core Web Vitals". One call replaces a hand-written percentile query over `$web_vitals` and classifies each page against the band thresholds for you.

Use `query-trends` on the `$web_vitals` event (property math on `$web_vitals_LCP_value` etc.) for a **site-wide trend over time** — this tool has no time axis; it aggregates the whole window.

Reach for `execute-sql` only for shapes neither covers (e.g. per-page sample counts, device splits per page, or custom baselines).

Requires the project to capture the `$web_vitals` event (`capture_performance` in posthog-js). If results come back empty, check capture with `read-data-schema` before concluding pages are fine.

# Inputs

Every input is optional, so `{}` returns LCP at p75 over the last 7 days against the standard bands.

- `metric`: `LCP` (load, ms), `INP` (interactivity, ms), `CLS` (layout stability, unitless), or `FCP` (first paint, ms). Defaults to `LCP`. One metric per call — run up to four calls for a full audit.
- `percentile`: defaults to `p75`, the percentile the Google bands are defined at. `p90`/`p99` show the slow tail.
- `thresholds`: `[good, poor]` boundaries for the chosen metric. Defaults to the standard Google values for `metric`, so only set it for your own bands:

| Metric | thresholds     |
| ------ | -------------- |
| LCP    | `[2500, 4000]` |
| INP    | `[200, 500]`   |
| CLS    | `[0.1, 0.25]`  |
| FCP    | `[1800, 3000]` |

- `dateRange`: defaults to the last 7 days — a good window for a stable percentile; shorter windows get noisy on low-traffic pages.
- `properties`: event and person filters only (the runner ignores session and cohort filters) — e.g. an event filter on `$host` to scope one domain of a multi-domain project, or on `$device_type` (`Mobile`/`Desktop`) to isolate a population.
- `filterTestAccounts`, `doPathCleaning`: same semantics as the other web analytics tools.

# Reading the result

Each band lists `{path, value}` pairs. A page in `poor` at p75 on a high-traffic route is a real, citable problem even if it never changed. Percentiles on low-traffic pages wobble — corroborate a surprising result with a sample count via `execute-sql` before making strong claims. Mobile values run 2–3× desktop, so a pooled percentile can hide a mobile-only problem: when a page looks borderline, re-run with a `$device_type` filter.

# Examples

LCP at p75 over the last 7 days, standard bands — the smallest call that returns data:

```json
{}
```

Worst LCP pages at p75, last 7 days, marketing site only:

```json
{
  "metric": "LCP",
  "percentile": "p75",
  "thresholds": [2500, 4000],
  "properties": [{ "type": "event", "key": "$host", "operator": "exact", "value": ["example.com"] }]
}
```
