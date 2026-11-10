Show what happened around one log line, one trace, or one run. Use it instead of many `query-logs` calls when you have an id and want the story around it.

```json
{ "query": { "anchor": { "traceId": "4bf92f3577b34da6a3ce929d0e0e4736" }, "include": ["spans"] } }
```

Give exactly one anchor in `query.anchor`:

- `{"traceId": "..."}`: the server reads the trace's spans first, then the logs of those services in the trace time range plus `padding` (default 30s).
- `{"logUuid": "...", "timestamp": "...Z"}`: lines of the same service around the log (default 5m). `timestamp` is required.
- `{"attribute": {"key": "workflow_run_id", "value": "..."}, "around": "...Z"}`: every log with that value, any service. `around` is required.

The response has:

- `anchor`: the time span and services of the anchor.
- `correlation_keys`: id-like attributes of the anchor log, with the count of logs that share each value. Use one as the next attribute anchor.
- `timeline`: rows with `t_offset_ms`, `service`, `severity`, `body` (300 characters) and `attrs` (only attributes that differ from the anchor log).
- `spans_summary` with `include: ["spans"]`: root, error spans and the 5 slowest spans with self time.
- `truncated` and `next_cursor`. Pass `after: next_cursor` with the same anchor for the next page.
- `next`: prefilled follow-up calls.

Add `severityLevels: ["warn", "error", "fatal"]` to see only problems.
