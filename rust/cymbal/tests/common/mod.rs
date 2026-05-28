//! Shared fixtures for remote-resolution integration tests.
//!
//! `tests/common/mod.rs` is the canonical place to put helpers that multiple
//! integration test binaries (`tests/remote_resolution.rs`,
//! `tests/remote_resolution_hardening.rs`,
//! `tests/remote_resolution_parity.rs`, …) reuse. Keep new fixtures here
//! rather than duplicating them per test file — Batch 4 onwards leans heavily
//! on this pattern so failure-mode tests can be extended without re-writing
//! the in-process gRPC stub.

#![allow(dead_code)]

use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::pipeline::ExceptionEventPipelineItem;
use cymbal::stages::resolution::{
    remote::{
        config::RemoteResolutionConfig, pool::EndpointPool, resolver::RemoteResolutionContext,
    },
    symbol::SymbolResolver,
    ResolutionStage,
};
use cymbal::symbol_store::chunk_id::OrChunkId;
use cymbal::symbol_store::proguard::ProguardRef;
use cymbal::types::{
    batch::Batch, exception_properties::ExceptionProperties, operator::TeamId, stage::Stage,
    Exception, ExceptionList, Stacktrace,
};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::{
    CymbalResolution, CymbalResolutionServer,
};
use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, BatchSummary, Done, Error as ItemError, ItemOutcome, LoadEvent, Outcome,
    ResolveRequest, Retry, SubscribeRequest,
};
use futures::Stream;
use tokio::sync::mpsc;
use tokio::sync::Semaphore;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use uuid::Uuid;

pub type ResolveStream = Pin<Box<dyn Stream<Item = Result<Outcome, Status>> + Send>>;

/// Fixture stub for the cymbal.resolution.v1 server. Each request the server
/// receives is recorded so tests can assert which endpoint was chosen on
/// which attempt and how many requests reached each behavior.
#[derive(Clone)]
pub struct StubServer {
    pub behavior: ServerBehavior,
    pub received: Arc<Mutex<Vec<SocketAddr>>>,
    pub requests: Arc<Mutex<Vec<ResolveRequest>>>,
    pub addr: SocketAddr,
    pub attempt_counter: Arc<AtomicU32>,
}

/// Catalog of behaviors a test stub can advertise. Extend this list when a new
/// failure-mode test needs a new stub variant — keeping every variant here
/// (instead of one-off custom stubs per test) keeps the integration suite
/// fixture-driven and easy for the next agent to extend.
#[derive(Clone)]
pub enum ServerBehavior {
    /// Echo each item back as Done with the input exception unchanged.
    Happy,
    /// Echo each item back as Done with the input exception unchanged but
    /// sleep `delay` before emitting outcomes. Useful for cancellation tests.
    HappyDelayed { delay: Duration },
    /// Always return Status::Unavailable to force the caller to retry.
    AlwaysUnavailable,
    /// Return Status::InvalidArgument — terminal, should not retry.
    AlwaysInvalidArgument,
    /// Sleep longer than the caller's deadline before responding with a
    /// deadline-exceeded status. Used by deadline cancellation tests.
    SlowerThanDeadline { sleep: Duration },
    /// Emit one Retry outcome per item plus a BatchSummary; caller should
    /// retry. After `retry_until_attempt` attempts, transition to Happy.
    RetryUntil { retry_until_attempt: u32 },
    /// Emit one Done for the first item then drop the stream with an internal
    /// error. Used to verify mid-stream interruption is classified as
    /// retryable.
    InterruptAfterFirst,
    /// Emit fewer ItemOutcomes than items submitted and a BatchSummary that
    /// flags the gap as `missing_items`. Used to verify missing-item retry.
    DropsLastItem,
    /// Emit all ItemOutcomes successfully but close the stream cleanly
    /// without ever sending the terminal BatchSummary. Mimics the server's
    /// spawn task panicking or `tx.send` failing after items but before
    /// summary: items it never produced look identical to "missing" on the
    /// client without a summary to disambiguate, so the caller must retry.
    DropsSummary,
    /// Emit the first item as Done and every subsequent item as a non-retryable
    /// `Error` outcome (e.g. server-side `invalid_payload`), plus a valid
    /// BatchSummary. The retry loop has no path for `Error`, so this exercises
    /// the all-or-nothing rollout policy: any `Error` item must fail the batch
    /// rather than silently downgrade the affected exceptions.
    ErrorAfterFirst { code: &'static str },
}

impl StubServer {
    pub fn new(behavior: ServerBehavior, addr: SocketAddr) -> Self {
        Self {
            behavior,
            received: Arc::new(Mutex::new(Vec::new())),
            requests: Arc::new(Mutex::new(Vec::new())),
            addr,
            attempt_counter: Arc::new(AtomicU32::new(0)),
        }
    }
}

pub type SubscribeStream = Pin<Box<dyn Stream<Item = Result<LoadEvent, Status>> + Send>>;

#[tonic::async_trait]
impl CymbalResolution for StubServer {
    type ResolveStream = ResolveStream;
    type SubscribeStream = SubscribeStream;

    /// Default Subscribe behaviour: emit `LoadEvent`s on a fast tick so the
    /// caller's `LoadSnapshot` stays fresh under snapshot-required routing.
    /// Mimics the real cymbal-resolution server's periodic tick — the
    /// previous one-shot stub left snapshots to expire and the pool would
    /// stop routing once the freshness window elapsed.
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
                    degraded: false,
                    draining: false,
                    in_flight: 0,
                    max_in_flight: 8,
                    sequence,
                    message: String::new(),
                    suggested_max_batch_items: 8,
                };
                if tx.send(Ok(event)).await.is_err() {
                    return; // caller dropped the stream
                }
            }
        });
        let stream: SubscribeStream = Box::pin(ReceiverStream::new(rx));
        Ok(Response::new(stream))
    }

    async fn resolve(
        &self,
        request: Request<ResolveRequest>,
    ) -> Result<Response<Self::ResolveStream>, Status> {
        self.received.lock().unwrap().push(self.addr);
        let attempt = self.attempt_counter.fetch_add(1, Ordering::SeqCst);
        let req = request.into_inner();
        self.requests.lock().unwrap().push(req.clone());

        let behavior = match &self.behavior {
            ServerBehavior::RetryUntil {
                retry_until_attempt,
            } => {
                if attempt < *retry_until_attempt {
                    ServerBehavior::RetryUntil {
                        retry_until_attempt: *retry_until_attempt,
                    }
                } else {
                    ServerBehavior::Happy
                }
            }
            other => other.clone(),
        };

        match behavior {
            ServerBehavior::AlwaysUnavailable => Err(Status::unavailable("forced shed")),
            ServerBehavior::AlwaysInvalidArgument => {
                Err(Status::invalid_argument("forced bad request"))
            }
            ServerBehavior::SlowerThanDeadline { sleep } => {
                tokio::time::sleep(sleep).await;
                Err(Status::deadline_exceeded("server slow"))
            }
            ServerBehavior::RetryUntil { .. } => {
                let outcomes = build_retry_outcomes(&req);
                Ok(Response::new(stream_of(outcomes).await))
            }
            ServerBehavior::Happy => {
                let outcomes = build_happy_outcomes(&req);
                Ok(Response::new(stream_of(outcomes).await))
            }
            ServerBehavior::HappyDelayed { delay } => {
                tokio::time::sleep(delay).await;
                let outcomes = build_happy_outcomes(&req);
                Ok(Response::new(stream_of(outcomes).await))
            }
            ServerBehavior::InterruptAfterFirst => {
                // Emit one Done outcome then close the stream with an internal
                // error so the client side observes a mid-stream tonic Status
                // rather than a clean end-of-stream.
                let (tx, rx) = mpsc::channel(2);
                if let Some(first) = req.items.first() {
                    let outcome = build_done_outcome(&req.batch_id, 1, first);
                    let _send = tx.send(Ok(outcome)).await;
                }
                let _send = tx
                    .send(Err(Status::internal("simulated interruption")))
                    .await;
                let stream: ResolveStream = Box::pin(ReceiverStream::new(rx));
                Ok(Response::new(stream))
            }
            ServerBehavior::DropsLastItem => {
                let mut seq = 0u64;
                let mut outcomes: Vec<Outcome> = Vec::with_capacity(req.items.len());
                let mut missing = Vec::new();
                for (i, item) in req.items.iter().enumerate() {
                    if i + 1 == req.items.len() {
                        // Last item is intentionally dropped; record it in
                        // the BatchSummary so the caller treats this as a
                        // missing-item retry.
                        missing.push(cymbal_proto::cymbal::resolution::v1::ItemReference {
                            item_id: item.item_id.clone(),
                            item_index: item.item_index,
                        });
                        continue;
                    }
                    seq += 1;
                    outcomes.push(build_done_outcome(&req.batch_id, seq, item));
                }
                seq += 1;
                outcomes.push(Outcome {
                    batch_id: req.batch_id.clone(),
                    sequence: seq,
                    message: Some(outcome::Message::BatchSummary(BatchSummary {
                        submitted_items: req.items.len() as u32,
                        item_outcomes: (req.items.len() - 1) as u32,
                        done_items: (req.items.len() - 1) as u32,
                        error_items: 0,
                        retry_items: 0,
                        missing_items: missing,
                        duplicate_items: vec![],
                    })),
                });
                Ok(Response::new(stream_of(outcomes).await))
            }
            ServerBehavior::DropsSummary => {
                // Emit Done for every item, then close the stream without
                // ever sending a BatchSummary — mimics the server-side spawn
                // task unwinding after items but before its terminal send.
                let mut outcomes: Vec<Outcome> = Vec::with_capacity(req.items.len());
                for (i, item) in req.items.iter().enumerate() {
                    outcomes.push(build_done_outcome(&req.batch_id, (i + 1) as u64, item));
                }
                Ok(Response::new(stream_of(outcomes).await))
            }
            ServerBehavior::ErrorAfterFirst { code } => {
                let mut outcomes: Vec<Outcome> = Vec::with_capacity(req.items.len() + 1);
                let mut done_count = 0u32;
                let mut error_count = 0u32;
                for (i, item) in req.items.iter().enumerate() {
                    let result = if i == 0 {
                        done_count += 1;
                        item_outcome::Result::Done(Done {
                            resolved_exception_json: item
                                .exception
                                .as_ref()
                                .map(|p| p.exception_json.clone())
                                .unwrap_or_default(),
                        })
                    } else {
                        error_count += 1;
                        item_outcome::Result::Error(ItemError {
                            code: code.to_string(),
                            message: format!("forced {code} from stub"),
                            details_json: Vec::new(),
                        })
                    };
                    outcomes.push(Outcome {
                        batch_id: req.batch_id.clone(),
                        sequence: (i + 1) as u64,
                        message: Some(outcome::Message::ItemOutcome(ItemOutcome {
                            item_id: item.item_id.clone(),
                            item_index: item.item_index,
                            result: Some(result),
                        })),
                    });
                }
                outcomes.push(Outcome {
                    batch_id: req.batch_id.clone(),
                    sequence: (req.items.len() + 1) as u64,
                    message: Some(outcome::Message::BatchSummary(BatchSummary {
                        submitted_items: req.items.len() as u32,
                        item_outcomes: req.items.len() as u32,
                        done_items: done_count,
                        error_items: error_count,
                        retry_items: 0,
                        missing_items: vec![],
                        duplicate_items: vec![],
                    })),
                });
                Ok(Response::new(stream_of(outcomes).await))
            }
        }
    }
}

fn build_done_outcome(
    batch_id: &str,
    sequence: u64,
    item: &cymbal_proto::cymbal::resolution::v1::ExceptionResolutionItem,
) -> Outcome {
    let payload = item
        .exception
        .as_ref()
        .map(|e| e.exception_json.clone())
        .unwrap_or_default();
    Outcome {
        batch_id: batch_id.to_string(),
        sequence,
        message: Some(outcome::Message::ItemOutcome(ItemOutcome {
            item_id: item.item_id.clone(),
            item_index: item.item_index,
            result: Some(item_outcome::Result::Done(Done {
                resolved_exception_json: payload,
            })),
        })),
    }
}

pub fn build_happy_outcomes(req: &ResolveRequest) -> Vec<Outcome> {
    // ServiceInfo no longer rides on the Resolve stream — load lives on the
    // Subscribe stream now. Resolve outcomes are item outcomes plus the
    // terminal summary only.
    let mut sequence = 0u64;
    let mut next_seq = || {
        sequence += 1;
        sequence
    };
    let mut outcomes = Vec::with_capacity(req.items.len() + 1);
    let mut done = 0u32;
    for item in &req.items {
        done += 1;
        outcomes.push(build_done_outcome(&req.batch_id, next_seq(), item));
    }
    outcomes.push(Outcome {
        batch_id: req.batch_id.clone(),
        sequence: next_seq(),
        message: Some(outcome::Message::BatchSummary(BatchSummary {
            submitted_items: req.items.len() as u32,
            item_outcomes: done,
            done_items: done,
            error_items: 0,
            retry_items: 0,
            missing_items: vec![],
            duplicate_items: vec![],
        })),
    });
    outcomes
}

pub fn build_retry_outcomes(req: &ResolveRequest) -> Vec<Outcome> {
    let mut sequence = 0u64;
    let mut next_seq = || {
        sequence += 1;
        sequence
    };
    let mut outcomes = Vec::with_capacity(req.items.len() + 1);
    for item in &req.items {
        outcomes.push(Outcome {
            batch_id: req.batch_id.clone(),
            sequence: next_seq(),
            message: Some(outcome::Message::ItemOutcome(ItemOutcome {
                item_id: item.item_id.clone(),
                item_index: item.item_index,
                result: Some(item_outcome::Result::Retry(Retry {
                    code: "overloaded".to_string(),
                    message: "try later".to_string(),
                    retry_after_ms: 0,
                })),
            })),
        });
    }
    outcomes.push(Outcome {
        batch_id: req.batch_id.clone(),
        sequence: next_seq(),
        message: Some(outcome::Message::BatchSummary(BatchSummary {
            submitted_items: req.items.len() as u32,
            item_outcomes: req.items.len() as u32,
            done_items: 0,
            error_items: 0,
            retry_items: req.items.len() as u32,
            missing_items: vec![],
            duplicate_items: vec![],
        })),
    });
    outcomes
}

async fn stream_of(outcomes: Vec<Outcome>) -> ResolveStream {
    let (tx, rx) = mpsc::channel(outcomes.len().max(1));
    for outcome in outcomes {
        tx.send(Ok(outcome)).await.unwrap();
    }
    Box::pin(ReceiverStream::new(rx))
}

/// Bind to an OS-assigned local port, drop the listener, and spawn a tonic
/// server. Returns the address once a probe TCP connect succeeds, so callers
/// never dial before the bind has actually happened.
pub async fn spawn_stub_server(
    behavior: ServerBehavior,
) -> (SocketAddr, Arc<Mutex<Vec<SocketAddr>>>) {
    let (addr, received, _requests) = spawn_recording_stub_server(behavior).await;
    (addr, received)
}

pub async fn spawn_recording_stub_server(
    behavior: ServerBehavior,
) -> (
    SocketAddr,
    Arc<Mutex<Vec<SocketAddr>>>,
    Arc<Mutex<Vec<ResolveRequest>>>,
) {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    let stub = StubServer::new(behavior, addr);
    let received = stub.received.clone();
    let requests = stub.requests.clone();

    tokio::spawn(async move {
        let _outcome = tonic::transport::Server::builder()
            .add_service(CymbalResolutionServer::new(stub))
            .serve(addr)
            .await;
    });

    for _ in 0..40 {
        if std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(50)).is_ok() {
            return (addr, received, requests);
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
    make_config_with_sample_rate_and_limits(max_retries, deadline, sample_rate, 64)
}

pub fn make_config_with_sample_rate_and_limits(
    max_retries: u32,
    deadline: Duration,
    sample_rate: f64,
    max_batch_items: usize,
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
        max_batch_items,
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
    RemoteResolutionContext { pool, config }
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
    RemoteResolutionContext { pool, config }
}

pub async fn make_ctx_with_sample_rate_and_limits(
    addrs: &[SocketAddr],
    max_retries: u32,
    deadline: Duration,
    sample_rate: f64,
    max_batch_items: usize,
) -> RemoteResolutionContext {
    let config = make_config_with_sample_rate_and_limits(
        max_retries,
        deadline,
        sample_rate,
        max_batch_items,
    );
    let pool = EndpointPool::from_addrs(config.clone(), addrs).expect("build pool");
    if !addrs.is_empty() {
        wait_until_routable(&pool).await;
    }
    RemoteResolutionContext { pool, config }
}

/// Wait until the pool has at least one routable endpoint (a fresh
/// `LoadEvent` snapshot has arrived). Snapshot-required routing means an
/// empty pool persists until the per-endpoint Subscribe stream delivers its
/// first event; without this small warm-up tests race the first tick and
/// observe spurious `pool_empty` failures.
async fn wait_until_routable(pool: &Arc<cymbal::stages::resolution::remote::EndpointPool>) {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        if pool.select().await.is_ok() {
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
    }
}
