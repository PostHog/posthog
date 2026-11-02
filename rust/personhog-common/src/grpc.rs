use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use futures::stream::unfold;
use http::{HeaderValue, Request, Response};
use metrics::{counter, gauge, histogram};
use pin_project::{pin_project, pinned_drop};
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{AcquireError, OwnedSemaphorePermit, Semaphore};
use tokio::task::futures::TaskLocalFuture;
use tokio::time::error::Elapsed;
use tonic::metadata::MetadataValue;
use tonic::transport::server::Connected;
use tower::util::Oneshot;
use tower::{Layer, Service, ServiceExt};

use crate::storage_error::TimeoutKind;

// ============================================================
// Client name extraction
// ============================================================

/// Header name for client identification in gRPC metadata.
pub const CLIENT_NAME_HEADER: &str = "x-client-name";

/// Metadata key marking a FAILED_PRECONDITION as a definitive semantic
/// refusal rather than a routing-race rejection. The router bounces and
/// retries bare FAILED_PRECONDITION (handoff fences, ownership races,
/// person fences — conditions that clear in watch or healer time) and
/// surfaces exhaustion as retriable UNAVAILABLE; a response carrying this
/// key is a final answer about the request itself and must pass through
/// to the caller unchanged, or a fail-closed refusal degrades into an
/// infinite retry loop. The value is a short reason slug for
/// observability.
pub const SEMANTIC_REFUSAL_METADATA_KEY: &str = "x-semantic-refusal";

/// Never set where the request may have been applied.
pub const NOT_APPLIED_HEADER: &str = "x-not-applied";

/// Marks a DEADLINE_EXCEEDED that a Postgres timeout caused, rather than an
/// expired gRPC deadline. The value names the setting that fired:
/// `statement_timeout` or `lock_timeout`.
pub const DB_TIMEOUT_METADATA_KEY: &str = "x-db-timeout";

pub fn db_timeout_status(message: impl Into<String>, kind: TimeoutKind) -> tonic::Status {
    let mut status = tonic::Status::deadline_exceeded(message.into());
    status.metadata_mut().insert(
        DB_TIMEOUT_METADATA_KEY,
        MetadataValue::from_static(kind.as_str()),
    );
    status
}

/// Build a semantic refusal. The reason is a short slug used as a metric
/// label.
pub fn semantic_refusal(message: impl Into<String>, reason: &'static str) -> tonic::Status {
    let mut status = tonic::Status::failed_precondition(message.into());
    if let Ok(value) = reason.parse() {
        status
            .metadata_mut()
            .insert(SEMANTIC_REFUSAL_METADATA_KEY, value);
    }
    status
}

/// Whether a status is a definitive semantic refusal rather than a
/// transient failure a retry can outlive.
pub fn is_semantic_refusal(status: &tonic::Status) -> bool {
    status.code() == tonic::Code::FailedPrecondition
        && status
            .metadata()
            .contains_key(SEMANTIC_REFUSAL_METADATA_KEY)
}

/// The refusal's reason slug, when present.
pub fn semantic_refusal_reason(status: &tonic::Status) -> Option<&str> {
    status
        .metadata()
        .get(SEMANTIC_REFUSAL_METADATA_KEY)
        .and_then(|v| v.to_str().ok())
}

/// The refusal reason as a metric label: bounded and character-safe, so a
/// misbehaving peer cannot mint unbounded label cardinality or break the
/// metric encoding. Falls back to "unknown".
pub fn refusal_reason_label(status: &tonic::Status) -> &str {
    semantic_refusal_reason(status)
        .filter(|r| {
            r.len() <= 64
                && r.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'))
        })
        .unwrap_or("unknown")
}

/// Header name for caller-tag attribution in gRPC metadata.
/// Identifies the code path / feature area within a service that
/// triggered the request (e.g., "api/feature-flags", "celery/cohort-calculation").
const CALLER_TAG_HEADER: &str = "x-caller-tag";

tokio::task_local! {
    /// Per-request client name, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_client_name()`.
    pub static CLIENT_NAME: Arc<str>;

    /// Per-request caller tag, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_caller_tag()`.
    pub static CALLER_TAG: Arc<str>;

    /// Per-request gRPC method name, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_method_name()`.
    pub static METHOD_NAME: Arc<str>;
}

/// Get the current client name from the task-local, or `"unknown"` if not set.
/// Returns `Arc<str>` so cloning is a cheap refcount bump rather than a
/// heap allocation + memcpy on every call.
pub fn current_client_name() -> Arc<str> {
    CLIENT_NAME
        .try_with(|c| c.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Get the current caller tag from the task-local, or `"unknown"` if not set.
pub fn current_caller_tag() -> Arc<str> {
    CALLER_TAG
        .try_with(|t| t.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Get the current gRPC method name from the task-local, or `"unknown"` if not set.
pub fn current_method_name() -> Arc<str> {
    METHOD_NAME
        .try_with(|m| m.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Label for a failure carrying no gRPC status at all — a client-side
/// error (a serialization failure, say) rather than anything a server
/// said. Part of the same label vocabulary as [`code_as_str`], and
/// deliberately distinct from its `unknown`, which is a real code a
/// server can return.
pub const NON_STATUS: &str = "non_status";

/// Stable snake_case name for a gRPC status code, for use as a metric
/// label. Codes are a fixed vocabulary, which is what makes them safe to
/// label with; status *messages* never are. Shared so every service
/// labels the same failure the same way — a dashboard comparing a
/// client's view of an error against the router's should not have to
/// translate between two spellings. Callers that classify errors which
/// may carry no status at all complete the vocabulary with
/// [`NON_STATUS`].
pub fn code_as_str(code: tonic::Code) -> &'static str {
    use tonic::Code;
    match code {
        Code::Ok => "ok",
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::InvalidArgument => "invalid_argument",
        Code::DeadlineExceeded => "deadline_exceeded",
        Code::NotFound => "not_found",
        Code::AlreadyExists => "already_exists",
        Code::PermissionDenied => "permission_denied",
        Code::ResourceExhausted => "resource_exhausted",
        Code::FailedPrecondition => "failed_precondition",
        Code::Aborted => "aborted",
        Code::OutOfRange => "out_of_range",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data_loss",
        Code::Unauthenticated => "unauthenticated",
    }
}

const MAX_HEADER_TAG_LEN: usize = 128;

fn is_safe_tag_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '/' | '_' | '-' | ':' | '.')
}

fn sanitize_header_tag(raw: &str) -> &str {
    let s = if raw.len() > MAX_HEADER_TAG_LEN {
        &raw[..MAX_HEADER_TAG_LEN]
    } else {
        raw
    };
    if s.chars().all(is_safe_tag_char) {
        s
    } else {
        "unknown"
    }
}

fn extract_sanitized_header<B>(request: &Request<B>, header: &str) -> Arc<str> {
    request
        .headers()
        .get(header)
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.is_empty())
        .map(sanitize_header_tag)
        .unwrap_or("unknown")
        .into()
}

fn extract_client_name<B>(request: &Request<B>) -> Arc<str> {
    extract_sanitized_header(request, CLIENT_NAME_HEADER)
}

fn extract_caller_tag<B>(request: &Request<B>) -> Arc<str> {
    extract_sanitized_header(request, CALLER_TAG_HEADER)
}

// ============================================================
// Connection tracking
// ============================================================

/// Drop guard that decrements the server connection gauge.
struct ConnectionGuard;

impl Drop for ConnectionGuard {
    fn drop(&mut self) {
        gauge!("grpc_server_connections").decrement(1.0);
    }
}

/// A TCP stream wrapper that tracks active gRPC server connections via a gauge.
///
/// Increments `grpc_server_connections` on creation, decrements on drop.
#[pin_project]
pub struct TrackedTcpStream {
    #[pin]
    inner: TcpStream,
    _guard: ConnectionGuard,
}

impl TrackedTcpStream {
    fn new(inner: TcpStream) -> Self {
        // Disable Nagle's algorithm to prevent ~40ms tail latency from the
        // Nagle + delayed-ACK interaction on gRPC request-response exchanges.
        if let Err(e) = inner.set_nodelay(true) {
            tracing::warn!("failed to set TCP_NODELAY on accepted socket: {e}");
        }
        gauge!("grpc_server_connections").increment(1.0);
        Self {
            inner,
            _guard: ConnectionGuard,
        }
    }
}

impl AsyncRead for TrackedTcpStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        self.project().inner.poll_read(cx, buf)
    }
}

impl AsyncWrite for TrackedTcpStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        self.project().inner.poll_write(cx, buf)
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        self.project().inner.poll_flush(cx)
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        self.project().inner.poll_shutdown(cx)
    }

    fn poll_write_vectored(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bufs: &[io::IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        self.project().inner.poll_write_vectored(cx, bufs)
    }

    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }
}

impl Connected for TrackedTcpStream {
    type ConnectInfo = <TcpStream as Connected>::ConnectInfo;

    fn connect_info(&self) -> Self::ConnectInfo {
        self.inner.connect_info()
    }
}

/// Creates a stream of connection-tracked TCP streams from a listener.
///
/// Each accepted connection increments `grpc_server_connections` and decrements
/// it when the connection is closed. Use with `tonic::transport::Server`'s
/// `serve_with_incoming_shutdown`.
///
/// The stream terminates on fatal accept errors (e.g. EMFILE, permission denied)
/// so the server shuts down cleanly rather than spinning on unrecoverable failures.
pub fn tracked_tcp_incoming(
    listener: TcpListener,
) -> impl futures::Stream<Item = Result<TrackedTcpStream, io::Error>> {
    unfold(listener, |listener| async move {
        match listener.accept().await {
            Ok((stream, _addr)) => Some((Ok(TrackedTcpStream::new(stream)), listener)),
            Err(e) if is_fatal_accept_error(&e) => None,
            Err(e) => Some((Err(e), listener)),
        }
    })
}

/// Drop guard that decrements a client-side in-flight gauge on drop,
/// ensuring cancellation-safety for outbound request tracking.
pub struct ClientInFlightGuard {
    pub backend: &'static str,
    client: Arc<str>,
}

impl ClientInFlightGuard {
    pub fn new(backend: &'static str) -> Self {
        let client = current_client_name();
        gauge!("personhog_router_client_requests_in_flight", "backend" => backend, "client" => client.clone())
            .increment(1.0);
        Self { backend, client }
    }
}

impl Drop for ClientInFlightGuard {
    fn drop(&mut self) {
        gauge!("personhog_router_client_requests_in_flight", "backend" => self.backend, "client" => self.client.clone())
            .decrement(1.0);
    }
}

/// Errors that indicate the listener cannot recover and the stream should terminate.
fn is_fatal_accept_error(e: &io::Error) -> bool {
    const EMFILE: i32 = 24;
    const ENFILE: i32 = 23;

    matches!(
        e.kind(),
        io::ErrorKind::PermissionDenied | io::ErrorKind::InvalidInput
    ) || matches!(e.raw_os_error(), Some(EMFILE) | Some(ENFILE))
}

// ============================================================
// Request metrics layer
// ============================================================

/// Header name for the replica's processing time, set on responses when
/// `emit_processing_time_header` is enabled. The router reads this to
/// compute per-request transport overhead without subtracting independent
/// histogram quantiles.
pub const PROCESSING_TIME_HEADER: &str = "x-processing-time-ms";

/// Response header set by [`AsyncGzipLayer`] with the total gzip layer
/// overhead in milliseconds (body collection + compression). The router
/// subtracts this alongside `PROCESSING_TIME_HEADER` to isolate true
/// network RTT.
pub const GZIP_OVERHEAD_HEADER: &str = "x-gzip-overhead-ms";

/// Tower layer that instruments gRPC requests with timing and concurrency metrics.
///
/// Records:
/// - `grpc_server_requests_total` - counter with method and client labels
/// - `grpc_server_request_duration_ms` - histogram with method and client labels
/// - `grpc_server_requests_in_flight` - gauge with method and client labels
///
/// Also sets the `CLIENT_NAME` task-local so downstream code can read
/// the client name via `current_client_name()`.
#[derive(Clone, Default)]
pub struct GrpcMetricsLayer {
    emit_processing_time_header: bool,
}

impl GrpcMetricsLayer {
    pub fn with_processing_time_header(self) -> Self {
        Self {
            emit_processing_time_header: true,
        }
    }
}

impl<S> Layer<S> for GrpcMetricsLayer {
    type Service = GrpcMetricsService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcMetricsService {
            inner: service,
            emit_processing_time_header: self.emit_processing_time_header,
        }
    }
}

#[derive(Clone)]
pub struct GrpcMetricsService<S> {
    inner: S,
    emit_processing_time_header: bool,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcMetricsService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone + Send + 'static,
    S::Future: Send,
    S::Error: Send,
    ReqBody: Send + 'static,
    ResBody: Send + 'static,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcMetricsFuture<S::Future>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        let method = extract_grpc_method(request.uri().path());
        let client = extract_client_name(&request);
        let caller_tag = extract_caller_tag(&request);
        gauge!("grpc_server_requests_in_flight", "method" => method.clone(), "client" => client.clone())
            .increment(1.0);

        let start = Instant::now();
        // Call inner inside all scopes so any synchronous work in call()
        // sees CLIENT_NAME, CALLER_TAG, and METHOD_NAME.
        let inner = CLIENT_NAME.sync_scope(client.clone(), || {
            CALLER_TAG.sync_scope(caller_tag.clone(), || {
                METHOD_NAME.sync_scope(method.clone(), || self.inner.call(request))
            })
        });

        GrpcMetricsFuture {
            inner: CLIENT_NAME.scope(
                client.clone(),
                CALLER_TAG.scope(caller_tag, METHOD_NAME.scope(method.clone(), inner)),
            ),
            method,
            client,
            start,
            emit_processing_time_header: self.emit_processing_time_header,
        }
    }
}

/// Future returned by [`GrpcMetricsService`].
///
/// Wraps the inner service future with task-local client name, caller tag,
/// and method name propagation, and records request metrics (counter,
/// histogram, in-flight gauge) on completion or cancellation. Lives inline
/// in the caller's async state machine — no heap allocation or dynamic dispatch.
#[pin_project(PinnedDrop)]
#[allow(clippy::type_complexity)]
pub struct GrpcMetricsFuture<F> {
    #[pin]
    inner: TaskLocalFuture<Arc<str>, TaskLocalFuture<Arc<str>, TaskLocalFuture<Arc<str>, F>>>,
    method: Arc<str>,
    client: Arc<str>,
    start: Instant,
    emit_processing_time_header: bool,
}

impl<F, ResBody, E> Future for GrpcMetricsFuture<F>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        match this.inner.poll(cx) {
            Poll::Ready(mut result) => {
                let duration_ms = this.start.elapsed().as_secs_f64() * 1000.0;
                counter!("grpc_server_requests_total",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .increment(1);
                histogram!("grpc_server_request_duration_ms",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .record(duration_ms);

                if *this.emit_processing_time_header {
                    if let Ok(ref mut response) = result {
                        if let Ok(hv) = HeaderValue::from_str(&format!("{duration_ms:.3}")) {
                            response.headers_mut().insert(PROCESSING_TIME_HEADER, hv);
                        }
                    }
                }

                Poll::Ready(result)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

/// Decrement the in-flight gauge when the future is dropped (on both
/// normal completion and cancellation), matching the original
/// `InFlightGuard` behavior.
#[pinned_drop]
impl<F> PinnedDrop for GrpcMetricsFuture<F> {
    fn drop(self: Pin<&mut Self>) {
        let this = self.project();
        gauge!("grpc_server_requests_in_flight",
            "method" => this.method.clone(),
            "client" => this.client.clone())
        .decrement(1.0);
    }
}

// ============================================================
// Load shedding layer
// ============================================================

/// Tower layer that sheds gRPC requests when the server is at capacity.
///
/// A request that finds no permit is refused with `x-not-applied`, so the
/// caller knows nothing ran. [`with_wait`](Self::with_wait) lets it wait a
/// bounded time first, so a sub-second burst shows up as latency rather
/// than refusals. When `max_requests` is 0, the layer is a pass-through.
#[derive(Clone)]
pub struct GrpcLoadShedLayer {
    max_requests: usize,
    permits: Arc<Semaphore>,
    wait_for_slot: Duration,
    max_waiters: usize,
    waiters: Arc<AtomicUsize>,
    grpc_status: HeaderValue,
}

impl GrpcLoadShedLayer {
    pub fn new(max_requests: usize) -> Self {
        Self {
            max_requests,
            permits: Arc::new(Semaphore::new(max_requests)),
            wait_for_slot: Duration::ZERO,
            max_waiters: max_requests,
            waiters: Arc::new(AtomicUsize::new(0)),
            grpc_status: grpc_status_header(tonic::Code::Unavailable),
        }
    }

    pub fn with_code(mut self, code: tonic::Code) -> Self {
        self.grpc_status = grpc_status_header(code);
        self
    }

    /// Past `max_waiters` queued requests the pod sheds on arrival again:
    /// a deep queue is the signal that the overload is not a burst, and
    /// shedding late only holds the stream and body longer for the same
    /// answer. `max_waiters` of 0 means `max_requests`.
    pub fn with_wait(mut self, wait_for_slot: Duration, max_waiters: usize) -> Self {
        self.wait_for_slot = wait_for_slot;
        self.max_waiters = if max_waiters == 0 {
            self.max_requests
        } else {
            max_waiters
        };
        self
    }
}

fn grpc_status_header(code: tonic::Code) -> HeaderValue {
    HeaderValue::from(code as i32)
}

impl<S> Layer<S> for GrpcLoadShedLayer {
    type Service = GrpcLoadShedService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcLoadShedService {
            inner: service,
            max_requests: self.max_requests,
            permits: self.permits.clone(),
            wait_for_slot: self.wait_for_slot,
            max_waiters: self.max_waiters,
            waiters: self.waiters.clone(),
            grpc_status: self.grpc_status.clone(),
        }
    }
}

#[derive(Clone)]
pub struct GrpcLoadShedService<S> {
    inner: S,
    max_requests: usize,
    permits: Arc<Semaphore>,
    wait_for_slot: Duration,
    max_waiters: usize,
    waiters: Arc<AtomicUsize>,
    grpc_status: HeaderValue,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ShedReason {
    NoWait,
    QueueFull,
    WaitTimeout,
}

impl ShedReason {
    fn as_str(self) -> &'static str {
        match self {
            ShedReason::NoWait => "no_wait",
            ShedReason::QueueFull => "queue_full",
            ShedReason::WaitTimeout => "wait_timeout",
        }
    }
}

fn record_shed(method: Arc<str>, client: Arc<str>, reason: ShedReason) {
    counter!("grpc_server_load_shed_total",
        "method" => method,
        "client" => client,
        "reason" => reason.as_str(),
    )
    .increment(1);
}

fn shed_response<ResBody: Default>(grpc_status: &HeaderValue) -> Response<ResBody> {
    Response::builder()
        .status(200)
        .header("content-type", "application/grpc")
        .header("grpc-status", grpc_status.clone())
        .header("grpc-message", "Server at capacity")
        .header(NOT_APPLIED_HEADER, "load_shed")
        .body(ResBody::default())
        .unwrap()
}

/// Holds one waiter slot; dropping it releases the slot, so a client that
/// disconnects mid-wait cannot leak one.
pub struct WaiterSlot {
    waiters: Arc<AtomicUsize>,
}

impl Drop for WaiterSlot {
    fn drop(&mut self) {
        self.waiters.fetch_sub(1, Ordering::Relaxed);
        gauge!("grpc_server_admission_waiters").decrement(1.0);
    }
}

type AcquireFuture = Pin<
    Box<dyn Future<Output = Result<Result<OwnedSemaphorePermit, AcquireError>, Elapsed>> + Send>,
>;

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcLoadShedService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone,
    ResBody: Default,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcLoadShedFuture<S, ReqBody, ResBody>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        if self.max_requests == 0 {
            return GrpcLoadShedFuture::Inner {
                inner: self.inner.call(request),
                permit: None,
            };
        }

        if let Ok(permit) = self.permits.clone().try_acquire_owned() {
            return GrpcLoadShedFuture::Inner {
                inner: self.inner.call(request),
                permit: Some(permit),
            };
        }

        let client = extract_client_name(&request);
        let method = extract_grpc_method(request.uri().path());

        if self.wait_for_slot.is_zero() {
            record_shed(method, client, ShedReason::NoWait);
            return GrpcLoadShedFuture::Shed {
                response: Some(shed_response(&self.grpc_status)),
            };
        }

        if self.waiters.fetch_add(1, Ordering::Relaxed) >= self.max_waiters {
            self.waiters.fetch_sub(1, Ordering::Relaxed);
            record_shed(method, client, ShedReason::QueueFull);
            return GrpcLoadShedFuture::Shed {
                response: Some(shed_response(&self.grpc_status)),
            };
        }
        gauge!("grpc_server_admission_waiters").increment(1.0);

        GrpcLoadShedFuture::Waiting {
            acquire: Box::pin(tokio::time::timeout(
                self.wait_for_slot,
                self.permits.clone().acquire_owned(),
            )),
            slot: Some(WaiterSlot {
                waiters: self.waiters.clone(),
            }),
            request: Some(request),
            service: Some(self.inner.clone()),
            method,
            client,
            started: Instant::now(),
            grpc_status: self.grpc_status.clone(),
        }
    }
}

/// The permit and the `WaiterSlot` release on drop, on completion and on
/// cancellation alike, which keeps the counts correct under client
/// disconnects.
#[pin_project(project = GrpcLoadShedFutureProj)]
pub enum GrpcLoadShedFuture<S, ReqBody, ResBody>
where
    S: Service<Request<ReqBody>>,
{
    Shed {
        response: Option<Response<ResBody>>,
    },
    Inner {
        #[pin]
        inner: S::Future,
        permit: Option<OwnedSemaphorePermit>,
    },
    Waiting {
        acquire: AcquireFuture,
        slot: Option<WaiterSlot>,
        request: Option<Request<ReqBody>>,
        service: Option<S>,
        method: Arc<str>,
        client: Arc<str>,
        started: Instant,
        grpc_status: HeaderValue,
    },
    /// `Oneshot` polls the clone's readiness, which `poll_ready` never
    /// covered.
    Admitted {
        #[pin]
        inner: Oneshot<S, Request<ReqBody>>,
        permit: OwnedSemaphorePermit,
    },
}

impl<S, ReqBody, ResBody> Future for GrpcLoadShedFuture<S, ReqBody, ResBody>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>>,
    ResBody: Default,
{
    type Output = Result<Response<ResBody>, S::Error>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let admitted = match self.as_mut().project() {
            GrpcLoadShedFutureProj::Shed { response } => {
                return Poll::Ready(Ok(response.take().unwrap()))
            }
            GrpcLoadShedFutureProj::Inner { inner, .. } => return inner.poll(cx),
            GrpcLoadShedFutureProj::Admitted { inner, .. } => return inner.poll(cx),
            GrpcLoadShedFutureProj::Waiting {
                acquire,
                slot,
                request,
                service,
                method,
                client,
                started,
                grpc_status,
            } => {
                let outcome = match acquire.as_mut().poll(cx) {
                    Poll::Pending => return Poll::Pending,
                    Poll::Ready(outcome) => outcome,
                };
                // Release the queue slot at the decision, not when hyper
                // drops the future.
                drop(slot.take());
                let waited_ms = started.elapsed().as_secs_f64() * 1000.0;
                match outcome {
                    Ok(Ok(permit)) => {
                        histogram!("grpc_server_admission_wait_ms",
                            "method" => method.clone(),
                            "client" => client.clone(),
                            "outcome" => "admitted",
                        )
                        .record(waited_ms);
                        let inner = service.take().unwrap().oneshot(request.take().unwrap());
                        GrpcLoadShedFuture::Admitted { inner, permit }
                    }
                    // The semaphore is never closed, so `Ok(Err)` cannot
                    // happen; shed rather than panic in a server path.
                    Ok(Err(_)) | Err(_) => {
                        histogram!("grpc_server_admission_wait_ms",
                            "method" => method.clone(),
                            "client" => client.clone(),
                            "outcome" => "shed",
                        )
                        .record(waited_ms);
                        record_shed(method.clone(), client.clone(), ShedReason::WaitTimeout);
                        return Poll::Ready(Ok(shed_response(grpc_status)));
                    }
                }
            }
        };
        self.set(admitted);
        self.poll(cx)
    }
}

/// Extract the gRPC method name from the URI path.
///
/// gRPC paths look like: `/package.Service/MethodName`
/// We extract just the method name part for cleaner metrics.
///
/// Cardinality is bounded because tonic rejects requests to unknown methods
/// before they reach this middleware.
fn extract_grpc_method(path: &str) -> Arc<str> {
    path.rsplit_once('/')
        .map(|(_, method)| method)
        .filter(|m| !m.is_empty())
        .unwrap_or("unknown")
        .into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::poll;
    use std::convert::Infallible;
    use std::task::{Context, Poll};
    use tower::Layer;

    fn grpc_request(path: &str) -> Request<()> {
        Request::builder().uri(path).body(()).unwrap()
    }

    /// Minimal service that immediately returns an empty 200 response.
    #[derive(Clone)]
    struct OkService;

    impl Service<Request<()>> for OkService {
        type Response = Response<()>;
        type Error = Infallible;
        type Future = std::future::Ready<Result<Response<()>, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _req: Request<()>) -> Self::Future {
            std::future::ready(Ok(Response::new(())))
        }
    }

    /// Service that never resolves — useful for testing cancellation/drop.
    #[derive(Clone)]
    struct PendingService;

    impl Service<Request<()>> for PendingService {
        type Response = Response<()>;
        type Error = Infallible;
        type Future = std::future::Pending<Result<Response<()>, Infallible>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _req: Request<()>) -> Self::Future {
            std::future::pending()
        }
    }

    fn hold_pod_full(layer: &GrpcLoadShedLayer) -> Vec<GrpcLoadShedFuture<PendingService, (), ()>> {
        let mut svc = layer.layer(PendingService);
        (0..layer.max_requests)
            .map(|_| svc.call(grpc_request("/pkg.Svc/Held")))
            .collect()
    }

    fn waiting_layer(max_waiters: usize) -> GrpcLoadShedLayer {
        GrpcLoadShedLayer::new(1).with_wait(Duration::from_millis(500), max_waiters)
    }

    fn assert_shed(resp: &Response<()>, expected_status: &str) {
        assert_eq!(resp.headers().get("grpc-status").unwrap(), expected_status);
        assert_eq!(
            resp.headers().get("grpc-message").unwrap(),
            "Server at capacity"
        );
        assert_eq!(resp.headers().get(NOT_APPLIED_HEADER).unwrap(), "load_shed");
    }

    fn assert_admitted(resp: &Response<()>) {
        assert_eq!(resp.status(), 200);
        assert!(resp.headers().get("grpc-status").is_none());
    }

    #[tokio::test]
    async fn passthrough_when_disabled() {
        let layer = GrpcLoadShedLayer::new(0);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);
    }

    #[tokio::test]
    async fn allows_requests_under_limit() {
        let layer = GrpcLoadShedLayer::new(2);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);
    }

    #[tokio::test]
    async fn sheds_at_capacity() {
        for (layer, expected_status) in [
            (GrpcLoadShedLayer::new(2), "14"),
            (
                GrpcLoadShedLayer::new(2).with_code(tonic::Code::ResourceExhausted),
                "8",
            ),
        ] {
            let held = hold_pod_full(&layer);
            let mut svc = layer.layer(OkService);

            let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
            assert_shed(&resp, expected_status);
            assert_eq!(layer.permits.available_permits(), 0);
            drop(held);
            assert_eq!(layer.permits.available_permits(), 2);
        }
    }

    #[tokio::test]
    async fn permit_returns_on_completion() {
        let layer = GrpcLoadShedLayer::new(10);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_admitted(&resp);

        assert_eq!(layer.permits.available_permits(), 10);
    }

    #[tokio::test]
    async fn permit_returns_on_drop() {
        let layer = GrpcLoadShedLayer::new(10);
        let mut svc = layer.layer(PendingService);

        let future = svc.call(grpc_request("/pkg.Svc/Method"));
        assert_eq!(layer.permits.available_permits(), 9);

        // Drop without polling to completion — simulates request cancellation
        drop(future);
        assert_eq!(layer.permits.available_permits(), 10);
    }

    #[tokio::test(start_paused = true)]
    async fn waits_for_a_permit_that_frees_inside_the_window() {
        let layer = waiting_layer(4);
        let mut held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let waiter = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(waiter);
        assert!(poll!(waiter.as_mut()).is_pending());
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);

        held.pop();
        let resp = waiter.await.unwrap();
        assert_admitted(&resp);
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn sheds_after_the_wait_window() {
        for (layer, expected_status) in [
            (waiting_layer(4), "14"),
            (
                waiting_layer(4).with_code(tonic::Code::ResourceExhausted),
                "8",
            ),
        ] {
            let _held = hold_pod_full(&layer);
            let mut svc = layer.layer(OkService);

            let start = tokio::time::Instant::now();
            let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
            assert!(start.elapsed() >= Duration::from_millis(500));
            assert_shed(&resp, expected_status);
            assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn sheds_immediately_when_the_queue_is_full() {
        let layer = waiting_layer(1);
        let _held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(first);
        assert!(poll!(first.as_mut()).is_pending());

        let start = tokio::time::Instant::now();
        let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
        assert_eq!(start.elapsed(), Duration::ZERO);
        assert_shed(&resp, "14");
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn dropped_waiter_frees_its_queue_slot() {
        let layer = waiting_layer(1);
        let _held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        {
            let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
            tokio::pin!(first);
            assert!(poll!(first.as_mut()).is_pending());
            assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
        }
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 0);

        let second = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(second);
        assert!(poll!(second.as_mut()).is_pending());
        assert_eq!(layer.waiters.load(Ordering::Relaxed), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn earliest_waiter_takes_the_freed_permit() {
        let layer = waiting_layer(4);
        let mut held = hold_pod_full(&layer);
        let mut svc = layer.layer(OkService);

        let first = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(first);
        let second = svc.call(grpc_request("/pkg.Svc/GetPerson"));
        tokio::pin!(second);
        assert!(poll!(first.as_mut()).is_pending());
        assert!(poll!(second.as_mut()).is_pending());

        held.pop();
        assert!(poll!(second.as_mut()).is_pending());
        match poll!(first.as_mut()) {
            Poll::Ready(Ok(resp)) => assert_admitted(&resp),
            other => panic!("first waiter not admitted: {other:?}"),
        }
    }

    #[test]
    fn extract_method_from_grpc_path() {
        assert_eq!(
            &*extract_grpc_method("/package.Service/GetPerson"),
            "GetPerson"
        );
        assert_eq!(&*extract_grpc_method("/a.b.c/Method"), "Method");
        assert_eq!(&*extract_grpc_method("/"), "unknown");
        assert_eq!(&*extract_grpc_method(""), "unknown");
    }

    #[test]
    fn extract_caller_tag_from_headers() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "api/feature-flags")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "api/feature-flags");
    }

    #[test]
    fn extract_caller_tag_defaults_to_unknown() {
        let req = Request::builder().uri("/pkg.Svc/Method").body(()).unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn extract_caller_tag_treats_empty_as_unknown() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn current_caller_tag_defaults_outside_scope() {
        assert_eq!(&*current_caller_tag(), "unknown");
    }

    #[test]
    fn extract_caller_tag_truncates_long_value() {
        let long_tag = "a".repeat(200);
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", &long_tag)
            .body(())
            .unwrap();
        assert_eq!(extract_caller_tag(&req).len(), MAX_HEADER_TAG_LEN);
    }

    #[test]
    fn extract_caller_tag_rejects_unsafe_chars() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "bad tag with spaces!")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn extract_client_name_truncates_long_value() {
        let long_name = "b".repeat(200);
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-client-name", &long_name)
            .body(())
            .unwrap();
        assert_eq!(extract_client_name(&req).len(), MAX_HEADER_TAG_LEN);
    }

    #[test]
    fn extract_client_name_rejects_unsafe_chars() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-client-name", "bad name!")
            .body(())
            .unwrap();
        assert_eq!(&*extract_client_name(&req), "unknown");
    }

    #[test]
    fn sanitize_allows_valid_tag_chars() {
        assert_eq!(
            sanitize_header_tag("api/feature-flags"),
            "api/feature-flags"
        );
        assert_eq!(
            sanitize_header_tag("celery/calculate_cohort_ch"),
            "celery/calculate_cohort_ch"
        );
        assert_eq!(
            sanitize_header_tag("posthog-django-web"),
            "posthog-django-web"
        );
        assert_eq!(sanitize_header_tag("some:tag.v1"), "some:tag.v1");
    }
}
