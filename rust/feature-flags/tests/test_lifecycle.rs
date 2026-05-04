use anyhow::Result;
use reqwest::StatusCode;

use crate::common::*;
use feature_flags::config::DEFAULT_TEST_CONFIG;

pub mod common;

async fn get_status(addr: &std::net::SocketAddr, path: &str) -> Result<StatusCode> {
    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}{path}")).send().await?;
    Ok(resp.status())
}

/// Readiness returns 200 while running, then 503 once the shutdown token is cancelled.
#[tokio::test]
async fn readiness_flips_to_503_after_shutdown() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;
    server.wait_until_ready().await;

    assert_eq!(
        get_status(&server.addr, "/_readiness").await?,
        StatusCode::OK
    );

    server.shutdown_now();

    // ReadinessHandler reads the shutdown token directly, so the flip is
    // synchronous from the handler's point of view. Poll up to ~500ms to absorb
    // scheduler jitter on loaded CI runners between shutdown_now() and the next
    // request landing on the server task. A connection error also counts as
    // success — axum's graceful-shutdown may have already closed the accept
    // loop. If this polls 25 times and never sees 503 or a connection drop,
    // that's a genuine regression, not a flake.
    let mut last_status: Option<StatusCode> = None;
    for _ in 0..25 {
        match get_status(&server.addr, "/_readiness").await {
            Err(_) => return Ok(()),
            Ok(StatusCode::SERVICE_UNAVAILABLE) => return Ok(()),
            Ok(status) => {
                last_status = Some(status);
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
        }
    }
    panic!(
        "/_readiness did not flip to 503 after shutdown within 500ms (last status: {last_status:?})"
    );
}

/// Liveness must return 200 while running and keep returning 200 across shutdown —
/// the lifecycle manager owns stall detection, not k8s, so a failed liveness
/// probe would cause the pod to be killed out from under a graceful drain.
#[tokio::test]
async fn liveness_stays_200_across_shutdown() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let server = ServerHandle::for_config(config).await;
    server.wait_until_ready().await;

    assert_eq!(
        get_status(&server.addr, "/_liveness").await?,
        StatusCode::OK
    );

    server.shutdown_now();

    // 200 or connection-error are both fine; a non-200 response would mean
    // somebody wired shutdown-gating into the liveness route.
    for _ in 0..5 {
        match get_status(&server.addr, "/_liveness").await {
            Err(_) => return Ok(()),
            Ok(StatusCode::OK) => {
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
            Ok(other) => panic!("/_liveness must stay 200 across shutdown, got {other}"),
        }
    }
    Ok(())
}

/// Dropping the ServerHandle cancels the shutdown token and the server exits.
/// Verifies the Drop-based teardown the test harness relies on.
#[tokio::test]
async fn drop_triggers_shutdown() -> Result<()> {
    let config = DEFAULT_TEST_CONFIG.clone();
    let addr = {
        let server = ServerHandle::for_config(config).await;
        server.wait_until_ready().await;
        server.addr
    };

    // After drop, the server should stop accepting new connections within a short window.
    // Worst case per iteration is ~250ms (200ms reqwest timeout + 50ms sleep) × 40 = ~10s,
    // which is the real ceiling the panic message reflects.
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(200))
        .build()?;
    let mut last_status: Option<StatusCode> = None;
    for _ in 0..40 {
        let resp = client.get(format!("http://{addr}/_readiness")).send().await;
        match resp {
            Err(_) => return Ok(()), // connection refused or timed out — server gone
            Ok(r) if r.status() == StatusCode::SERVICE_UNAVAILABLE => return Ok(()),
            Ok(r) => {
                last_status = Some(r.status());
                tokio::time::sleep(std::time::Duration::from_millis(50)).await;
            }
        }
    }
    panic!("server still accepting /_readiness requests ~10s after drop (last status: {last_status:?})");
}
