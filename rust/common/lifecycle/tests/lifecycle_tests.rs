use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use lifecycle::{ComponentOptions, LifecycleError, Manager};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Default test manager: short global shutdown timeout (5s) so tests don't
/// hang. Per-test tokio::time::timeout guards are a second safety net.
fn test_manager() -> Manager {
    Manager::builder("test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_secs(5))
        .build()
}

/// Manager with fast health polling for stall detection tests.
fn fast_poll_manager(poll_ms: u64) -> Manager {
    Manager::builder("test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_secs(5))
        .with_health_poll_interval(Duration::from_millis(poll_ms))
        .build()
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
    comp.fail_flag.store(true, Ordering::SeqCst);
    tokio::spawn(async move { comp.process().await });

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
/// successful do_work(). Active heartbeating prevents the health monitor from
/// triggering a stall-based shutdown.
#[tokio::test]
async fn component_b_reports_healthy_from_process() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "b",
        ComponentOptions::new().with_liveness_deadline(Duration::from_millis(200)),
    );

    let comp = ComponentB::new(handle.clone());
    let guard = manager.monitor_background();
    tokio::spawn(async move { comp.process().await });

    // Let several poll cycles pass — no stall because do_work heartbeats
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(!handle.is_shutting_down());

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
    ha.request_shutdown();

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
/// K8s effect: readiness flips to 503.
#[tokio::test]
async fn direct_signal_failure_then_drop() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.signal_failure("something broke");
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
// Section 3: Health monitoring and readiness
//
// Health monitoring is internal to the manager: the health poll task checks
// component heartbeats and triggers shutdown when stall_threshold is reached.
// Liveness endpoint always returns 200 (process is reachable). Readiness
// flips to 503 on shutdown so K8s stops routing traffic.
// ---------------------------------------------------------------------------

/// Component that stops heartbeating is detected as stalled by the health
/// monitor. With stall_threshold=1 (default), one stalled check triggers
/// global shutdown with ComponentFailure.
#[tokio::test]
async fn stall_triggers_shutdown() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_liveness_deadline(Duration::from_millis(100)),
    );
    let guard = manager.monitor_background();

    // Report healthy once so we move past Starting state
    handle.report_healthy();
    // Wait for the deadline to expire + poll to fire
    tokio::time::sleep(Duration::from_millis(250)).await;

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, reason })
            if tag == "worker" && reason.contains("stalled")
    ));
}

/// Components in Starting state (never called report_healthy) do not trigger
/// stall detection — the health monitor skips them.
#[tokio::test]
async fn starting_component_does_not_trigger_stall() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_liveness_deadline(Duration::from_millis(100)),
    );
    let guard = manager.monitor_background();

    // Never call report_healthy — component stays in Starting state
    // Wait for several poll cycles
    tokio::time::sleep(Duration::from_millis(300)).await;
    assert!(!handle.is_shutting_down());

    handle.request_shutdown();
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// stall_threshold > 1: component stalls briefly then recovers by calling
/// report_healthy before threshold is reached — no shutdown triggered.
#[tokio::test]
async fn stall_threshold_allows_recovery() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "worker",
        ComponentOptions::new()
            .with_liveness_deadline(Duration::from_millis(120))
            .with_stall_threshold(3),
    );
    let guard = manager.monitor_background();

    // Report healthy, then let it stall for 1-2 checks (deadline 120ms,
    // poll 50ms → first stall at ~170ms, second at ~220ms, well under threshold 3)
    handle.report_healthy();
    tokio::time::sleep(Duration::from_millis(200)).await;
    // Recover before threshold (3) is reached
    handle.report_healthy();
    tokio::time::sleep(Duration::from_millis(50)).await;

    assert!(!handle.is_shutting_down());

    handle.request_shutdown();
    drop(handle);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

/// stall_threshold > 1: component stalls for enough consecutive checks to
/// reach the threshold — shutdown is triggered.
#[tokio::test]
async fn stall_threshold_exceeded_triggers_shutdown() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "worker",
        ComponentOptions::new()
            .with_liveness_deadline(Duration::from_millis(80))
            .with_stall_threshold(3),
    );
    let guard = manager.monitor_background();

    handle.report_healthy();
    // Wait for deadline to expire + 3 stalled polls (3 * 50ms + margin)
    tokio::time::sleep(Duration::from_millis(400)).await;

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, .. }) if tag == "worker"
    ));
}

/// report_unhealthy() sets the component to an unhealthy state that the health
/// monitor treats the same as a stalled heartbeat. With stall_threshold=1, the
/// next poll triggers shutdown.
#[tokio::test]
async fn report_unhealthy_triggers_stall() {
    let mut manager = fast_poll_manager(50);
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_liveness_deadline(Duration::from_millis(500)),
    );
    let guard = manager.monitor_background();

    handle.report_healthy();
    tokio::time::sleep(Duration::from_millis(20)).await;
    handle.report_unhealthy();
    // Wait for health poll to detect the unhealthy state
    tokio::time::sleep(Duration::from_millis(150)).await;

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, reason })
            if tag == "worker" && reason.contains("unhealthy")
    ));
}

/// Liveness endpoint always returns 200 regardless of component health.
#[tokio::test]
async fn liveness_always_200() {
    let mut manager = test_manager();
    let _handle = manager.register("worker", liveness_opts());
    let liveness = manager.liveness_handler();

    let resp = axum::response::IntoResponse::into_response(liveness.check());
    assert_eq!(resp.status(), axum::http::StatusCode::OK);
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

/// Task panics while holding a process_scope guard → guard drop fires during
/// unwind, manager receives Died, triggers global shutdown. Validates that the
/// drop guard actually catches panics (not just manual drops).
#[tokio::test]
async fn panic_in_task_with_process_scope_signals_died() {
    let mut manager = test_manager();
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        let _scope = handle.process_scope();
        panic!("boom");
    });

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

// ---------------------------------------------------------------------------
// Section 5: Global shutdown timeout
//
// Global shutdown timeout (default 60s) is always active. It caps the total
// shutdown duration — if components haven't finished in time the monitor
// returns ShutdownTimeout. This prevents indefinite hangs if a component
// doesn't check for cancellation properly. The timeout is configurable via
// Manager::builder("name").with_global_shutdown_timeout(duration).
// ---------------------------------------------------------------------------

/// Component that hangs during shutdown: the global timeout fires and the
/// monitor returns ShutdownTimeout listing the stuck component.
#[tokio::test]
async fn global_timeout_fires_when_component_hangs() {
    let mut manager = Manager::builder("test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_millis(100))
        .build();

    let handle = manager.register("slow", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(10)).await;
        handle.request_shutdown();
        std::future::pending::<()>().await;
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ShutdownTimeout { remaining, .. })
            if remaining.contains(&"slow".to_string())
    ));
}

/// Component that finishes before the global timeout produces a clean result.
#[tokio::test]
async fn global_timeout_does_not_fire_when_components_finish() {
    let mut manager = Manager::builder("test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_secs(5))
        .build();

    let handle = manager.register("fast", ComponentOptions::new());
    let guard = manager.monitor_background();

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.request_shutdown();
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}

// ---------------------------------------------------------------------------
// Section 6: Edge cases during shutdown
//
// These test interactions that happen while shutdown is already in progress:
// second failures, mixed per-component timeout outcomes, etc.
// ---------------------------------------------------------------------------

/// A second component calling signal_failure() after shutdown is already in
/// progress does not cause problems. The drain loop handles the late Failure
/// by marking the component Died (so it resolves immediately), but preserves
/// the original trigger's error via first_failure.
#[tokio::test]
async fn signal_failure_during_shutdown_marks_died() {
    let mut manager = test_manager();
    let h1 = manager.register("first", ComponentOptions::new());
    let h2 = manager.register("second", ComponentOptions::new());
    let guard = manager.monitor_background();

    let h2_clone = h2.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        h1.signal_failure("primary failure");
        // h1 dropped during shutdown → WorkCompleted (ignored since already Died)
    });

    tokio::spawn(async move {
        // Wait for shutdown to be in progress, then fire a second failure
        h2_clone.shutdown_recv().await;
        h2_clone.signal_failure("secondary failure");
    });

    // Drop h2 so the manager can finish
    drop(h2);

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, reason })
            if tag == "first" && reason == "primary failure"
    ));
}

/// Failure event during the shutdown drain loop marks the component Died and
/// resolves it immediately — the manager finishes without waiting for the 5s
/// global timeout. Both handles are held alive (via pending futures) so the
/// only way "late_fail" can resolve is through the Failure arm in the drain.
/// Exercises the same ComponentEvent::Failure path that a health monitor late
/// poll would take.
#[tokio::test]
async fn failure_during_drain_resolves_component_without_global_timeout() {
    let mut manager = Manager::builder("test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_secs(5))
        .build();

    let trigger = manager.register("trigger", ComponentOptions::new());
    let late_fail = manager.register("late_fail", ComponentOptions::new());
    let guard = manager.monitor_background();

    let late_fail_clone = late_fail.clone();
    tokio::spawn(async move {
        late_fail_clone.shutdown_recv().await;
        tokio::time::sleep(Duration::from_millis(20)).await;
        late_fail_clone.signal_failure("late failure during drain");
        std::future::pending::<()>().await;
    });
    drop(late_fail);

    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        trigger.signal_failure("primary trigger");
        std::future::pending::<()>().await;
    });

    let result = tokio::time::timeout(Duration::from_millis(500), guard.wait())
        .await
        .expect(
            "manager should resolve promptly via Failure in drain, not wait for global timeout",
        );

    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { tag, .. }) if tag == "trigger"
    ));
}

/// Two components with different graceful_shutdown budgets. One completes
/// within its budget, the other hangs past it. The manager marks the slow
/// one as TimedOut but still returns Ok (per-component timeouts don't fail
/// the monitor — only global timeout returns an error).
#[tokio::test]
async fn mixed_component_timeout_outcomes() {
    let mut manager = test_manager();
    let fast = manager.register(
        "fast",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_millis(200)),
    );
    let slow = manager.register(
        "slow",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_millis(50)),
    );
    let guard = manager.monitor_background();

    let fast_clone = fast.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(10)).await;
        fast_clone.request_shutdown();
        // Complete quickly
        fast_clone.shutdown_recv().await;
    });
    drop(fast);

    tokio::spawn(async move {
        // Hold past the 50ms graceful_shutdown budget
        slow.shutdown_recv().await;
        tokio::time::sleep(Duration::from_millis(100)).await;
    });

    let result = tokio::time::timeout(Duration::from_secs(10), guard.wait())
        .await
        .expect("timed out");
    assert!(result.is_ok());
}
