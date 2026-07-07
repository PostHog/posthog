//! Shared fixtures for remote-resolution integration tests.
//!
//! `tests/common/mod.rs` is the canonical place to put helpers that multiple
//! integration test binaries (`tests/remote_resolution.rs`,
//! `tests/remote_resolution_hardening.rs`,
//! `tests/remote_resolution_parity.rs`, …) reuse. Keep new fixtures here
//! rather than duplicating them per test file so failure-mode tests can be
//! extended without re-writing the in-process gRPC stub.

#![allow(dead_code)]

use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::native::DebugImage;
use cymbal::stages::pipeline::ExceptionEventPipelineItem;
use cymbal::stages::resolution::{
    remote::{
        config::RemoteResolutionConfig, pool::EndpointPool, resolver::RemoteResolutionContext,
    },
    ResolutionStage,
};
use cymbal::symbolication::symbol::SymbolResolver;
use cymbal::symbolication::symbol_store::chunk_id::OrChunkId;
use cymbal::symbolication::symbol_store::proguard::ProguardRef;
use cymbal::types::{
    batch::Batch, exception_properties::ExceptionProperties, operator::TeamId, stage::Stage,
    Exception, ExceptionList, Stacktrace,
};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::{
    CymbalResolution, CymbalResolutionServer,
};
use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, Accepted, Done, Error as ItemError, ErrorKind, LoadEvent, ResolveItem,
    ResolveOutcome, Retry, SubscribeRequest,
};
use futures::{Stream, StreamExt};
use tokio::sync::mpsc;
use tokio::sync::Semaphore;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use uuid::Uuid;

pub type ResolveStream = Pin<Box<dyn Stream<Item = Result<ResolveOutcome, Status>> + Send>>;
pub type SubscribeStream = Pin<Box<dyn Stream<Item = Result<LoadEvent, Status>> + Send>>;

/// Fixture stub for the cymbal.resolution.v1 server. Streams are recorded
/// separately from items: the mux opens one long-lived bidi stream per
/// endpoint, while tests usually care about the individual ResolveItems that
/// actually crossed that stream.
#[derive(Clone)]
pub struct StubServer {
    pub behavior: ServerBehavior,
    pub streams: Arc<Mutex<Vec<SocketAddr>>>,
    pub items: Arc<Mutex<Vec<ResolveItem>>>,
    pub addr: SocketAddr,
    pub stream_counter: Arc<AtomicU32>,
}

/// Catalog of behaviors a test stub can advertise. Keep failure modes here so
/// the integration suite stays fixture-driven and the bidi protocol shape is
/// shared across remote-resolution tests.
#[derive(Clone)]
pub enum ServerBehavior {
    /// Echo each item back as Done with the input exception unchanged.
    Happy,
    /// Echo each item back as Done with the input exception unchanged but
    /// sleep `delay` before emitting each outcome.
    HappyDelayed { delay: Duration },
    /// Emit Accepted immediately, then emit Done after `delay` without blocking
    /// reads for subsequent items.
    AcceptedThenDoneDelayed { delay: Duration },
    /// Fail the Resolve stream during setup with Status::Unavailable.
    AlwaysUnavailable,
    /// Fail the Resolve stream during setup with Status::InvalidArgument.
    AlwaysInvalidArgument,
    /// Delay stream setup long enough for caller deadlines to fire.
    SlowerThanDeadline { sleep: Duration },
    /// Emit Retry outcomes for every item on this stream.
    Retry,
    /// Emit ErrorKind::Overloaded outcomes for every item on this stream.
    Overloaded,
    /// Emit one Done for the first item then break the stream with Internal.
    InterruptAfterFirst,
    /// Emit the first item as Done and every subsequent item as Error.
    ErrorAfterFirst { kind: ErrorKind },
}

impl StubServer {
    pub fn new(behavior: ServerBehavior, addr: SocketAddr) -> Self {
        Self {
            behavior,
            streams: Arc::new(Mutex::new(Vec::new())),
            items: Arc::new(Mutex::new(Vec::new())),
            addr,
            stream_counter: Arc::new(AtomicU32::new(0)),
        }
    }
}

#[tonic::async_trait]
impl CymbalResolution for StubServer {
    type ResolveStream = ResolveStream;
    type SubscribeStream = SubscribeStream;

    /// Default Subscribe behaviour: emit freshness/draining-only `LoadEvent`s
    /// on a fast tick so snapshot-required routing can warm up quickly.
    async fn subscribe(
        &self,
        _request: Request<SubscribeRequest>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        let (tx, rx) = mpsc::channel(2);
        let instance = format!("stub-{}", self.addr);
        tokio::spawn(async move {
            let mut sequence = 0u64;
            let mut ticker = tokio::time::interval(Duration::from_millis(25));
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                ticker.tick().await;
                sequence += 1;
                let event = LoadEvent {
                    service_instance_id: instance.clone(),
                    draining: false,
                    sequence,
                    message: String::new(),
                };
                if tx.send(Ok(event)).await.is_err() {
                    return;
                }
            }
        });
        Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
    }

    async fn resolve(
        &self,
        request: Request<tonic::Streaming<ResolveItem>>,
    ) -> Result<Response<Self::ResolveStream>, Status> {
        self.streams.lock().unwrap().push(self.addr);
        self.stream_counter.fetch_add(1, Ordering::SeqCst);

        match self.behavior.clone() {
            ServerBehavior::AlwaysUnavailable => Err(Status::unavailable("forced shed")),
            ServerBehavior::AlwaysInvalidArgument => {
                Err(Status::invalid_argument("forced bad request"))
            }
            ServerBehavior::SlowerThanDeadline { sleep } => {
                tokio::time::sleep(sleep).await;
                Err(Status::deadline_exceeded("server slow"))
            }
            behavior => {
                let mut inbound = request.into_inner();
                let (tx, rx) = mpsc::channel(16);
                let items = self.items.clone();
                tokio::spawn(async move {
                    let mut seen = 0usize;
                    while let Some(next) = inbound.next().await {
                        let item = match next {
                            Ok(item) => item,
                            Err(err) => {
                                // The client may close its request half as soon as every in-flight
                                // item has a terminal outcome. Tonic can surface that as an h2 body
                                // read error on the server task; don't turn client-side shutdown into
                                // an extra response-stream failure after the fixture has already sent
                                // the outcomes the test cares about.
                                drop(err);
                                return;
                            }
                        };
                        items.lock().unwrap().push(item.clone());
                        seen += 1;

                        match behavior {
                            ServerBehavior::Happy => {
                                send_outcome(&tx, accepted_outcome(&item)).await;
                                send_outcome(&tx, done_outcome(&item)).await;
                            }
                            ServerBehavior::HappyDelayed { delay } => {
                                send_outcome(&tx, accepted_outcome(&item)).await;
                                tokio::time::sleep(delay).await;
                                send_outcome(&tx, done_outcome(&item)).await;
                            }
                            ServerBehavior::AcceptedThenDoneDelayed { delay } => {
                                send_outcome(&tx, accepted_outcome(&item)).await;
                                let item_tx = tx.clone();
                                tokio::spawn(async move {
                                    tokio::time::sleep(delay).await;
                                    send_outcome(&item_tx, done_outcome(&item)).await;
                                });
                            }
                            ServerBehavior::Retry => {
                                send_outcome(&tx, retry_outcome(&item)).await;
                            }
                            ServerBehavior::Overloaded => {
                                send_outcome(&tx, error_outcome(&item, ErrorKind::Overloaded))
                                    .await;
                            }
                            ServerBehavior::InterruptAfterFirst => {
                                if seen == 1 {
                                    send_outcome(&tx, accepted_outcome(&item)).await;
                                    send_outcome(&tx, done_outcome(&item)).await;
                                    let _ignored = tx
                                        .send(Err(Status::internal("simulated interruption")))
                                        .await;
                                    return;
                                }
                                send_outcome(&tx, accepted_outcome(&item)).await;
                                send_outcome(&tx, done_outcome(&item)).await;
                            }
                            ServerBehavior::ErrorAfterFirst { kind } => {
                                if seen == 1 {
                                    send_outcome(&tx, accepted_outcome(&item)).await;
                                    send_outcome(&tx, done_outcome(&item)).await;
                                } else {
                                    send_outcome(&tx, accepted_outcome(&item)).await;
                                    send_outcome(&tx, error_outcome(&item, kind)).await;
                                }
                            }
                            ServerBehavior::AlwaysUnavailable
                            | ServerBehavior::AlwaysInvalidArgument
                            | ServerBehavior::SlowerThanDeadline { .. } => unreachable!(
                                "stream setup failures return before spawning the bidi task"
                            ),
                        }
                    }
                });
                Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
            }
        }
    }
}

async fn send_outcome(tx: &mpsc::Sender<Result<ResolveOutcome, Status>>, outcome: ResolveOutcome) {
    let _ignored = tx.send(Ok(outcome)).await;
}

fn accepted_outcome(item: &ResolveItem) -> ResolveOutcome {
    ResolveOutcome {
        id: item.id,
        result: Some(resolve_outcome::Result::Accepted(Accepted {})),
    }
}

fn done_outcome(item: &ResolveItem) -> ResolveOutcome {
    ResolveOutcome {
        id: item.id,
        result: Some(resolve_outcome::Result::Done(Done {
            resolved_exception_json: item.exception_json.clone(),
        })),
    }
}

fn retry_outcome(item: &ResolveItem) -> ResolveOutcome {
    ResolveOutcome {
        id: item.id,
        result: Some(resolve_outcome::Result::Retry(Retry {
            code: "retry".to_string(),
            message: "try later".to_string(),
            retry_after_ms: 0,
        })),
    }
}

fn error_outcome(item: &ResolveItem, kind: ErrorKind) -> ResolveOutcome {
    ResolveOutcome {
        id: item.id,
        result: Some(resolve_outcome::Result::Error(ItemError {
            kind: kind as i32,
            message: format!("forced {} from stub", kind.as_str_name()),
            details_json: Vec::new(),
        })),
    }
}

/// Bind to an OS-assigned local port, drop the listener, and spawn a tonic
/// server. Returns the address once a probe TCP connect succeeds, so callers
/// never dial before the bind has actually happened.
pub async fn spawn_stub_server(
    behavior: ServerBehavior,
) -> (SocketAddr, Arc<Mutex<Vec<ResolveItem>>>) {
    let (addr, _streams, items) = spawn_recording_stub_server(behavior).await;
    (addr, items)
}

pub async fn spawn_recording_stub_server(
    behavior: ServerBehavior,
) -> (
    SocketAddr,
    Arc<Mutex<Vec<SocketAddr>>>,
    Arc<Mutex<Vec<ResolveItem>>>,
) {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    let stub = StubServer::new(behavior, addr);
    let streams = stub.streams.clone();
    let items = stub.items.clone();

    tokio::spawn(async move {
        let _outcome = tonic::transport::Server::builder()
            .add_service(CymbalResolutionServer::new(stub))
            .serve(addr)
            .await;
    });

    for _ in 0..40 {
        if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(50)).is_ok() {
            return (addr, streams, items);
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    panic!("test stub server failed to come up at {addr}");
}

/// Reserve a local TCP port without keeping a listener bound to it. The
/// returned address is therefore guaranteed not to accept connections, which
/// is what `connection-refused` failure tests need.
pub fn unbound_addr() -> SocketAddr {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    addr
}

pub fn make_config(max_retries: u32, deadline: Duration) -> RemoteResolutionConfig {
    make_config_with_sample_rate(max_retries, deadline, 1.0)
}

pub fn make_config_with_sample_rate(
    max_retries: u32,
    deadline: Duration,
    sample_rate: f64,
) -> RemoteResolutionConfig {
    RemoteResolutionConfig {
        host: "test-only".to_string(),
        port: 0,
        internal_api_secret: "test-secret".to_string(),
        dns_refresh: Duration::from_secs(60),
        request_deadline: deadline,
        connect_timeout: Duration::from_secs(1),
        max_retries,
        // Tests run with near-zero backoff so retries don't drag suite latency;
        // production defaults are tuned for thundering-herd mitigation.
        retry_backoff: Duration::from_millis(1),
        retry_max_backoff: Duration::from_millis(2),
        sample_rate,
        routing_jitter: 0.0,
        routing_acceptance_concurrency: 10,
        overload_ejection_initial: Duration::ZERO,
        overload_ejection_max: Duration::ZERO,
        overload_ejection_decay: Duration::from_secs(30),
        // Subscription cadence is irrelevant for tests that don't wire the
        // subscription client — kept short so tests that do consume it run
        // quickly when they opt in via a dedicated pool builder.
        subscribe_tick_hint: Duration::from_millis(50),
        subscribe_reconnect_backoff: Duration::from_millis(50),
    }
}

pub async fn make_ctx(
    addrs: &[SocketAddr],
    max_retries: u32,
    deadline: Duration,
) -> RemoteResolutionContext {
    let config = make_config(max_retries, deadline);
    let pool = EndpointPool::from_addrs(config.clone(), addrs).expect("build pool");
    if !addrs.is_empty() {
        wait_until_routable(&pool).await;
    }
    RemoteResolutionContext::new(pool, config)
}

pub async fn make_ctx_with_sample_rate(
    addrs: &[SocketAddr],
    max_retries: u32,
    deadline: Duration,
    sample_rate: f64,
) -> RemoteResolutionContext {
    let config = make_config_with_sample_rate(max_retries, deadline, sample_rate);
    let pool = EndpointPool::from_addrs(config.clone(), addrs).expect("build pool");
    if !addrs.is_empty() {
        wait_until_routable(&pool).await;
    }
    RemoteResolutionContext::new(pool, config)
}

/// Wait until the pool has at least one routable endpoint (a fresh
/// `LoadEvent` snapshot has arrived). Snapshot-required routing means an
/// empty pool persists until the per-endpoint Subscribe stream delivers its
/// first event; without this small warm-up tests race the first tick and
/// observe spurious `pool_empty` failures.
pub async fn wait_until_routable(pool: &Arc<cymbal::stages::resolution::remote::EndpointPool>) {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        if pool.select(&[]).await.is_ok() {
            return;
        }
        if Instant::now() >= deadline {
            panic!("pool never became routable within warm-up window");
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
}

#[derive(Default)]
pub struct NoopResolver;

#[async_trait]
impl SymbolResolver for NoopResolver {
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
        unreachable!("integration fixtures do not exercise Java class resolution")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        unreachable!("integration fixtures do not exercise Dart name resolution")
    }
}

pub fn remote_stage(ctx: RemoteResolutionContext) -> ResolutionStage {
    ResolutionStage {
        symbol_resolver: Arc::new(NoopResolver),
        symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
        remote: Some(ctx),
    }
}

pub fn local_stage() -> ResolutionStage {
    ResolutionStage {
        symbol_resolver: Arc::new(NoopResolver),
        symbol_resolution_limiter: Arc::new(Semaphore::new(4)),
        remote: None,
    }
}

pub async fn process_one(
    stage: ResolutionStage,
    evt: ExceptionProperties,
) -> Result<ExceptionProperties, UnhandledError> {
    let batch: Batch<ExceptionEventPipelineItem> = Batch::from(vec![Ok(evt)]);
    let result = stage.process(batch).await?;
    let mut items: Vec<_> = result.into_iter().collect();
    assert_eq!(items.len(), 1, "single-event batch must produce one output");
    Ok(items.remove(0).expect("event must not be EventError"))
}

pub fn build_event(num_exceptions: usize) -> ExceptionProperties {
    let exceptions: Vec<Exception> = (0..num_exceptions)
        .map(|i| Exception {
            exception_id: None,
            exception_type: format!("Boom{i}"),
            exception_message: format!("message {i}"),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: Some(Stacktrace::Raw { frames: vec![] }),
        })
        .collect();
    ExceptionProperties {
        exception_list: ExceptionList::from(exceptions),
        exception_sources: None,
        exception_types: None,
        exception_messages: None,
        exception_functions: None,
        exception_handled: None,
        exception_releases: Default::default(),
        fingerprint: None,
        fingerprint_version: None,
        proposed_fingerprint: None,
        fingerprint_record: None,
        issue_id: None,
        proposed_issue_name: None,
        proposed_issue_description: None,
        debug_images: Vec::new(),
        props: Default::default(),
        uuid: Uuid::now_v7(),
        timestamp: String::new(),
        team_id: 7,
        issue: None,
        legacy_order_exception_list: None,
        legacy_order_resolved: None,
    }
}
