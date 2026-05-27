//! End-to-end coverage for the load event bus (`Subscribe` RPC) and
//! pool routing on server-reported load.
//!
//! These tests bring up a real cymbal-resolution server with a fake symbol
//! resolver, build an `EndpointPool` pointed at it, and verify that the
//! pool's per-endpoint subscription task actually fills the load snapshot
//! and biases routing accordingly. The unit-level pool/subscription tests
//! validate the in-process logic; this file exercises the gRPC wire as well.

mod common;

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::remote::{EndpointPool, RemoteResolutionConfig};
use cymbal::stages::resolution::symbol::SymbolResolver;
use cymbal::symbol_store::chunk_id::OrChunkId;
use cymbal::symbol_store::proguard::ProguardRef;
use cymbal::types::operator::TeamId;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use cymbal_resolution::service::{CymbalResolutionService, ServiceConfig};
use tokio::sync::Semaphore;

#[derive(Default)]
struct EmptyResolver;

#[async_trait]
impl SymbolResolver for EmptyResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: TeamId,
        _frame: &RawFrame,
        _debug_images: &[AppleDebugImage],
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
/// limiter so tests can manipulate server-reported load by pinning permits.
/// Server-reported load tracks the item limiter, which is the new admission
/// gate the pool routes against.
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
        degraded_load_ratio: f64::INFINITY,
    };
    // Symbol limiter is irrelevant for these tests because EmptyResolver
    // never acquires; size it generously so it never gates anything.
    let symbol_limiter = Arc::new(Semaphore::new(64));
    let service = CymbalResolutionService::new(
        resolver,
        symbol_limiter,
        item_limiter,
        format!("real-{addr}"),
        max_in_flight,
        service_config,
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
        dns_refresh: Duration::from_secs(60),
        request_deadline: Duration::from_secs(2),
        connect_timeout: Duration::from_secs(1),
        max_retries: 0,
        retry_backoff: Duration::from_millis(1),
        retry_max_backoff: Duration::from_millis(2),
        sample_rate: 1.0,
        max_batch_items: 64,
        subscribe_tick_hint: tick_hint,
        subscribe_reconnect_backoff: Duration::from_millis(20),
    }
}

#[tokio::test]
async fn pool_routes_to_endpoint_with_lower_server_reported_load() {
    // Pod A holds 7 of its 8 permits; pod B holds none. Both serve Subscribe
    // ticks at a fast cadence so the pool's per-endpoint snapshot fills
    // within a few hundred ms. After that, select() must consistently route
    // new requests to pod B (the low-load endpoint), regardless of caller-
    // side in-flight counts.
    let pod_a_limiter = Arc::new(Semaphore::new(8));
    let pod_b_limiter = Arc::new(Semaphore::new(8));

    // Pre-take 7 permits on pod A so its reported in_flight is high.
    let mut held = Vec::new();
    for _ in 0..7 {
        held.push(pod_a_limiter.clone().acquire_owned().await.unwrap());
    }

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

    // Drive several selections — pod B must dominate because its reported
    // load ratio (0/8) is much lower than pod A's (7/8). We allow a small
    // tolerance for a single misroute caused by a tick that hadn't propagated
    // before the first select.
    let mut b_picks = 0;
    let mut total = 0;
    let mut handles = Vec::new();
    for _ in 0..20 {
        let handle = pool.select().await.expect("select succeeds");
        total += 1;
        if handle.addr == pod_b {
            b_picks += 1;
        }
        handles.push(handle);
    }

    assert!(
        b_picks as f64 / total as f64 >= 0.8,
        "expected pod_b ({pod_b}) to receive most routing; got {b_picks}/{total}",
    );
    drop(held);
}
