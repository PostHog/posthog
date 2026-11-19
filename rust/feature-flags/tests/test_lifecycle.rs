use std::time::Duration;

use anyhow::{bail, Context, Result};
use reqwest::StatusCode;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::TcpStream;

use crate::common::*;
use feature_flags::config::DEFAULT_TEST_CONFIG;

pub mod common;

async fn get_status(addr: &std::net::SocketAddr, path: &str) -> Result<StatusCode> {
    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}{path}")).send().await?;
    Ok(resp.status())
}

/// Sends `GET path` on an open HTTP/1.1 connection and returns the response head as
/// lowercase lines. Reads the body too, so the next request starts on a clean boundary.
async fn get_on(conn: &mut BufReader<TcpStream>, path: &str) -> Result<Vec<String>> {
    conn.get_mut()
        .write_all(format!("GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n").as_bytes())
        .await?;
    let mut head = Vec::new();
    loop {
        let mut line = String::new();
        if conn.read_line(&mut line).await? == 0 {
            bail!("connection closed before the response head ended");
        }
        let line = line.trim_end().to_ascii_lowercase();
        if line.is_empty() {
            break;
        }
        head.push(line);
    }
    let content_length = head
        .iter()
        .find_map(|line| line.strip_prefix("content-length:"))
        .map_or(Ok(0), |len| len.trim().parse())?;
    conn.read_exact(&mut vec![0; content_length]).await?;
    Ok(head)
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

/// While the pod drains, the server still answers on a keep-alive connection opened
/// before the drain, then closes it, so the client reconnects to a pod that stays.
#[tokio::test]
async fn drain_closes_keep_alive_connections_after_the_response() -> Result<()> {
    let prestop_dir = tempfile::tempdir()?;
    let prestop_path = prestop_dir.path().join("shutdown");
    let server =
        ServerHandle::for_config_with_prestop_drain(DEFAULT_TEST_CONFIG.clone(), &prestop_path)
            .await;
    server.wait_until_ready().await;

    let mut conn = BufReader::new(TcpStream::connect(server.addr).await?);
    for _ in 0..2 {
        let head = get_on(&mut conn, "/flags").await?;
        assert!(
            !head.iter().any(|line| line == "connection: close"),
            "a serving pod must keep the connection open, got {head:?}"
        );
    }

    std::fs::write(&prestop_path, "")?;
    // The listener stays open while draining, so readiness answers 503 rather than
    // refusing the connection.
    tokio::time::timeout(Duration::from_secs(5), async {
        while get_status(&server.addr, "/_readiness").await? != StatusCode::SERVICE_UNAVAILABLE {
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        anyhow::Ok(())
    })
    .await
    .context("readiness did not fail after the pre-stop file appeared")??;

    let head = get_on(&mut conn, "/flags").await?;
    assert!(
        head.iter().any(|line| line == "connection: close"),
        "a draining pod must ask the client to close the connection, got {head:?}"
    );
    let closed = tokio::time::timeout(Duration::from_secs(5), conn.read(&mut [0; 1]))
        .await
        .context("the server kept the connection open after the response")??;
    assert_eq!(
        closed, 0,
        "the server must close the connection after the response"
    );
    Ok(())
}
