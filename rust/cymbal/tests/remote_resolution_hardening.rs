//! Failure-mode hardening tests for the remote resolution client.
//!
//! These tests exercise the final bidi `ResolveItem` / `ResolveOutcome`
//! protocol: transport failures, stream breaks, per-item terminal errors,
//! caller cancellation, and endpoint lifecycle cleanup.

mod common;

use std::io;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common::{
    build_event, make_config, make_ctx, process_one, remote_stage, spawn_stub_server, unbound_addr,
    wait_until_routable, ServerBehavior,
};
use cymbal::stages::resolution::remote::dns::DnsResolver;
use cymbal::stages::resolution::remote::resolver::RemoteResolutionContext;
use cymbal_proto::cymbal::resolution::v1::ErrorKind;
use tokio::sync::Mutex as TokioMutex;

#[tokio::test]
async fn connection_refused_endpoint_is_classified_as_retryable() {
    let bad = unbound_addr();
    let (good, good_items) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[bad, good], 4, Duration::from_secs(2)).await;
    let evt = build_event(1);

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("connection refused must not surface as terminal");
    assert_eq!(resolved.exception_list.len(), 1);
    assert_eq!(good_items.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn stream_interruption_reroutes_in_flight_items() {
    for _ in 0..20 {
        let (interrupted, interrupted_items) =
            spawn_stub_server(ServerBehavior::InterruptAfterFirst).await;
        let (good, good_items) = spawn_stub_server(ServerBehavior::Happy).await;
        let ctx = make_ctx(&[interrupted, good], 4, Duration::from_secs(2)).await;
        let selected = ctx
            .pool
            .select_for_key("team:7", &[])
            .await
            .expect("pool warmed")
            .addr;
        if selected != interrupted {
            continue;
        }

        let resolved = process_one(remote_stage(ctx), build_event(2))
            .await
            .expect("interrupted stream must reroute remaining items");
        assert_eq!(resolved.exception_list.len(), 2);
        assert_eq!(interrupted_items.lock().unwrap().len(), 1);
        assert_eq!(good_items.lock().unwrap().len(), 1);
        return;
    }
    panic!("failed to build fixture where rendezvous routing selected interrupted endpoint");
}

#[tokio::test]
async fn server_per_item_terminal_error_fails_batch_under_all_or_nothing_policy() {
    let (lossy, _) = spawn_stub_server(ServerBehavior::ErrorAfterFirst {
        kind: ErrorKind::InvalidPayload,
    })
    .await;
    let ctx = make_ctx(&[lossy], 1, Duration::from_secs(2)).await;
    let evt = build_event(3);

    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("server per-item Error must fail the batch");
    let msg = format!("{err}");
    assert!(
        msg.contains("items_failed") || msg.contains("failed terminally"),
        "expected per-item-error failure surface, got: {msg}"
    );
}

#[tokio::test]
async fn caller_drops_future_before_deadline_releases_pool_slot() {
    let (addr, _items) = spawn_stub_server(ServerBehavior::HappyDelayed {
        delay: Duration::from_millis(500),
    })
    .await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;
    let pool = Arc::clone(&ctx.pool);
    let evt = build_event(1);

    let result = tokio::time::timeout(
        Duration::from_millis(100),
        process_one(remote_stage(ctx.clone()), evt),
    )
    .await;
    assert!(
        result.is_err(),
        "remote resolution should still be in-flight when the caller times out"
    );

    tokio::time::sleep(Duration::from_millis(50)).await;
    let _handle = pool.select(&[]).await.expect("pool should still be usable");
}

#[tokio::test]
async fn accounting_preserves_order_and_team_id_on_resolved_payloads() {
    let (addr, _items) = spawn_stub_server(ServerBehavior::Happy).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(2)).await;
    let evt = build_event(5);

    let original_types: Vec<String> = evt
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();
    let original_team_id = evt.team_id;

    let resolved = process_one(remote_stage(ctx), evt)
        .await
        .expect("happy path");

    let resolved_types: Vec<String> = resolved
        .exception_list
        .iter()
        .map(|e| e.exception_type.clone())
        .collect();
    assert_eq!(resolved_types, original_types, "slots must be preserved");
    assert_eq!(resolved.team_id, original_team_id);
}

#[tokio::test]
async fn endpoint_refresh_closes_draining_mux_and_reroutes_in_flight_item() {
    let (old_addr, old_items) = spawn_stub_server(ServerBehavior::HappyDelayed {
        delay: Duration::from_millis(500),
    })
    .await;
    let (new_addr, new_items) = spawn_stub_server(ServerBehavior::Happy).await;
    let resolver = Arc::new(QueuedResolver::new(vec![vec![old_addr], vec![new_addr]]));
    let config = make_config(50, Duration::from_secs(3));
    let pool = cymbal::stages::resolution::remote::EndpointPool::new(config.clone(), resolver)
        .await
        .expect("build pool");
    wait_until_routable(&pool).await;
    let ctx = RemoteResolutionContext::new(Arc::clone(&pool), config);

    let task = tokio::spawn(process_one(remote_stage(ctx), build_event(1)));
    tokio::time::sleep(Duration::from_millis(75)).await;
    pool.refresh().await.expect("refresh to new endpoint");
    wait_until_routable(&pool).await;

    let resolved = task
        .await
        .expect("join remote resolution")
        .expect("drained mux should reroute item");
    assert_eq!(resolved.exception_list.len(), 1);
    assert_eq!(old_items.lock().unwrap().len(), 1);
    assert_eq!(new_items.lock().unwrap().len(), 1);
    assert_eq!(pool.endpoints().await, vec![new_addr]);
}

#[tokio::test]
async fn pool_with_only_draining_endpoints_fails_fast_without_local_fallback() {
    let ctx = make_ctx(&[], 0, Duration::from_millis(50)).await;
    let evt = build_event(1);

    let start = std::time::Instant::now();
    let err = process_one(remote_stage(ctx), evt)
        .await
        .expect_err("empty pool must fail fast");
    let elapsed = start.elapsed();

    assert!(
        elapsed < Duration::from_millis(200),
        "fast-fail expected, took {elapsed:?}"
    );
    assert!(
        format!("{err}").contains("pool unavailable"),
        "expected pool-unavailable error: {err}"
    );
}

struct QueuedResolver {
    results: TokioMutex<Vec<Vec<SocketAddr>>>,
}

impl QueuedResolver {
    fn new(results: Vec<Vec<SocketAddr>>) -> Self {
        Self {
            results: TokioMutex::new(results),
        }
    }
}

#[async_trait]
impl DnsResolver for QueuedResolver {
    async fn resolve(&self, _host: &str, _port: u16) -> io::Result<Vec<SocketAddr>> {
        let mut results = self.results.lock().await;
        if results.is_empty() {
            return Err(io::Error::other("no more resolver fixtures"));
        }
        Ok(results.remove(0))
    }
}
