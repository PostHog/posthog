use std::time::Duration;

use lifecycle::{ComponentOptions, HealthStrategy, LifecycleError, Manager, ManagerOptions};

#[tokio::test]
async fn readiness_returns_200_until_shutdown() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(5),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register("worker", ComponentOptions::new());
    let readiness = manager.readiness_handler();
    assert_eq!(readiness.check().await.as_u16(), 200);

    let guard = manager.monitor_background();
    let handle_for_shutdown = handle.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(50)).await;
        handle_for_shutdown.request_shutdown();
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle_for_shutdown.work_completed();
    });

    guard.wait().await.unwrap();
    assert_eq!(readiness.check().await.as_u16(), 503);
}

#[tokio::test]
async fn liveness_unhealthy_until_report_healthy() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(1),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30)),
    );
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

#[tokio::test]
async fn liveness_strategy_all_requires_all_healthy() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(1),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let h1 = manager.register(
        "a",
        ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30)),
    );
    let h2 = manager.register(
        "b",
        ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30)),
    );
    let liveness = manager.liveness_handler();
    h1.report_healthy();
    let status = liveness.check();
    assert!(!status.healthy);

    h2.report_healthy();
    let status = liveness.check();
    assert!(status.healthy);
}

#[tokio::test]
async fn liveness_strategy_any_one_healthy_suffices() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(1),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::Any,
    });
    let h1 = manager.register(
        "a",
        ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30)),
    );
    let _h2 = manager.register(
        "b",
        ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30)),
    );
    let liveness = manager.liveness_handler();
    h1.report_healthy();
    let status = liveness.check();
    assert!(status.healthy);
}

#[tokio::test]
async fn handle_drop_without_work_completed_signals_died() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(2),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();
    drop(handle);
    let result = guard.wait().await;
    assert!(matches!(
        result,
        Err(LifecycleError::ComponentDied { tag }) if tag == "worker"
    ));
}

#[tokio::test]
async fn work_completed_prevents_died_on_drop() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(2),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register("worker", ComponentOptions::new());
    handle.work_completed();
    let guard = manager.monitor_background();
    drop(handle);
    tokio::time::sleep(Duration::from_millis(100)).await;
    let result = guard.wait().await;
    assert!(result.is_ok());
}

#[tokio::test]
async fn request_shutdown_then_work_completed_clean_shutdown() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(5),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register("worker", ComponentOptions::new());
    let guard = manager.monitor_background();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(50)).await;
        handle.request_shutdown();
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.work_completed();
    });
    let result = guard.wait().await;
    assert!(result.is_ok());
}

#[tokio::test]
async fn component_timeout_during_graceful_shutdown() {
    let mut manager = Manager::new(ManagerOptions {
        name: "test".into(),
        global_shutdown_timeout: Duration::from_secs(5),
        trap_signals: false,
        enable_prestop_check: false,
        liveness_strategy: HealthStrategy::All,
    });
    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_millis(50)),
    );
    let guard = manager.monitor_background();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(20)).await;
        handle.request_shutdown();
    });
    let result = guard.wait().await;
    assert!(result.is_ok());
}
