# lifecycle

Unified app lifecycle management for K8s services. All features are opt-in — use only what your app needs.

**Core** (always active): signal trapping, component registration with RAII drop guards, coordinated graceful shutdown, readiness probe.

**Opt-in**: health monitoring with stall detection (`with_liveness_deadline`), global shutdown timeout (`with_global_shutdown_timeout`), liveness probe, pre-stop file polling.

## Manager setup

Create a manager, register components, then run the monitor. Register all components **before** starting the monitor.

### Minimal (shutdown coordination only)

```rust
use lifecycle::{ComponentOptions, Manager, ManagerOptions};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut manager = Manager::new(
        ManagerOptions::new("my-service")
            .with_trap_signals(true),  // SIGINT/SIGTERM handling (default)
    );

    let handle = manager.register("consumer", ComponentOptions::new());

    // ... spawn tasks using the handle ...
    manager.monitor().await?;
    Ok(())
}
```

### Full-featured (health monitoring + shutdown timeout)

```rust
use std::time::Duration;
use lifecycle::{ComponentOptions, Manager, ManagerOptions};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut manager = Manager::new(
        ManagerOptions::new("my-service")
            .with_global_shutdown_timeout(Duration::from_secs(30)), // optional: cap shutdown duration
    );

    let handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(10))  // per-component shutdown budget
            .with_liveness_deadline(Duration::from_secs(30))  // must call report_healthy() within this
            .with_stall_threshold(2),                         // 2 consecutive stalled checks before shutdown
    );

    // ... spawn component tasks, wire up HTTP routes ...

    // Option A: blocking — monitor runs until all components finish or time out
    manager.monitor().await?;

    // Option B: background — returns a guard; await it after your HTTP server exits
    // let guard = manager.monitor_background();
    // axum::serve(...).with_graceful_shutdown(shutdown).await?;
    // guard.wait().await?;

    Ok(())
}
```

### ManagerOptions

All options except `name` are optional with sensible defaults. Features are opt-in — call the builder method to enable.

| Method | Effect | Default |
|--------|--------|---------|
| `ManagerOptions::new(name)` | Create options with the given service name (`service_name` label on all metrics). | `"app"` |
| `.with_global_shutdown_timeout(duration)` | Hard ceiling on total shutdown. Monitor returns `ShutdownTimeout` if exceeded. Without this, the monitor waits indefinitely for components — K8s SIGKILL is the external backstop. (see test `global_timeout_fires_when_component_hangs`) | `None` — no ceiling |
| `.with_trap_signals(bool)` | Install SIGINT/SIGTERM handlers. Set `false` in tests. | `true` |
| `.with_prestop_check(bool)` | Poll for `/tmp/shutdown` file (K8s pre-stop hook pattern). | `true` |
| `.with_health_poll_interval(duration)` | Override health monitor poll frequency. The health monitor is automatically active when any component has `with_liveness_deadline`. (see test `stall_triggers_shutdown`) | `5s` |

### register() / ComponentOptions

`register(tag, options)` — `tag` is a `&str` identifier for the component (used in metrics/logs). `options` is built with the `ComponentOptions` builder:

| Method | Effect | Default |
|--------|--------|---------|
| `ComponentOptions::new()` | Base options with defaults for all fields. | — |
| `.with_graceful_shutdown(duration)` | Max time for this component to clean up after shutdown begins. Exceeded = marked timed out. (see test `component_timeout_then_late_drop_preserves_timeout`) | `None` — waits indefinitely (bounded by `global_shutdown_timeout` if set, or K8s SIGKILL) |
| `.with_liveness_deadline(duration)` | Component must call `report_healthy()` within this interval or the health monitor considers it stalled. After `stall_threshold` consecutive stalled checks, the manager triggers global shutdown. (see test `stall_triggers_shutdown`) | `None` — no health monitoring |
| `.with_stall_threshold(n)` | Number of consecutive stalled health checks before the manager triggers global shutdown. Set higher for tolerance of transient hiccups. Only meaningful with `with_liveness_deadline`. (see test `stall_threshold_allows_recovery`) | `1` — immediate shutdown on first stall |

## K8s readiness and liveness

**Readiness** (`/_readiness`) returns 200 until shutdown begins, then 503. K8s uses this to stop routing traffic to the pod. No per-component logic — it's purely "is the app accepting work?" (see test `readiness_200_until_shutdown_then_503`)

**Liveness** (`/_liveness`) always returns 200 — it means "the process is reachable." Health monitoring is handled internally by the manager's health poll task, not by K8s. When a component's heartbeat deadline expires, the health monitor increments a stall counter. After `stall_threshold` consecutive stalled checks, the manager triggers global shutdown via the same `ComponentEvent::Failure` path as `signal_failure()`. This ensures the app always gets coordinated graceful shutdown instead of K8s surprise-killing the pod. (see tests `stall_triggers_shutdown`, `stall_threshold_exceeded_triggers_shutdown`, `stall_threshold_allows_recovery`)

Components in **Starting** state (never called `report_healthy()`) are skipped by the health monitor — they won't trigger stall detection until they've reported healthy at least once. (see test `starting_component_does_not_trigger_stall`)

### Axum route setup

```rust
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
```

## Using the handle

### With `process_scope()` (struct-held handle)

Use when your component is a struct that owns a `Handle` and has a blocking/looping `process()` method. Call `process_scope()` at the top of `process()` — when the guard is dropped (process returns), the manager is notified once. (see tests `component_a_clean_shutdown`, `component_b_clean_shutdown_with_do_work`)

The handle can be freely passed by reference or clone into child methods. Child methods can call `report_healthy()`, `report_unhealthy()`, `signal_failure()`, or return errors that cause `process()` to return (which drops the guard). None of this interferes with the guard. (see test `component_b_do_work_signals_failure` for error propagation from a child method)

```rust
struct MyConsumer {
    handle: lifecycle::Handle,
}

impl MyConsumer {
    async fn process(&self) {
        let _guard = self.handle.process_scope();
        loop {
            tokio::select! {
                _ = self.handle.shutdown_recv() => return,
                result = self.do_work() => {
                    match result {
                        Ok(()) => self.handle.report_healthy(),
                        Err(reason) => {
                            self.handle.signal_failure(reason);
                            return; // guard dropped → manager notified
                        }
                    }
                }
            }
        }
    }

    // Single select! — checks for cancellation alongside real work.
    // Returning does NOT trigger the guard; only process() returning does.
    async fn do_work(&self) -> Result<(), String> {
        tokio::select! {
            _ = self.handle.shutdown_recv() => Ok(()),
            result = self.fetch_and_process() => result,
        }
    }

    async fn fetch_and_process(&self) -> Result<(), String> { /* ... */ Ok(()) }
}
```

After `process()` returns, the struct can be dropped later without sending a duplicate event — the guard already signalled once. (see test `process_scope_prevents_double_signal_from_struct`)

### Without `process_scope()` (handle moved into task)

Use when you `tokio::spawn` and move the handle into the async block. The task IS the scope — when it returns, the last handle clone is dropped, and the drop guard notifies the manager. (see test `direct_handle_drop_during_shutdown_is_completion`)

```rust
async fn consumer_loop(handle: lifecycle::Handle) {
    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => return, // drop during shutdown = completion
            msg = recv_message() => {
                if let Err(e) = process(msg).await {
                    handle.signal_failure(e.to_string());
                    return; // signal_failure triggers shutdown; drop is fine
                }
                handle.report_healthy();
            }
        }
    }
}
```

After `signal_failure()`, just return — the manager records the failure immediately and the subsequent handle drop is harmlessly ignored. For normal shutdown or `request_shutdown()`, just return too — drop during shutdown is treated as completion. For one-shot/finite work that completes during normal operation, call `work_completed()` to prevent the drop from signaling "died". (see test `direct_work_completed_prevents_died_on_drop`)

### Handle API summary

| Method | Use when |
|--------|----------|
| `shutdown_recv()` | In `tokio::select!` to react to shutdown. |
| `is_shutting_down()` | Sync check (e.g. in a hot loop) to bail out. |
| `signal_failure(reason)` | Fatal error; triggers global shutdown. Just return after calling it. |
| `request_shutdown()` | Request clean shutdown (non-fatal). Then return (drop is enough). |
| `work_completed()` | One-shot/finite work that completes during normal operation (prevents the handle drop from signaling "died"). Not needed for long-running components — drop during shutdown is treated as completion. |
| `process_scope()` | Returns a `ProcessScopeGuard`. Ties lifecycle signaling to a method scope instead of handle drop. Use when your struct owns the handle. |
| `report_healthy()` | Liveness heartbeat. Must be called more often than `liveness_deadline`. Missed deadlines increment a stall counter; after `stall_threshold` consecutive stalled checks, global shutdown is triggered. |
| `report_unhealthy()` | Mark this component unhealthy. Treated the same as a stalled heartbeat by the health monitor. For immediate shutdown, use `signal_failure()` instead. |
| `report_healthy_blocking()` | Same as `report_healthy()`; safe from sync/blocking contexts (e.g. rdkafka callbacks). |

### Common pitfalls

1. **Drop during normal operation** — If the last handle (or process scope guard) is dropped while shutdown is **not** in progress, the manager treats it as "component died" and triggers shutdown. This catches panics and early returns. Dropping after shutdown begins is treated as normal completion. (see test `panic_in_task_with_process_scope_signals_died`)
2. **Register order** — Register all components before calling `monitor()` or `monitor_background()`. The manager is consumed by those calls.
3. **Health monitoring** — Activated by `with_liveness_deadline` on any component. You must call `report_healthy()` more frequently than `liveness_deadline`, or the health monitor triggers global shutdown after `stall_threshold` consecutive stalled checks. Components that haven't called `report_healthy()` yet (Starting state) are skipped. Use `with_health_poll_interval` on the manager to tune poll frequency (default 5s).
4. **Struct-held handles** — If your struct owns the handle and `process()` is the run method, use `process_scope()`. Otherwise the manager is only notified when the struct is dropped, not when `process()` returns.

## Metrics

The crate emits metrics via the `metrics` facade (no recorder installed by this crate; the parent app does that). All metrics are segmented by **`service_name`**: set `ManagerOptions::name` to your app's service name (e.g. K8s service name or logical app name) so dashboards and alerts can filter by service.

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
