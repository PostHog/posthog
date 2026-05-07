# Decision tree: which signal answers which question?

## User asks about "errors" or "5xx"

1. **Clarify layer**
   - **Reverse proxy / load balancer logs** (e.g. Caddy, nginx): often log connection failures and **502** with **no** or **zero** `trace_id`. Lead with **logs** and infra reachability.
   - **Application HTTP status**: use span attribute **`http.status_code`** (`span_attribute` filter) or parse structured log JSON if the log line carries `status`.
   - **OpenTelemetry span health**: use **`statusCodes: [2]`** on APM tools (not HTTP).

2. **If APM sparkline for OTEL errors is flat zero but logs show errors**
   - Do not conclude "no errors in the system."
   - Conclude: **no error-status spans in range for those filters**, or instrumentation never marks spans as Error / does not export spans for that path.

## User asks "correlate logs and traces"

1. Run **`apm-logs-signal-snapshot`** (or HogQL joinability recipe).
2. **High `joinableTraceIdPercent`:** use `trace_id` to bridge `query-logs` and `apm-trace-get`.
3. **Low percent:** correlate by **time window + service + request path** (log fields and span `name` / attributes), not by ID — state that limitation explicitly.

## User asks "which services exist?"

- **Log services:** `logs-count` / attribute value listing / `query` aggregates on `logs.service_name` (see HogQL recipes).
- **Trace services:** `apm-services-list` (pass explicit `dateRange` if the default window is empty).

Never assume the two lists match without checking the snapshot overlap fields.
