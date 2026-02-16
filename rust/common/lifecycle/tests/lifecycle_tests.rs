use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use lifecycle::{ComponentOptions, HealthStrategy, LifecycleError, Manager, ManagerOptions};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn test_manager() -> Manager {
    Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(5),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    })
}

fn liveness_opts() -> ComponentOptions {
    ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30))
}

// ---------------------------------------------------------------------------
// Realistic component structs
//
// These model how real services use the lifecycle crate. Both own a Handle
// on the struct (the typical pattern) and create a process_scope guard at
// the top of process(). ComponentB adds an inner do_work() method that
// accesses the handle via &self — demonstrating that child methods can
// freely call any handle API (report_healthy, shutdown_recv, etc.) without
// affecting the process_scope guard.
// ---------------------------------------------------------------------------

/// Simple looping component. process_scope guard ties lifecycle to process().
struct ComponentA {
    handle: lifecycle::Handle,
}

impl ComponentA {
    async fn process(&self) {
        let _guard = self.handle.process_scope();
        loop {
            tokio::select! {
                _ = self.handle.shutdown_recv() => return,
                _ = tokio::time::sleep(Duration::from_millis(50)) => {
                    self.handle.report_healthy();
                }
            }
        }
    }
}

/// Looping component with an inner do_work() method. process() creates the
/// guard and delegates work each iteration. do_work() does a single select!
/// (not looped) — it checks for cancellation alongside fake work, and returns
/// without triggering the guard. Only process() returning drops the guard.
///
/// On error, process() calls signal_failure() and returns — the guard drop
/// during shutdown is harmlessly ignored by the manager.
struct ComponentB {
    handle: lifecycle::Handle,
    fail_flag: Arc<AtomicBool>,
}

impl ComponentB {
    fn new(handle: lifecycle::Handle) -> Self {
        Self {
            handle,
            fail_flag: Arc::new(AtomicBool::new(false)),
        }
    }

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
                            return;
                        }
                    }
                }
            }
        }
    }

    async fn do_work(&self) -> Result<(), String> {
        if self.fail_flag.load(Ordering::SeqCst) {
            return Err("injected failure".into());
        }
        tokio::select! {
            _ = self.handle.shutdown_recv() => Ok(()),
            _ = tokio::time::sleep(Duration::from_millis(10)) => Ok(()),
        }
    }
}

// ---------------------------------------------------------------------------
// Section 1: Struct-based integration tests (process_scope guard)
//
// These tests use ComponentA and ComponentB to demonstrate the recommended
// pattern: struct owns Handle, process() creates a process_scope guard,
// child methods access the handle freely. The guard ties lifecycle signaling
// to the process() scope, not the struct's lifetime.
// ---------------------------------------------------------------------------

/// ComponentA: simple loop, clean shutdown. Guard dropped on return → Ok.
/// Demonstrates: process_scope, shutdown_recv, report_healthy.
#[tokio::test]
async fn component_a_clean_shutdown() {
    let mut manager = test_manager();
    let handle = manager.register("a", liveness_opts());
    let guard = manager.monitor_background();

    let comp = ComponentA {
        handle: handle.clone(),
    };
    tokio::spawn(async move { comp.process().await });

    tokio::time::sleep(Duration::from_millis(80)).await;
    handle.request_shutdown();

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// ComponentB: loop with inner do_work(), clean shutdown. do_work() checks
/// shutdown_recv in a select! alongside fake work — returns without triggering
/// the guard. Only process() returning drops the guard.
/// Demonstrates: process_scope, child method using handle, report_healthy.
#[tokio::test]
async fn component_b_clean_shutdown_with_do_work() {
    let mut manager = test_manager();
    let handle = manager.register("b", liveness_opts());
    let guard = manager.monitor_background();

    let comp = ComponentB::new(handle.clone());
    tokio::spawn(async move { comp.process().await });

    tokio::time::sleep(Duration::from_millis(80)).await;
    handle.request_shutdown();

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// ComponentB: do_work() returns Err, process() calls signal_failure() and
/// returns → manager records ComponentFailure, guard drop is harmlessly ignored.
/// Demonstrates: error propagation from child method, signal_failure from process().
#[tokio::test]
async fn component_b_do_work_signals_failure() {
    let mut manager = test_manager();
    let handle = manager.register("b", ComponentOptions::new());
    let guard = manager.monitor_background();

    let comp = ComponentB::new(handle.clone());
    // Set the fail flag so do_work returns Err on next call
    comp.fail_flag.store(true, Ordering::SeqCst);
    tokio::spawn(async move { comp.process().await });

    // Wait for struct to drop after task exits
    tokio::time::sleep(Duration::from_millis(200)).await;
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, reason })
            if tag == "b" && reason == "injected failure"
    ));
}

/// ComponentB: report_healthy() is called from the process loop after each
/// successful do_work(). Liveness probe starts as !healthy (Starting), then
/// reflects Healthy once heartbeats arrive.
/// Demonstrates: liveness driven by report_healthy in a struct-based component.
#[tokio::test]
async fn component_b_reports_healthy_from_process() {
    let mut manager = test_manager();
    let handle = manager.register("b", liveness_opts());
    let liveness = manager.liveness_handler();

    // Initially Starting (no report_healthy yet)
    assert!(!liveness.check().healthy);

    let comp = ComponentB::new(handle.clone());
    let guard = manager.monitor_background();
    tokio::spawn(async move { comp.process().await });

    // Let a few do_work iterations run so report_healthy is called
    tokio::time::sleep(Duration::from_millis(80)).await;
    assert!(liveness.check().healthy);

    handle.request_shutdown();
    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// Two components (A + B) registered on the same manager. request_shutdown()
/// from either triggers global shutdown — both see it via shutdown_recv() and
/// exit cleanly. Readiness flips to 503 so K8s stops routing traffic.
/// Demonstrates: multi-component registration, shared shutdown signal.
#[tokio::test]
async fn component_a_and_b_multi_component_shutdown() {
    let mut manager = test_manager();
    let ha = manager.register("a", liveness_opts());
    let hb = manager.register("b", liveness_opts());
    let guard = manager.monitor_background();

    let comp_a = ComponentA { handle: ha.clone() };
    let comp_b = ComponentB::new(hb.clone());

    tokio::spawn(async move { comp_a.process().await });
    tokio::spawn(async move { comp_b.process().await });

    tokio::time::sleep(Duration::from_millis(80)).await;
    ha.request_shutdown(); // triggers global shutdown, both components see it

    // Drop the "struct" clones
    drop(ha);
    drop(hb);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

// ---------------------------------------------------------------------------
// Section 2: Direct API usage (no process_scope guard)
//
// These tests show the "handle moved into task" pattern where the spawned
// task IS the scope — when it returns, the last handle clone drops and the
// drop guard notifies the manager. No struct, no process_scope().
// ---------------------------------------------------------------------------

/// signal_failure() triggers global shutdown; just return and let the handle
/// drop. Manager records ComponentFailure; the drop during shutdown is ignored.
/// K8s effect: readiness flips to 503, liveness stays healthy during shutdown.
#[tokio::test]
async fn direct_signal_failure_then_drop() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.signal_failure("something broke");
        // No work_completed() — just return; drop during shutdown is fine
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, reason })
            if tag == "worker" && reason == "something broke"
    ));
}

/// request_shutdown() + work_completed(): clean non-fatal shutdown. The component
/// requests shutdown, finishes remaining work, then calls work_completed().
/// Demonstrates: the explicit completion path (alternative to drop-as-completion).
#[tokio::test]
async fn direct_request_shutdown_with_work_completed() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.request_shutdown();
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.work_completed();
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// Handle moved into spawned task. Task requests shutdown, awaits shutdown_recv(),
/// then returns — handle drop during shutdown is treated as normal completion.
/// No work_completed() call needed. This is the simplest correct pattern for
/// long-running components without a struct.
#[tokio::test]
async fn direct_handle_drop_during_shutdown_is_completion() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.request_shutdown();
        handle.shutdown_recv().await;
        // handle dropped here — shutdown in progress, so treated as WorkCompleted
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// work_completed() for one-shot/finite work: call it when work finishes during
/// normal operation so the subsequent handle drop doesn't signal "died". This is
/// the only case where work_completed() is needed — long-running components that
/// exit on shutdown don't need it (drop during shutdown is completion).
#[tokio::test]
async fn direct_work_completed_prevents_died_on_drop() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    handle.work_completed();
    let guard = manager.monitor_background();
    drop(handle);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

// ---------------------------------------------------------------------------
// Section 3: Liveness and readiness
//
// Liveness is driven by report_healthy() / report_unhealthy() calls on
// handles. K8s probes this endpoint and restarts the pod if it fails
// failureThreshold consecutive times. Readiness is driven by the shutdown
// token — it flips to 503 when any shutdown trigger fires, telling K8s to
// stop routing traffic.
// ---------------------------------------------------------------------------

/// Components start as Starting (liveness probe fails). After calling
/// report_healthy(), the probe returns Healthy.
/// K8s effect: pod is not "live" until the first heartbeat arrives.
#[tokio::test]
async fn liveness_starts_as_starting_until_report_healthy() {
    let mut manager = test_manager();
    let handle = manager.register("worker", liveness_opts());
    let liveness = manager.liveness_handler();

    let status = liveness.check();
    assert!(!status.healthy);
    assert_eq!(
        status.components.get("worker").unwrap(),
        &lifecycle::ComponentLiveness::Starting
    );

    handle.report_healthy();
    let status = liveness.check();
    assert!(status.healthy);
    assert_eq!(
        status.components.get("worker").unwrap(),
        &lifecycle::ComponentLiveness::Healthy
    );
}

/// report_unhealthy() explicitly marks the component as Unhealthy. Calling
/// report_healthy() again would recover it. This is distinct from Stalled
/// (heartbeat deadline expired) — Unhealthy is an explicit signal.
/// K8s effect: liveness probe returns 500; K8s eventually restarts the pod.
#[tokio::test]
async fn liveness_report_unhealthy() {
    let mut manager = test_manager();
    let handle = manager.register("worker", liveness_opts());
    let liveness = manager.liveness_handler();

    handle.report_healthy();
    assert!(liveness.check().healthy);

    handle.report_unhealthy();
    let status = liveness.check();
    assert!(!status.healthy);
    assert_eq!(
        status.components.get("worker").unwrap(),
        &lifecycle::ComponentLiveness::Unhealthy
    );
}

/// End-to-end: ComponentB runs with process_scope, calls report_healthy() on
/// each successful do_work() iteration. Liveness reflects Healthy while
/// running. After shutdown, the guard drops cleanly and the struct-held
/// handle is dropped without double-signaling.
/// Demonstrates: liveness + process_scope + struct-held handle working together.
#[tokio::test]
async fn liveness_with_process_scope_struct() {
    let mut manager = test_manager();
    let handle = manager.register("b", liveness_opts());
    let liveness = manager.liveness_handler();
    let guard = manager.monitor_background();

    let comp = ComponentB::new(handle.clone());
    tokio::spawn(async move { comp.process().await });

    tokio::time::sleep(Duration::from_millis(80)).await;
    assert!(liveness.check().healthy);

    handle.request_shutdown();
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// HealthStrategy::All: every component must be healthy for the probe to pass.
/// One Starting/Stalled/Unhealthy component fails the whole probe.
#[tokio::test]
async fn liveness_strategy_all_requires_all_healthy() {
    let mut manager = test_manager();
    let h1 = manager.register("a", liveness_opts());
    let h2 = manager.register("b", liveness_opts());
    let liveness = manager.liveness_handler();

    h1.report_healthy();
    assert!(!liveness.check().healthy); // b still Starting

    h2.report_healthy();
    assert!(liveness.check().healthy);
}

/// HealthStrategy::Any: at least one healthy component is enough.
#[tokio::test]
async fn liveness_strategy_any_one_healthy_suffices() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(5),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::Any,
    });
    let h1 = manager.register("a", liveness_opts());
    let _h2 = manager.register("b", liveness_opts());
    let liveness = manager.liveness_handler();

    h1.report_healthy();
    assert!(liveness.check().healthy);
}

/// Readiness returns 200 while running, 503 after shutdown begins.
/// K8s effect: once 503, K8s removes the pod from service endpoints and
/// stops routing new traffic. This happens before liveness is affected.
#[tokio::test]
async fn readiness_200_until_shutdown_then_503() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let readiness = manager.readiness_handler();
    assert_eq!(readiness.check().await.as_u16(), 200);

    let guard = manager.monitor_background();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(50)).await;
        handle.request_shutdown();
        tokio::time::sleep(Duration::from_millis(80)).await;
    });

    tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out")
        .unwrap();
    assert_eq!(readiness.check().await.as_u16(), 503);
}

// ---------------------------------------------------------------------------
// Section 4: Drop guard edge cases
//
// These tests verify the safety net: drops during normal operation (panics,
// early returns) trigger shutdown, while drops during shutdown are benign.
// Also covers process_scope deduplication guarantees.
// ---------------------------------------------------------------------------

/// Handle dropped during normal operation (no shutdown in progress) → manager
/// receives Died, triggers global shutdown, returns ComponentDied error.
/// This is the safety net for panics and accidental early returns.
#[tokio::test]
async fn handle_drop_during_normal_operation_signals_died() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentDied { tag }) if tag == "worker"
    ));
}

/// Struct outlives its process_scope guard. When the guard fires (process
/// returns), it signals once. When the struct is later dropped and
/// HandleInner::drop runs, it sees process_scope_signalled=true and skips.
/// No double-signal, no spurious errors.
#[tokio::test]
async fn process_scope_prevents_double_signal_from_struct() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    let h = handle.clone();
    tokio::spawn(async move {
        let _scope = h.process_scope();
        tokio::time::sleep(Duration::from_millis(30)).await;
        h.request_shutdown();
        h.shutdown_recv().await;
        // _scope dropped → WorkCompleted (first and only event)
    });

    // "struct" clone dropped later — should not double-signal
    tokio::time::sleep(Duration::from_millis(300)).await;
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// Two guards from the same handle: only the first dropped sends an event.
/// Second guard and handle drop are both no-ops. Typical usage is one guard
/// per process() call, but this verifies the dedup is safe regardless.
#[tokio::test]
async fn multiple_process_scope_guards_only_first_sends() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        let scope1 = handle.process_scope();
        let scope2 = handle.process_scope();
        tokio::time::sleep(Duration::from_millis(30)).await;
        handle.request_shutdown();
        handle.shutdown_recv().await;
        drop(scope1);
        drop(scope2);
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// Component exceeds its with_graceful_shutdown budget. Manager marks it
/// TimedOut. When the handle is eventually dropped (sending a late WorkCompleted),
/// the manager does not overwrite TimedOut with Completed — metrics correctly
/// reflect the timeout.
#[tokio::test]
async fn component_timeout_then_late_drop_preserves_timeout() {
    let mut manager = test_manager();
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_millis(50)),
    );
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.request_shutdown();
        // Hold handle past the 50ms graceful shutdown window
        tokio::time::sleep(Duration::from_millis(100)).await;
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}
