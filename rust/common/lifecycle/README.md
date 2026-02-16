# lifecycle

Unified app lifecycle management: signal trapping (SIGINT/SIGTERM), component registration with RAII drop guards, coordinated graceful shutdown, heartbeat-based liveness, K8s readiness/liveness probes, and metrics. The monitor runs on a dedicated OS thread with an isolated tokio runtime so it stays responsive regardless of app workload.

## Usage

### Worker (no HTTP server)

Register components **before** calling `monitor()` or `monitor_background()`. In your component task, **always** call `handle.work_completed()` before returning (on both shutdown and error paths), or the handle's drop guard will signal "component died" and trigger shutdown.

```rust
use std::time::Duration;
use lifecycle::{ComponentOptions, Manager, ManagerOptions};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut manager = Manager::new(ManagerOptions {
        name: "my-worker".into(),
        global_shutdown_timeout: Duration::from_secs(30),
        ..Default::default()
    });

    let handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(10))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    tokio::spawn(consumer_loop(handle));

    manager.monitor().await?;
    Ok(())
}

async fn consumer_loop(handle: lifecycle::Handle) {
    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => {
                // Drain in-flight work, then signal done. Must call work_completed() before return.
                drain().await;
                handle.work_completed();
                return;
            }
            msg = recv_message() => {
                if let Err(e) = process(msg).await {
                    handle.signal_failure(e.to_string());
                    handle.work_completed();
                    return;
                }
                handle.report_healthy();
            }
        }
    }
}
```

### With Axum (readiness / liveness / graceful shutdown)

Use `monitor_background()` so the monitor runs while the server is up; after `axum::serve` returns (due to shutdown signal), await the guard to get the final result.

```rust
use std::time::Duration;
use axum::{Router, routing::get};
use lifecycle::{ComponentOptions, Manager, ManagerOptions};
use tokio::net::TcpListener;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut manager = Manager::new(ManagerOptions {
        name: "my-api".into(),
        global_shutdown_timeout: Duration::from_secs(30),
        ..Default::default()
    });

    let handle = manager.register(
        "processor",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(10))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    tokio::spawn(processor_loop(handle));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let shutdown = manager.shutdown_signal();

    let app = Router::new()
        .route("/_readiness", get({
            let r = readiness.clone();
            move || async move { r.check().await }
        }))
        .route("/_liveness", get({
            let l = liveness.clone();
            move || async move { l.check().into_response() }
        }));

    let guard = manager.monitor_background();

    let listener = TcpListener::bind("0.0.0.0:8080").await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown)
        .await?;

    guard.wait().await?;
    Ok(())
}
```

### Handle API summary

| Method | Use when |
|--------|----------|
| `shutdown_recv()` | In `tokio::select!` to react to shutdown (e.g. stop consuming, drain, then `work_completed()`). |
| `cancellation_token()` | Pass to sub-tasks or APIs that take a `CancellationToken`. |
| `is_shutting_down()` | Sync check (e.g. in a hot loop) to bail out. |
| `signal_failure(reason)` | Fatal error; triggers global shutdown. Call `work_completed()` after. |
| `request_shutdown()` | Request clean shutdown (non-fatal). Then finish work and `work_completed()`. |
| `work_completed()` | **Always** call before your component task returns (shutdown or error path). Otherwise the drop guard signals "died". |
| `report_healthy()` | Liveness heartbeat (call more often than `liveness_deadline`). |
| `report_unhealthy()` | Mark component unhealthy for liveness. |
| `report_healthy_blocking()` | Same as `report_healthy()`; use from sync/blocking contexts (e.g. rdkafka callbacks). |

### Common pitfalls

1. **Forgetting `work_completed()`** — When the **last** clone of a `Handle` is dropped (e.g. when your component task returns), the drop guard runs. If you never called `work_completed()`, the manager receives "component died" and shuts down. So: on every exit path from your component (normal shutdown, error, early return), call `work_completed()` before returning.
2. **Register order** — Register all components before calling `monitor()` or `monitor_background()`; the manager is consumed by those calls, so you cannot register afterward.
3. **Liveness** — If you use `with_liveness_deadline`, the component must call `report_healthy()` (or `report_healthy_blocking()`) more frequently than that interval, or the liveness probe will report the component as stalled/unhealthy. With `HealthStrategy::All`, one stalled component makes the app unhealthy.

## Metrics

The crate emits metrics via the `metrics` facade (no recorder installed by this crate; the parent app does that). All metrics are segmented by **`service_name`**: set `ManagerOptions::name` to your app’s service name (e.g. K8s service name or logical app name) so dashboards and alerts can filter by service.

| Metric | Type | Labels | When emitted |
|--------|------|--------|--------------|
| `lifecycle_shutdown_initiated_total` | Counter | `service_name`, `trigger_component`, `trigger_reason` | Once when shutdown begins |
| `lifecycle_component_shutdown_duration_seconds` | Histogram | `service_name`, `component`, `result` | Once per component at completion/timeout/death |
| `lifecycle_component_shutdown_result_total` | Counter | `service_name`, `component`, `result` | Once per component at completion/timeout/death |
| `lifecycle_shutdown_completed_total` | Counter | `service_name`, `clean` | Once when monitor returns successfully |
| `lifecycle_component_healthy` | Gauge | `service_name`, `component` | Continuously during normal operation |

Label values: `trigger_reason` = `signal`, `prestop`, `failure`, `requested`, `died`; `result` = `completed`, `timeout`, `died`; `clean` = `true` / `false`.

`lifecycle_shutdown_completed_total` is **not** emitted on global timeout or if the process is killed; that asymmetry with `lifecycle_shutdown_initiated_total` is how incomplete shutdowns (e.g. SIGKILL) are detected.

## Grafana / Prometheus setup

1. **Service name** — When creating the manager, set `ManagerOptions::name` to your service name (e.g. `"kafka-deduplicator"`, `"ingestion-api"`). This value is emitted as the `service_name` label on every lifecycle metric.
2. **Grafana variable** — In dashboards, define a variable (e.g. `service_name`) of type *Query* that lists values:  
   `label_values(lifecycle_shutdown_initiated_total, service_name)`  
   so users can filter panels by service.
3. **Prometheus scrape** — Ensure your app exposes the same metrics endpoint Prometheus scrapes (e.g. `/metrics`); the lifecycle crate only emits to the `metrics` facade; the app wires the recorder/exporter.

### Recommended panels (PromQL, segment by `service_name`)

- **What triggered shutdown?** (table)  
  `increase(lifecycle_shutdown_initiated_total{service_name="$service_name"}[$__range])`  
  by `trigger_component`, `trigger_reason`.

- **Component shutdown duration** (heatmap)  
  `histogram_quantile(0.95, rate(lifecycle_component_shutdown_duration_seconds_bucket{service_name="$service_name"}[5m]))`  
  by `component`, `result`.

- **Shutdown result breakdown** (stacked bar)  
  `sum by (component, result) increase(lifecycle_component_shutdown_result_total{service_name="$service_name"}[$__range])`.

- **Incomplete shutdowns (SIGKILL detection)** (stat; alert if > 0)  
  `increase(lifecycle_shutdown_initiated_total{service_name="$service_name"}[1h]) - increase(lifecycle_shutdown_completed_total{service_name="$service_name"}[1h])`.

- **Component liveness** (table)  
  `lifecycle_component_healthy{service_name="$service_name"}`  
  (one row per component).

### Alert rules (segment by `service_name`)

- Component timeout rate > 0 over 5m:  
  `increase(lifecycle_component_shutdown_result_total{service_name="$service_name", result="timeout"}[5m]) > 0`
- Incomplete shutdown count > 0 over 1h:  
  `increase(lifecycle_shutdown_initiated_total{service_name="$service_name"}[1h]) - increase(lifecycle_shutdown_completed_total{service_name="$service_name"}[1h]) > 0`
- Component unhealthy for > 2 consecutive scrapes: e.g. alert when `lifecycle_component_healthy{service_name="$service_name"}` is 0 for a given component for 2 scrape intervals.

## SIGKILL detection

SIGKILL cannot be trapped. Detection is by absence:

- **Logs**: "Lifecycle: shutdown initiated" present but "Lifecycle: shutdown complete" absent within the expected window → process was killed mid-shutdown. In Loki: `{app="my-worker"} |= "Lifecycle: shutdown initiated"` and absence of `|= "Lifecycle: shutdown complete"`.
- **Metrics**: `increase(lifecycle_shutdown_initiated_total[1h]) - increase(lifecycle_shutdown_completed_total[1h]) > 0` means some shutdowns did not complete.
- **K8s**: Pod exit code 137 is the authoritative SIGKILL signal (infrastructure-level, not emitted by this crate).
