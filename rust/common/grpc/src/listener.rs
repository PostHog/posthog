//! A TCP listener whose accepted connections count in `grpc_server_connections`, for
//! `tonic::transport::Server::serve_with_incoming_shutdown`.

use std::future::Future;
use std::io;
use std::pin::Pin;
use std::task::{Context, Poll};

use futures::stream::unfold;
use metrics::gauge;
use pin_project::pin_project;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::{TcpListener, TcpStream};
use tokio_util::sync::CancellationToken;
use tonic::transport::server::Connected;

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
    tracked_tcp_incoming_until(listener, CancellationToken::new())
}

/// [`tracked_tcp_incoming`] that drops the listener when `shutdown` is cancelled.
/// A bound listener queues a late connection that nothing serves, so the client
/// waits out its deadline. Serve this stream with [`until_incoming_ends`].
pub fn tracked_tcp_incoming_until(
    listener: TcpListener,
    shutdown: CancellationToken,
) -> impl futures::Stream<Item = Result<TrackedTcpStream, io::Error>> {
    unfold((listener, shutdown), |(listener, shutdown)| async move {
        tokio::select! {
            biased;
            _ = shutdown.cancelled() => None,
            accepted = listener.accept() => match accepted {
                Ok((stream, _addr)) => {
                    Some((Ok(TrackedTcpStream::new(stream)), (listener, shutdown)))
                }
                Err(e) if is_fatal_accept_error(&e) => None,
                Err(e) => Some((Err(e), (listener, shutdown))),
            },
        }
    })
}

/// A shutdown signal that never fires, so the end of the stream stops tonic's
/// accept loop. Tonic selects at random between its signal and the stream, and
/// a signal win keeps the listener bound for the whole drain.
pub fn until_incoming_ends() -> impl Future<Output = ()> + Send + 'static {
    std::future::pending()
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

#[cfg(test)]
mod tests {
    use std::convert::Infallible;
    use std::sync::Arc;
    use std::time::Duration;

    use http::{Request, Response};
    use tonic::body::BoxBody;
    use tonic::server::NamedService;
    use tonic::transport::{Endpoint, Server};
    use tower::{Service, ServiceExt};

    use super::*;

    #[derive(Clone)]
    struct HeldRpcService {
        entered: Arc<tokio::sync::Notify>,
        release: CancellationToken,
    }

    impl NamedService for HeldRpcService {
        const NAME: &'static str = "test.Held";
    }

    impl Service<Request<BoxBody>> for HeldRpcService {
        type Response = Response<BoxBody>;
        type Error = Infallible;
        type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Infallible>> + Send>>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _req: Request<BoxBody>) -> Self::Future {
            let service = self.clone();
            Box::pin(async move {
                service.entered.notify_one();
                service.release.cancelled().await;
                Ok(Response::new(tonic::body::empty_body()))
            })
        }
    }

    #[tokio::test]
    async fn a_draining_server_refuses_connections_and_finishes_accepted_rpcs() {
        // Tonic picks its select branch at random, so one round can pass by luck.
        for _ in 0..16 {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let addr = listener.local_addr().unwrap();
            let shutdown = CancellationToken::new();
            let service = HeldRpcService {
                entered: Arc::new(tokio::sync::Notify::new()),
                release: CancellationToken::new(),
            };

            let server = tokio::spawn(
                Server::builder()
                    .add_service(service.clone())
                    .serve_with_incoming_shutdown(
                        tracked_tcp_incoming_until(listener, shutdown.clone()),
                        until_incoming_ends(),
                    ),
            );

            let mut channel = Endpoint::from_shared(format!("http://{addr}"))
                .unwrap()
                .connect()
                .await
                .unwrap();
            let request = Request::builder()
                .method("POST")
                .uri(format!("http://{addr}/test.Held/Call"))
                .body(tonic::body::empty_body())
                .unwrap();
            let held_rpc = tokio::spawn(channel.ready().await.unwrap().call(request));
            service.entered.notified().await;

            shutdown.cancel();
            tokio::time::timeout(Duration::from_secs(5), async {
                while TcpStream::connect(addr).await.is_ok() {
                    tokio::task::yield_now().await;
                }
            })
            .await
            .expect("the port must refuse connections during the drain");
            assert!(!server.is_finished());

            service.release.cancel();
            assert!(held_rpc.await.unwrap().is_ok());
            server.await.unwrap().unwrap();
        }
    }
}
