Per-page Core Web Vitals breakdown — one metric at one percentile, with pages bucketed into `good` / `needs_improvements` / `poor` bands. Mirrors the in-product **Web analytics → Web vitals** tab.

# When to use this vs `query-trends` / `execute-sql`

Use `query-web-vitals` for **page-level** vitals questions: "which pages are slowest?", "where is LCP bad?", "audit our Core Web Vitals". One call replaces a hand-written percentile query over `$web_vitals`, classifies each page against the band thresholds, and lists each band worst page first with its sample count.

Use `query-trends` on the `$web_vitals` event (property math on `$web_vitals_LCP_value` etc.) for a **site-wide trend over time** — this tool has no time axis; it aggregates the whole window.

Reach for `execute-sql` only for shapes neither covers (e.g. device splits per page, or custom baselines).

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
- `properties`: event and person filters only (the runner ignores session and cohort filters) — e.g. an event filter on `$host` to scope one domain of a multi-domain project, or on `$device_type` (`Mobile`/`Desktop`) to isolate a population.
- `minSamples`: drop pages with fewer samples than this. On a busy site set it (50–100) so one-off slow loads on rarely visited pages do not fill the `poor` band ahead of real problems; leave it unset on a small site.
- `filterTestAccounts`: same semantics as the other web analytics tools.
- `doPathCleaning`: on by default, so the team's path-cleaning rules roll `/project/123/...` style paths into one row. Set `false` to see raw paths.

# Reading the result

Each band lists `{path, value, count}` rows, **worst value first**, capped at 20 per band — so "the slowest pages" are the first rows of `poor`, then `needs_improvements`. `count` is the number of samples behind the percentile; quote it, and treat a page with a handful of samples as noise rather than a finding. A response served from precomputed aggregates (`preComputeStrategy` other than `live`) carries no `count`: pass `minSamples: 1` to force a live scan when the counts matter. A page in `poor` at p75 on a high-traffic route is a real, citable problem even if it never changed. Mobile values run 2–3× desktop, so a pooled percentile can hide a mobile-only problem: when a page looks borderline, re-run with a `$device_type` filter.

# Example

Worst LCP pages at p75, last 7 days, marketing site only, ignoring pages with under 50 samples:

```json
{
  "metric": "LCP",
  "percentile": "p75",
  "thresholds": [2500, 4000],
  "minSamples": 50,
  "properties": [{ "type": "event", "key": "$host", "operator": "exact", "value": ["example.com"] }]
}
```
