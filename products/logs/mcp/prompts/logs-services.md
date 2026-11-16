List every service that logged in the window, with its health against a baseline. All other parameters go inside `query`:

```json
{ "query": { "dateRange": { "date_from": "-24h" }, "compare": "previous_day", "environment": "production" } }
```

Each row has `log_count`, `error_count`, `error_rate_pct` and `last_seen`. With `compare`, each row also gets a `status` and a short `reason`.
The status is `ok`, `degraded` (5% errors or more), `regressed` or `improved` (error rate up or down by 1 pp and 2x), `recovered`, `new` (no baseline logs) or `silent` (baseline logs, none now).
Silent services appear only with a baseline.
This is the entry point for "which services are silent, new or worse".
Use `logs-group-by` for counts by pattern or attribute, `logs-patterns-diff` for the error patterns behind a regression, and `logs-count-ranges` for when a spike started.

`compare` is `none` (default), `previous_period`, `previous_day` or `previous_week`. `baselineDateRange`, next to `query`, sets an explicit baseline.
`environment` matches the first set resource attribute of `deployment.environment.name`, `deployment.environment` and `env`.
`window` gives the absolute UTC bounds. `next` holds prefilled follow-up calls. It is empty when `environment` is set, because those tools do not filter by environment.
