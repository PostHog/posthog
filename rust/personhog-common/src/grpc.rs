use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use futures::stream::unfold;
use http::{HeaderValue, Request, Response};
use metrics::{counter, gauge, histogram};
use pin_project::{pin_project, pinned_drop};
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::{TcpListener, TcpStream};
use tokio::task::futures::TaskLocalFuture;
use tonic::transport::server::Connected;
use tower::{Layer, Service};

// ============================================================
// Client name extraction
// ============================================================

/// Header name for client identification in gRPC metadata.
const CLIENT_NAME_HEADER: &str = "x-client-name";

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
        let method: Arc<str> = Arc::from(extract_grpc_method(request.uri().path()));
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
/// Tracks in-flight requests with an atomic counter shared across all
/// connections on the pod. When the count exceeds `max_requests`,
/// immediately returns gRPC `UNAVAILABLE` so the router retries on
/// another pod. When `max_requests` is 0, the layer is a pass-through.
#[derive(Clone)]
pub struct GrpcLoadShedLayer {
    max_requests: usize,
    in_flight: Arc<AtomicUsize>,
}

impl GrpcLoadShedLayer {
    pub fn new(max_requests: usize) -> Self {
        Self {
            max_requests,
            in_flight: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl<S> Layer<S> for GrpcLoadShedLayer {
    type Service = GrpcLoadShedService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcLoadShedService {
            inner: service,
            max_requests: self.max_requests,
            in_flight: self.in_flight.clone(),
        }
    }
}

#[derive(Clone)]
pub struct GrpcLoadShedService<S> {
    inner: S,
    max_requests: usize,
    in_flight: Arc<AtomicUsize>,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcLoadShedService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>>,
    ResBody: Default,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcLoadShedFuture<S::Future, ResBody>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        if self.max_requests == 0 {
            return GrpcLoadShedFuture::Inner {
                inner: self.inner.call(request),
                in_flight: None,
            };
        }

        let current = self.in_flight.fetch_add(1, Ordering::Relaxed);
        if current >= self.max_requests {
            self.in_flight.fetch_sub(1, Ordering::Relaxed);

            let client = extract_client_name(&request);
            let method = extract_grpc_method(request.uri().path());
            counter!("grpc_server_load_shed_total",
                "method" => method,
                "client" => client,
            )
            .increment(1);

            let response = Response::builder()
                .status(200)
                .header("content-type", "application/grpc")
                .header("grpc-status", "14") // UNAVAILABLE
                .header("grpc-message", "Server at capacity")
                .body(ResBody::default())
                .unwrap();

            return GrpcLoadShedFuture::Shed {
                response: Some(response),
            };
        }

        GrpcLoadShedFuture::Inner {
            inner: self.inner.call(request),
            in_flight: Some(self.in_flight.clone()),
        }
    }
}

#[pin_project(project = GrpcLoadShedFutureProj, PinnedDrop)]
pub enum GrpcLoadShedFuture<F, ResBody> {
    Shed {
        response: Option<Response<ResBody>>,
    },
    Inner {
        #[pin]
        inner: F,
        in_flight: Option<Arc<AtomicUsize>>,
    },
}

impl<F, ResBody, E> Future for GrpcLoadShedFuture<F, ResBody>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match self.project() {
            GrpcLoadShedFutureProj::Shed { response } => Poll::Ready(Ok(response.take().unwrap())),
            GrpcLoadShedFutureProj::Inner { inner, .. } => inner.poll(cx),
        }
    }
}

#[pinned_drop]
impl<F, ResBody> PinnedDrop for GrpcLoadShedFuture<F, ResBody> {
    fn drop(self: Pin<&mut Self>) {
        if let GrpcLoadShedFutureProj::Inner {
            in_flight: Some(counter),
            ..
        } = self.project()
        {
            counter.fetch_sub(1, Ordering::Relaxed);
        }
    }
}

/// Extract the gRPC method name from the URI path.
///
/// gRPC paths look like: `/package.Service/MethodName`
/// We extract just the method name part for cleaner metrics.
///
/// Cardinality is bounded because tonic rejects requests to unknown methods
/// before they reach this middleware.
fn extract_grpc_method(path: &str) -> String {
    path.rsplit_once('/')
        .map(|(_, method)| method)
        .filter(|m| !m.is_empty())
        .unwrap_or("unknown")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::convert::Infallible;
    use std::sync::atomic::AtomicUsize;
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

    #[tokio::test]
    async fn passthrough_when_disabled() {
        let layer = GrpcLoadShedLayer::new(0);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_eq!(resp.status(), 200);
        assert!(resp.headers().get("grpc-status").is_none());
    }

    #[tokio::test]
    async fn allows_requests_under_limit() {
        let layer = GrpcLoadShedLayer::new(2);
        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert_eq!(resp.status(), 200);
        assert!(resp.headers().get("grpc-status").is_none());
    }

    #[tokio::test]
    async fn sheds_at_capacity() {
        let in_flight = Arc::new(AtomicUsize::new(0));
        let layer = GrpcLoadShedLayer {
            max_requests: 2,
            in_flight: in_flight.clone(),
        };
        in_flight.store(2, Ordering::Relaxed);

        let mut svc = layer.layer(OkService);

        let resp = svc.call(grpc_request("/pkg.Svc/GetPerson")).await.unwrap();
        assert_eq!(resp.headers().get("grpc-status").unwrap(), "14");
        assert_eq!(
            resp.headers().get("grpc-message").unwrap(),
            "Server at capacity"
        );
        // Shed path: increment then immediate decrement, net zero change
        assert_eq!(in_flight.load(Ordering::Relaxed), 2);
    }

    #[tokio::test]
    async fn counter_decrements_on_completion() {
        let in_flight = Arc::new(AtomicUsize::new(0));
        let layer = GrpcLoadShedLayer {
            max_requests: 10,
            in_flight: in_flight.clone(),
        };
        let mut svc = layer.layer(OkService);

        assert_eq!(in_flight.load(Ordering::Relaxed), 0);

        let resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();
        assert!(resp.headers().get("grpc-status").is_none());

        // Future completed and dropped — counter back to 0
        assert_eq!(in_flight.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn counter_decrements_on_drop() {
        let in_flight = Arc::new(AtomicUsize::new(0));
        let layer = GrpcLoadShedLayer {
            max_requests: 10,
            in_flight: in_flight.clone(),
        };
        let mut svc = layer.layer(PendingService);

        let future = svc.call(grpc_request("/pkg.Svc/Method"));
        assert_eq!(in_flight.load(Ordering::Relaxed), 1);

        // Drop without polling to completion — simulates request cancellation
        drop(future);
        assert_eq!(in_flight.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn shed_response_does_not_decrement_existing() {
        let in_flight = Arc::new(AtomicUsize::new(5));
        let layer = GrpcLoadShedLayer {
            max_requests: 5,
            in_flight: in_flight.clone(),
        };
        let mut svc = layer.layer(OkService);

        let _resp = svc.call(grpc_request("/pkg.Svc/Method")).await.unwrap();

        // Existing in-flight count unchanged after shed
        assert_eq!(in_flight.load(Ordering::Relaxed), 5);
    }

    #[test]
    fn extract_method_from_grpc_path() {
        assert_eq!(
            extract_grpc_method("/package.Service/GetPerson"),
            "GetPerson"
        );
        assert_eq!(extract_grpc_method("/a.b.c/Method"), "Method");
        assert_eq!(extract_grpc_method("/"), "unknown");
        assert_eq!(extract_grpc_method(""), "unknown");
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
