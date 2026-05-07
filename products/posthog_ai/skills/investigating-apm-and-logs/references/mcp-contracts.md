# MCP contracts: logs vs APM

## Wrapper shapes

- **APM span query / sparkline:** parameters live under a top-level **`query`** object (`query.dateRange`, `query.serviceNames`, …).
- **Logs `query-logs`:** body shape is defined by the logs MCP tool schema — typically includes **`dateRange`**, **`serviceNames`** (often required or strongly expected for cost), **`limit`**, optional `severityLevels`, `filterGroup`, etc. Do not assume parity with the APM `query` wrapper.

## `dateRange` quirks

- Some tracing list endpoints expect **`dateRange` as a JSON string** in query params (e.g. GET `service-names`). When a tool returns empty results, retry with an explicit **`{"date_from":"-24h"}`** (or the window the user asked for) before concluding there is no data.
- **Relative bounds** (`-1h`, `-24h`) are shared; always align the same window across snapshot, logs, and spans when comparing counts.

## Scopes and product gate

- **`apm-logs-signal-snapshot`** requires **both** `tracing:read` and `logs:read` on the API key or OAuth token. If the tool is missing from the client, verify scopes before falling back to HogQL.
- The same endpoint also requires the PostHog **`tracing`** feature flag for the project (same key as the Tracing product in the app). **HTTP 403** with a message about the `tracing` feature flag means the snapshot is intentionally unavailable — use [hogql-recipes](./hogql-recipes.md) for joinability instead.

## Response fields to read

- **Span query:** `warnings`, `resolvedDateRange`, `exemplarTraceIds.slowest_trace_id`, `hasMore`, `nextCursor`.
- **Trace get:** `truncated`, `maxSpans` when large traces are capped.
- **Snapshot:** `joinableTraceIdPercent`, `serviceNamesOverlap`, `resolvedDateRange`.
