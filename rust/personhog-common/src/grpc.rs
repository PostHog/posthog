use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use futures::stream::unfold;
use http::{Request, Response};
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

tokio::task_local! {
    /// Per-request client name, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_client_name()`.
    pub static CLIENT_NAME: Arc<str>;
}

/// Get the current client name from the task-local, or `"unknown"` if not set.
/// Returns `Arc<str>` so cloning is a cheap refcount bump rather than a
/// heap allocation + memcpy on every call.
pub fn current_client_name() -> Arc<str> {
    CLIENT_NAME
        .try_with(|c| c.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Extract the client name from HTTP headers, defaulting to `"unknown"`.
fn extract_client_name<B>(request: &Request<B>) -> Arc<str> {
    request
        .headers()
        .get(CLIENT_NAME_HEADER)
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown")
        .into()
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
pub struct GrpcMetricsLayer;

impl<S> Layer<S> for GrpcMetricsLayer {
    type Service = GrpcMetricsService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcMetricsService { inner: service }
    }
}

#[derive(Clone)]
pub struct GrpcMetricsService<S> {
    inner: S,
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
        gauge!("grpc_server_requests_in_flight", "method" => method.clone(), "client" => client.clone())
            .increment(1.0);

        let start = Instant::now();
        // Call inner inside the scope so any synchronous work in call() sees CLIENT_NAME.
        let inner = CLIENT_NAME.sync_scope(client.clone(), || self.inner.call(request));

        GrpcMetricsFuture {
            inner: CLIENT_NAME.scope(client.clone(), inner),
            method,
            client,
            start,
        }
    }
}

/// Future returned by [`GrpcMetricsService`].
///
/// Wraps the inner service future with task-local client name propagation
/// and records request metrics (counter, histogram, in-flight gauge) on
/// completion or cancellation. Lives inline in the caller's async state
/// machine — no heap allocation or dynamic dispatch.
#[pin_project(PinnedDrop)]
pub struct GrpcMetricsFuture<F> {
    #[pin]
    inner: TaskLocalFuture<Arc<str>, F>,
    method: String,
    client: Arc<str>,
    start: Instant,
}

impl<F, ResBody, E> Future for GrpcMetricsFuture<F>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        match this.inner.poll(cx) {
            Poll::Ready(result) => {
                let duration_ms = this.start.elapsed().as_secs_f64() * 1000.0;
                counter!("grpc_server_requests_total",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .increment(1);
                histogram!("grpc_server_request_duration_ms",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .record(duration_ms);
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
