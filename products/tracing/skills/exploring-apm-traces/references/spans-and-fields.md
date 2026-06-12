# APM span field reference

Fields returned by `apm-trace-get` and `query-apm-spans`.

## Span fields

| Field            | Type       | Description                                                                                                                                                                         |
| ---------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uuid`           | string     | Internal row UUID (rarely useful for analysis)                                                                                                                                      |
| `trace_id`       | hex string | 32-char hex ID linking every span in one trace                                                                                                                                      |
| `span_id`        | hex string | 16-char hex ID for this span                                                                                                                                                        |
| `parent_span_id` | hex string | Parent span's hex ID. Zero-padded `"00000000…"` for root spans                                                                                                                      |
| `name`           | string     | Operation name (e.g. `HTTP GET /api/users`, `db.query`)                                                                                                                             |
| `kind`           | int 0–5    | OpenTelemetry span kind (see enum below)                                                                                                                                            |
| `service_name`   | string     | Service that emitted the span                                                                                                                                                       |
| `status_code`    | int 0–2    | OpenTelemetry status (see enum below). `2` is the only error indicator                                                                                                              |
| `timestamp`      | ISO 8601   | Start time                                                                                                                                                                          |
| `end_time`       | ISO 8601   | End time                                                                                                                                                                            |
| `duration_nano`  | int        | Duration in **nanoseconds** (1s = 1_000_000_000)                                                                                                                                    |
| `is_root_span`   | bool       | Convenience flag for the trace entry — prefer this over comparing parent ID                                                                                                         |
| `matched_filter` | int 0/1    | `1` if this span matched the `query-apm-spans` filter; `0` if it only shares a trace with a match (root/prefetched sibling). Always present; only meaningful from `query-apm-spans` |
| `attributes`     | map        | Span-level OTel attributes the span set, e.g. `http.method`, `db.statement`, `net.peer.name`. A string-keyed map                                                                    |

**Returned in the payload:** span-level `attributes` (above) — read them straight off the span.

**Not returned in the payload:** resource attributes (k8s labels, `service.version`, deployment metadata). Discover them via `apm-attributes-list` (type `resource`) and fetch values via `apm-attribute-values-list`.

## `kind` enum (OpenTelemetry span kind)

| Value | Label         | Meaning                                    |
| ----- | ------------- | ------------------------------------------ |
| `0`   | `Unspecified` | Default when no kind is set                |
| `1`   | `Internal`    | Internal operation, no remote boundary     |
| `2`   | `Server`      | Inbound side of a synchronous remote call  |
| `3`   | `Client`      | Outbound side of a synchronous remote call |
| `4`   | `Producer`    | Producer side of an async messaging system |
| `5`   | `Consumer`    | Consumer side of an async messaging system |

A synchronous downstream call typically pairs a `Client` span on the caller with a matching `Server` span on the callee.

## `status_code` enum (OpenTelemetry span status)

| Value | Label   | Meaning                           |
| ----- | ------- | --------------------------------- |
| `0`   | `Unset` | No status reported                |
| `1`   | `OK`    | Operation completed without error |
| `2`   | `Error` | Operation failed                  |

UI filter chips for `status_code = OK` match `{0, 1}`, but the underlying integer column only stores the raw value. When filtering programmatically, treat any span with `status_code == 2` as the error set.

## Filter property types in `query-apm-spans`

| `type` value              | Filters on                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------ |
| `span`                    | Built-in span fields: `trace_id`, `span_id`, `duration`, `name`, `kind`, `status_code`, `is_root_span` |
| `span_attribute`          | Span-level attributes (e.g. `http.method`, `db.statement`)                                             |
| `span_resource_attribute` | Resource-level attributes (e.g. `k8s.pod.name`, `service.version`)                                     |

`duration` filters take values in **nanoseconds** (the column is `duration_nano`). The frontend translates `1000ms` → `1_000_000_000` before sending.

`is_root_span` filters take `true`/`false` — filter `true` to isolate entry/request spans (e.g. request counts for RED metrics).
