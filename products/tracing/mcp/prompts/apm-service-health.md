Score every service in one call: requests, throughput, error rate, p50/p95/p99 and a status, compared with a baseline window.

Use this first for "how healthy are my services" or a daily report.
Use `apm-spans-aggregate` next for the operations inside one service. Use `apm-spans-count` only for a raw count.

All parameters go inside `query`, and every one is optional:

```json
{ "query": { "dateRange": { "date_from": "-24h" }, "compare": "previous_day", "environment": "production" } }
```

Each row has a `status`: `silent` (spans stopped), `regressed` (error rate or p95 got worse), `degraded` (error rate 5% or more), `new`, `recovered`, `improved` or `ok`, and a short `reason`.
Rows come worst first.

`window` gives the absolute UTC times the server used. Reuse `window.current` as `dateRange` in follow-up calls.
`next` holds prefilled follow-up calls for regressed and degraded services. It is empty when `environment` is set, because those tools cannot repeat the environment fallback.
`spanScope: "entry"` (default) counts one span per request. Use `"all"` to count every span.
A 400 that names the 10 GB cap means the window is too wide. Use the window it suggests, or add `serviceNames`.
