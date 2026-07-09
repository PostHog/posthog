//! End-to-end coverage for the freshness/draining `Subscribe` RPC and
//! pool routing on server-reported health.
//!
//! These tests bring up a real cymbal-resolution server with a fake symbol
//! resolver, build an `EndpointPool` pointed at it, and verify that the
//! pool's per-endpoint subscription task actually fills the load snapshot
//! and biases routing accordingly. The unit-level pool/subscription tests
//! validate the in-process logic; this file exercises the gRPC wire as well.

mod common;

use std::net::SocketAddr;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::native::DebugImage;
use cymbal::modes::resolution::load_monitor::LoadMonitor;
use cymbal::modes::resolution::service::{CymbalResolutionService, ServiceConfig};
use cymbal::stages::resolution::remote::{EndpointPool, RemoteResolutionConfig};
use cymbal::symbolication::symbol::SymbolResolver;
use cymbal::symbolication::symbol_store::chunk_id::OrChunkId;
use cymbal::symbolication::symbol_store::proguard::ProguardRef;
use cymbal::types::operator::TeamId;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use tokio::sync::Semaphore;

#[derive(Default)]
struct EmptyResolver;

#[async_trait]
impl SymbolResolver for EmptyResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: TeamId,
        _frame: &RawFrame,
        _debug_images: &[DebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        Ok(Vec::new())
    }

    async fn resolve_java_class(
        &self,
        _team_id: TeamId,
        _symbolset_ref: OrChunkId<ProguardRef>,
        _class: String,
    ) -> Result<String, ResolveError> {
        unreachable!("not exercised by subscribe tests")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        unreachable!("not exercised by subscribe tests")
    }
}

/// Spawn a real cymbal-resolution server with the given item-admission
/// limiter and load-event capacity suggestion.
async fn spawn_real_server(item_limiter: Arc<Semaphore>, max_in_flight: u32) -> SocketAddr {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);

    let resolver: Arc<dyn SymbolResolver> = Arc::new(EmptyResolver);
    // Fast tick so the test doesn't pay a second per iteration; min above zero
    // so the server clamps any hint up safely.
    let service_config = ServiceConfig {
        default_tick_interval: Duration::from_millis(25),
        min_tick_interval: Duration::from_millis(5),
        max_tick_interval: Duration::from_secs(1),
    };
    // Symbol limiter is irrelevant for these tests because EmptyResolver
    // never acquires; size it generously so it never gates anything.
    let symbol_limiter = Arc::new(Semaphore::new(64));
    // Degraded signal disabled (threshold 0); these tests don't exercise it.
    let load_monitor = LoadMonitor::new(max_in_flight);
    load_monitor
        .set_in_flight(max_in_flight.saturating_sub(item_limiter.available_permits() as u32));
    let service = CymbalResolutionService::new(
        resolver,
        symbol_limiter,
        load_monitor,
        format!("real-{addr}"),
        service_config,
        Arc::new(AtomicBool::new(false)),
    );

    tokio::spawn(async move {
        let _outcome = tonic::transport::Server::builder()
            .add_service(CymbalResolutionServer::new(service))
            .serve(addr)
            .await;
    });

    for _ in 0..40 {
        if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(50)).is_ok() {
            return addr;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    panic!("real cymbal-resolution server failed to come up at {addr}");
}

fn pool_config(host: &str, tick_hint: Duration) -> RemoteResolutionConfig {
    RemoteResolutionConfig {
        host: host.to_string(),
        port: 0,
        internal_api_secret: "test-secret".to_string(),
        dns_refresh: Duration::from_secs(60),
        request_deadline: Duration::from_secs(2),
        connect_timeout: Duration::from_secs(1),
        max_retries: 0,
        retry_backoff: Duration::from_millis(1),
        retry_max_backoff: Duration::from_millis(2),
        sample_rate: 1.0,
        routing_jitter: 0.0,
        routing_acceptance_concurrency: 10,
        overload_ejection_initial: Duration::ZERO,
        overload_ejection_max: Duration::ZERO,
        overload_ejection_decay: Duration::from_secs(30),
        subscribe_tick_hint: tick_hint,
        subscribe_reconnect_backoff: Duration::from_millis(20),
    }
}

#[tokio::test]
async fn pool_routes_across_endpoints_with_fresh_load_events() {
    // Both pods serve Subscribe ticks at a fast cadence so the pool's
    // per-endpoint snapshot fills within a few hundred ms. After that,
    // select() should route across the healthy endpoint set.
    let pod_a_limiter = Arc::new(Semaphore::new(8));
    let pod_b_limiter = Arc::new(Semaphore::new(8));

    let pod_a = spawn_real_server(pod_a_limiter.clone(), 8).await;
    let pod_b = spawn_real_server(pod_b_limiter.clone(), 8).await;

    let pool = EndpointPool::from_addrs(
        pool_config("test", Duration::from_millis(25)),
        &[pod_a, pod_b],
    )
    .expect("build pool");

    // Give the subscription tasks a few ticks to populate both snapshots.
    // The server's tick is 25ms; 500ms is generous but keeps the test snappy.
    tokio::time::sleep(Duration::from_millis(500)).await;

    // Random selection across the fresh, healthy set: over many picks both
    // pods must appear (and only those two — every pick is a known pod).
    let mut picks = std::collections::HashSet::new();
    for _ in 0..50 {
        let handle = pool.select(&[]).await.expect("select succeeds");
        assert!(handle.addr == pod_a || handle.addr == pod_b);
        picks.insert(handle.addr);
    }
    assert_eq!(
        picks.len(),
        2,
        "both fresh pods should be selected over time"
    );
}
