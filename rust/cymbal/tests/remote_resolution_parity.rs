//! Parity tests for Batch 4.
//!
//! These tests stand up an in-process `cymbal-resolution` service backed by a
//! shared fake `SymbolResolver`, run the same exception through both the
//! local `ResolutionStage` (`remote = None`) and the remote stage
//! (`remote = Some(ctx)`), and assert the resulting `ExceptionList` is
//! byte-for-byte identical after JSON round-tripping. Parity is the v1
//! correctness guarantee: when remote mode is enabled, callers must observe
//! the same resolved frames they would have seen locally.
//!
//! Fixtures live in `tests/common/mod.rs`. Add new resolution types here as
//! they become supported by the remote service.

mod common;

use std::net::SocketAddr;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common::{build_event, make_ctx};
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::native::DebugImage;
use cymbal::modes::resolution::load_monitor::LoadMonitor;
use cymbal::modes::resolution::service::{CymbalResolutionService, ServiceConfig};
use cymbal::stages::resolution::ResolutionStage;
use cymbal::symbolication::symbol::SymbolResolver;
use cymbal::symbolication::symbol_store::chunk_id::OrChunkId;
use cymbal::symbolication::symbol_store::proguard::ProguardRef;
use cymbal::types::batch::Batch;
use cymbal::types::operator::TeamId;
use cymbal::types::stage::Stage;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use tokio::sync::Semaphore;

/// Fake symbol resolver shared by both sides of the parity comparison. Every
/// resolution method is deterministic and produces the same output for the
/// same input — the point is that any divergence in the resolved
/// `ExceptionList` must come from plumbing differences, not from non-determinism.
#[derive(Default)]
struct FakeResolver;

#[async_trait]
impl SymbolResolver for FakeResolver {
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
        unreachable!("parity fixtures do not exercise Java class resolution")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        unreachable!("parity fixtures do not exercise Dart name resolution")
    }
}

async fn spawn_cymbal_resolution_with_resolver(resolver: Arc<dyn SymbolResolver>) -> SocketAddr {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    let limiter = Arc::new(Semaphore::new(4));
    let service_config = ServiceConfig {
        default_tick_interval: Duration::from_millis(50),
        min_tick_interval: Duration::from_millis(10),
        max_tick_interval: Duration::from_secs(1),
    };
    let service = CymbalResolutionService::new(
        resolver,
        limiter,
        LoadMonitor::new(4),
        "parity-stub",
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
    panic!("cymbal-resolution server failed to come up at {addr}");
}

fn local_stage(resolver: Arc<dyn SymbolResolver>) -> ResolutionStage {
    ResolutionStage {
        symbol_resolver: resolver,
        symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
        remote: None,
    }
}

fn remote_stage(
    resolver: Arc<dyn SymbolResolver>,
    remote: cymbal::stages::resolution::remote::resolver::RemoteResolutionContext,
) -> ResolutionStage {
    ResolutionStage {
        // The symbol_resolver field is unused in remote mode, but
        // ResolutionStage requires one. Pass the same fake so any accidental
        // local fallback would still produce parity-matching output.
        symbol_resolver: resolver,
        symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
        remote: Some(remote),
    }
}

async fn run_stage(
    stage: ResolutionStage,
    evt: cymbal::types::exception_properties::ExceptionProperties,
) -> cymbal::types::exception_properties::ExceptionProperties {
    let batch: Batch<cymbal::stages::pipeline::ExceptionEventPipelineItem> =
        Batch::from(vec![Ok(evt)]);
    let result = stage.process(batch).await.expect("stage processed");
    let mut items: Vec<_> = result.into_iter().collect();
    assert_eq!(items.len(), 1, "single-event batch must produce one output");
    items.remove(0).expect("event must not be EventError")
}

#[tokio::test]
async fn local_and_remote_stages_produce_identical_exception_list_for_empty_stacks() {
    let resolver: Arc<dyn SymbolResolver> = Arc::new(FakeResolver);
    let addr = spawn_cymbal_resolution_with_resolver(resolver.clone()).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;

    let evt = build_event(3);
    let local_out = run_stage(local_stage(resolver.clone()), evt.clone()).await;
    let remote_out = run_stage(remote_stage(resolver, ctx), evt).await;

    // Compare via JSON round-trip so the test stays robust against
    // Exception's #[serde(skip_serializing_if = "Option::is_none")] fields and
    // the difference in how `Stacktrace::Raw` vs `Stacktrace::Resolved`
    // serialize.
    let local_json = serde_json::to_value(&local_out.exception_list).unwrap();
    let remote_json = serde_json::to_value(&remote_out.exception_list).unwrap();
    assert_eq!(local_json, remote_json, "exception_list parity");

    // Properties derived by PropertiesResolver should also match in both
    // paths, since they're computed from the (parity-checked) exception_list.
    // `unique_by` preserves exception_list order, so compare directly.
    assert_eq!(local_out.exception_types, remote_out.exception_types);
    assert_eq!(local_out.exception_messages, remote_out.exception_messages);
    assert_eq!(local_out.exception_handled, remote_out.exception_handled);
}

#[tokio::test]
async fn parity_holds_for_empty_exception_list() {
    let resolver: Arc<dyn SymbolResolver> = Arc::new(FakeResolver);
    let addr = spawn_cymbal_resolution_with_resolver(resolver.clone()).await;
    let ctx = make_ctx(&[addr], 0, Duration::from_secs(5)).await;

    let evt = build_event(0);
    let local_out = run_stage(local_stage(resolver.clone()), evt.clone()).await;
    let remote_out = run_stage(remote_stage(resolver, ctx), evt).await;

    assert_eq!(local_out.exception_list.len(), 0);
    assert_eq!(remote_out.exception_list.len(), 0);
    assert_eq!(local_out.exception_types, remote_out.exception_types);
    assert_eq!(local_out.exception_messages, remote_out.exception_messages);
}
