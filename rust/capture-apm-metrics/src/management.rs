//! The management plane: probes and `/metrics` on a runtime the data plane
//! never shares.

use std::net::SocketAddr;

use axum::Router;
use tokio::net::TcpListener;
use tokio::runtime::{Builder, Handle, Runtime};
use tokio::task::JoinHandle;
use tracing::error;

/// Build the runtime that serves the probes and `/metrics`. It owns one OS
/// thread that the data plane never uses. When request decoding saturates the
/// data-plane workers, the kernel still schedules this thread, so the probes
/// answer inside the kubelet timeout.
pub fn build_runtime() -> Runtime {
    Builder::new_multi_thread()
        .worker_threads(1)
        .thread_name("management")
        .enable_all()
        .build()
        .expect("failed to build management runtime")
}

/// Serve `router` on `listener` from the management runtime. The connection
/// tasks never wait behind the data-plane handlers. The handle resolves when
/// the server stops.
pub fn serve(runtime: &Handle, listener: TcpListener, router: Router) -> JoinHandle<()> {
    runtime.spawn(async move {
        if let Err(e) = axum::serve(
            listener,
            router.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .await
        {
            error!("Management server failed: {}", e);
        }
    })
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::sync::mpsc;
    use std::time::Duration;

    use axum::routing::get;

    use super::*;

    fn get_readiness(addr: SocketAddr) -> String {
        let mut stream = TcpStream::connect(addr).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        stream
            .write_all(b"GET /_readiness HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        response
    }

    /// A probe must answer while the only data-plane worker is held by
    /// synchronous work, as a large protobuf decode holds it in production.
    #[test]
    fn probe_answers_while_data_plane_worker_is_blocked() {
        let management = build_runtime();
        let listener = management
            .block_on(TcpListener::bind("127.0.0.1:0"))
            .unwrap();
        let addr = listener.local_addr().unwrap();
        let router = Router::new().route("/_readiness", get(|| async { "ok" }));
        let _server = serve(management.handle(), listener, router);

        let data_plane = Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()
            .unwrap();
        let (blocked_tx, blocked_rx) = mpsc::channel::<()>();
        let (release_tx, release_rx) = mpsc::channel::<()>();
        data_plane.spawn(async move {
            blocked_tx.send(()).unwrap();
            release_rx.recv().unwrap();
        });
        blocked_rx.recv().unwrap();

        // Confirm the worker is held: a second data-plane task does not run.
        let (ran_tx, ran_rx) = mpsc::channel::<()>();
        data_plane.spawn(async move {
            ran_tx.send(()).unwrap();
        });
        assert!(
            ran_rx.recv_timeout(Duration::from_millis(200)).is_err(),
            "data-plane worker was not blocked"
        );

        let response = get_readiness(addr);
        assert!(response.starts_with("HTTP/1.1 200"), "{response}");

        release_tx.send(()).unwrap();
        ran_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    }
}
