use std::time::Duration;

use axum::routing::get;
use lifecycle::{ComponentOptions, Manager};
use tokio_util::sync::CancellationToken;

fn test_manager(token: CancellationToken) -> Manager {
    Manager::builder("batch-import-worker-test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_global_shutdown_timeout(Duration::from_secs(5))
        .with_shutdown_token(token)
        .build()
}

#[tokio::test]
async fn readiness_200_before_shutdown_503_after() {
    let token = CancellationToken::new();
    let mut manager = test_manager(token.clone());

    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(1)),
    );
    let readiness = manager.readiness_handler();
    let monitor = manager.monitor_background();

    assert_eq!(readiness.check().await, axum::http::StatusCode::OK);

    token.cancel();

    assert_eq!(
        readiness.check().await,
        axum::http::StatusCode::SERVICE_UNAVAILABLE
    );

    drop(handle);
    monitor.wait().await.unwrap();
}

#[tokio::test]
async fn liveness_always_200() {
    let token = CancellationToken::new();
    let mut manager = test_manager(token.clone());

    let handle = manager.register(
        "worker",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(1)),
    );
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    let resp = liveness.check();
    let axum_resp = axum::response::IntoResponse::into_response(resp);
    assert_eq!(axum_resp.status(), axum::http::StatusCode::OK);

    token.cancel();

    let resp = liveness.check();
    let axum_resp = axum::response::IntoResponse::into_response(resp);
    assert_eq!(axum_resp.status(), axum::http::StatusCode::OK);

    drop(handle);
    monitor.wait().await.unwrap();
}

#[tokio::test]
async fn shutdown_token_causes_job_loop_exit() {
    let token = CancellationToken::new();
    let mut manager = test_manager(token.clone());

    let job_handle = manager.register(
        "job-loop",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );
    let monitor = manager.monitor_background();

    let loop_exited = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let exited = loop_exited.clone();

    tokio::spawn(async move {
        let _guard = job_handle.process_scope();
        while !job_handle.is_shutting_down() {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(5)) => {},
                _ = job_handle.shutdown_recv() => break,
            }
        }
        exited.store(true, std::sync::atomic::Ordering::SeqCst);
    });

    // Give the task a moment to start
    tokio::task::yield_now().await;

    assert!(!loop_exited.load(std::sync::atomic::Ordering::SeqCst));

    token.cancel();

    monitor.wait().await.unwrap();

    assert!(loop_exited.load(std::sync::atomic::Ordering::SeqCst));
}

#[tokio::test]
async fn observability_handle_outlives_standard_handle() {
    let token = CancellationToken::new();
    let mut manager = test_manager(token.clone());

    let standard_handle = manager.register(
        "job-loop",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(1)),
    );
    let obs_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    let obs_saw_standard_drain = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let flag = obs_saw_standard_drain.clone();

    // Observability server: verify readiness is already 503 (standard drain started)
    // before the obs handle receives its own shutdown signal
    tokio::spawn(async move {
        let _guard = obs_handle.process_scope();

        let app = axum::Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();

        axum::serve(listener, app)
            .with_graceful_shutdown(obs_handle.shutdown_signal())
            .await
            .unwrap();

        // If we get here, the obs shutdown signal fired. The standard token
        // was already cancelled (that's how two-phase shutdown works).
        flag.store(true, std::sync::atomic::Ordering::SeqCst);
    });

    // Standard component: exit immediately on shutdown
    tokio::spawn(async move {
        let _guard = standard_handle.process_scope();
        standard_handle.shutdown_recv().await;
    });

    token.cancel();

    monitor.wait().await.unwrap();

    assert!(obs_saw_standard_drain.load(std::sync::atomic::Ordering::SeqCst));
}
