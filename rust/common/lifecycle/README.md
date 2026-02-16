# lifecycle

Unified app lifecycle management: signal trapping (SIGINT/SIGTERM), component registration with RAII drop guards, coordinated graceful shutdown, heartbeat-based liveness, K8s readiness/liveness probes, and metrics. The monitor runs on a dedicated OS thread with an isolated tokio runtime so it stays responsive regardless of app workload.

## Metrics

The crate emits metrics via the `metrics` facade (no recorder installed by this crate; the parent app does that).

| Metric | Type | Labels | When emitted |
|--------|------|--------|--------------|
| `lifecycle_shutdown_initiated_total` | Counter | `app`, `trigger_component`, `trigger_reason` | Once when shutdown begins |
| `lifecycle_component_shutdown_duration_seconds` | Histogram | `app`, `component`, `result` | Once per component at completion/timeout/death |
| `lifecycle_component_shutdown_result_total` | Counter | `app`, `component`, `result` | Once per component at completion/timeout/death |
| `lifecycle_shutdown_completed_total` | Counter | `app`, `clean` | Once when monitor returns successfully |
| `lifecycle_component_healthy` | Gauge | `app`, `component` | Continuously during normal operation |

Label values: `trigger_reason` = `signal`, `prestop`, `failure`, `requested`, `died`; `result` = `completed`, `timeout`, `died`; `clean` = `true` / `false`.

`lifecycle_shutdown_completed_total` is **not** emitted on global timeout or if the process is killed; that asymmetry with `lifecycle_shutdown_initiated_total` is how incomplete shutdowns (e.g. SIGKILL) are detected.

## PromQL / Grafana

- **What triggered shutdown?**  
  `increase(lifecycle_shutdown_initiated_total{app="$app"}[$__range])` by `trigger_component`, `trigger_reason` (table).

- **Component shutdown duration**  
  `histogram_quantile(0.95, rate(lifecycle_component_shutdown_duration_seconds_bucket{app="$app"}[5m]))` by `component`, `result` (heatmap).

- **Shutdown result breakdown**  
  `sum by (component, result) increase(lifecycle_component_shutdown_result_total{app="$app"}[$__range])` (stacked bar).

- **Incomplete shutdowns (SIGKILL detection)**  
  `increase(lifecycle_shutdown_initiated_total{app="$app"}[1h]) - increase(lifecycle_shutdown_completed_total{app="$app"}[1h])` (stat panel; alert if > 0).

- **Component liveness**  
  `lifecycle_component_healthy{app="$app"}` (table, one row per component).

### Alert rules

- Component timeout rate > 0 over 5m.
- Incomplete shutdown count > 0 over 1h.
- Component unhealthy for > 2 consecutive scrapes.

## SIGKILL detection

SIGKILL cannot be trapped. Detection is by absence:

- **Logs**: "Lifecycle: shutdown initiated" present but "Lifecycle: shutdown complete" absent within the expected window → process was killed mid-shutdown. In Loki: `{app="my-worker"} |= "Lifecycle: shutdown initiated"` and absence of `|= "Lifecycle: shutdown complete"`.
- **Metrics**: `increase(lifecycle_shutdown_initiated_total[1h]) - increase(lifecycle_shutdown_completed_total[1h]) > 0` means some shutdowns did not complete.
- **K8s**: Pod exit code 137 is the authoritative SIGKILL signal (infrastructure-level, not emitted by this crate).
