Returns a **single JSON summary** of how well **logs** and **OpenTelemetry trace spans** overlap for a time window — not a full investigation.

Use **`posthog:apm-logs-signal-snapshot`** at the start of cross-signal triage (before burning tokens on large `query-logs` or span pages).

## Request body

- **`dateRange`** (optional): `date_from` / `date_to` as ISO timestamps or relative strings (`-24h`, `-7d`). Defaults to last 24 hours when omitted.
- **`serviceNames`** (optional): restrict both log and span aggregates to these `service_name` values.

## Response fields (read these first)

- **`resolvedDateRange`**: UTC bounds actually applied.
- **`logsTotal`** / **`logsWithJoinableTraceId`** / **`joinableTraceIdPercent`**: share of log rows whose `trace_id` looks non-placeholder (non-empty, not all literal `0` characters after lowercasing). Low percent means you usually **cannot** jump from arbitrary log lines to `apm-trace-get`.
- **`logServiceNames`**: `{ service_name, count }[]` from logs (top 100 by volume).
- **`traceServiceNames`**: distinct span `service_name` values (up to 200).
- **`serviceNamesOverlap`**, **`logOnlyServiceNames`**, **`traceOnlyServiceNames`**: set difference helpers — log “services” and trace “services” are **not** the same namespace.
- **`sampleJoinableTraceIds`**: up to 10 example `trace_id` strings you can try with **`apm-trace-get`** when joinability is meaningful.

## What this tool does **not** do

- It does not return log bodies or span rows — use **`query-logs`** and **`query-apm-spans`** after you know whether correlation by `trace_id` is realistic.
- It does not prove application health — empty or skewed results can mean missing instrumentation, different `service_name` labels, or proxy-only errors.

## Required OAuth / API key scopes

Both **`tracing:read`** and **`logs:read`** are required.

## Product gate

The project must have the PostHog **`tracing`** feature flag enabled (same as the Tracing product in the UI). Otherwise the API returns **403** with a message about that flag — use HogQL joinability recipes from the **`investigating-apm-and-logs`** skill instead of retrying this tool.
