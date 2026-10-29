Compare the log patterns of a current window with a baseline window. Use it for "which error patterns are new or worse?" in one call. Do not mine two windows and match templates yourself.

Put all parameters in `query`. The only sibling is the optional `baselineDateRange`. Omit it to compare with the same window one week earlier.

```json
{ "query": { "dateRange": { "date_from": "-24h" }, "severityLevels": ["error", "fatal"], "limit": 25 } }
```

Each entry has:

- `classification`: `new`, `rate_shift`, `gone` or `unchanged` ("no confident claim").
- `rate_ratio`: current rate / baseline rate, per second. 4.0 is 4x faster now.
- `masked_example`: the template with variable parts masked. It can still hold literal text from the logs, so check it before you quote it.
- `services`, `baseline_estimated_count`, and `pattern` with counts and `match_regex` / `match_patterns`.
- `first_seen_ever`: the earliest time the pattern appears in the last 14 days. It tells "new today" from "new this week". Null on the body-mining fallback.

Read the top level too:

- `window`: the absolute UTC bounds that were compared.
- `source` and `sampled`: `stored_patterns` gives exact counts. `body_mining` (`sampled: true`) gives estimates, and rare templates can be missing.
- `baseline.total_count`: if it is 0 or small, every pattern looks new.
- `next`: prefilled `query-logs` calls for the raw lines of the top suspects.

Scope `serviceNames` once you know the service.
