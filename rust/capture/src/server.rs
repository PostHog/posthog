use std::io;
use std::net::SocketAddr;
use std::time::Duration;

use axum::extract::ConnectInfo;
use axum::Router;
use hyper_util::rt::{TokioExecutor, TokioIo, TokioTimer};
use hyper_util::server::conn::auto::Builder as AutoBuilder;
use hyper_util::server::graceful::GracefulShutdown;
use tokio::net::{TcpListener, TcpStream};
use tower::Service;
use tracing::{debug, error, info, warn};

use crate::setup::CaptureComponents;

// failsafe to prevent infinite loop if k8s endpoint removal is not working in prod
const MAX_DRAINABLE_CONNECTIONS: u64 = 1000;

const METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS: &str = "capture_hyper_accepted_connections";
const METRIC_CAPTURE_HYPER_ACCEPT_ERROR: &str = "capture_hyper_accept_error";
const METRIC_CAPTURE_HYPER_HEADER_READ_TIMEOUT: &str = "capture_hyper_header_read_timeout";

/// Returns true for errors that commonly occur during accept and don't indicate
/// a problem with the listener itself. These are silently retried without logging.
/// Matches axum::serve behavior.
fn is_connection_error(e: &io::Error) -> bool {
    matches!(
        e.kind(),
        io::ErrorKind::ConnectionRefused
            | io::ErrorKind::ConnectionAborted
            | io::ErrorKind::ConnectionReset
    )
}

/// Configures and spawns a connection handler for an accepted TCP connection.
/// Sets TCP_NODELAY, creates the hyper service with ConnectInfo, registers with
/// graceful shutdown, and spawns the connection handler task.
fn spawn_connection_handler(
    socket: TcpStream,
    remote_addr: SocketAddr,
    app: Router,
    builder: &AutoBuilder<TokioExecutor>,
    graceful: &GracefulShutdown,
    stage: &'static str,
) {
    if let Err(e) = socket.set_nodelay(true) {
        metrics::counter!(
            METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
            "err_type" => "set_tcp_nodelay",
            "stage" => stage,
        )
        .increment(1);
        warn!("Hyper accept loop ({stage}): error setting TCP_NODELAY: {e:#}");
    }

    let service = hyper::service::service_fn(move |req: hyper::Request<hyper::body::Incoming>| {
        let mut app = app.clone();
        let mut req = req.map(axum::body::Body::new);
        req.extensions_mut().insert(ConnectInfo(remote_addr));
        async move { app.call(req).await }
    });

    let conn = builder.serve_connection_with_upgrades(TokioIo::new(socket), service);
    let conn = graceful.watch(conn.into_owned());

    tokio::spawn(async move {
        if let Err(e) = conn.await {
            let err_str = e.to_string();
            let is_header_timeout = err_str.contains("timeout") && err_str.contains("header");

            if is_header_timeout {
                metrics::counter!(
                    METRIC_CAPTURE_HYPER_HEADER_READ_TIMEOUT,
                    "stage" => stage,
                )
                .increment(1);
                debug!("Hyper accept loop ({}): header read timeout: {}", stage, e);
            } else {
                metrics::counter!(
                    METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                    "err_type" => "conn_closed",
                    "stage" => stage,
                )
                .increment(1);
                debug!("Hyper accept loop ({}): connection closed: {}", stage, e);
            }
        }
    });
}

pub async fn serve(listener: TcpListener, components: CaptureComponents) {
    let CaptureComponents {
        app,
        server_handle,
        sink,
        http1_header_read_timeout_ms,
    } = components;

    // --- Server block with process_scope ---
    {
        let _scope = server_handle.process_scope();

        let mut builder = AutoBuilder::new(TokioExecutor::new());

        if let Some(timeout_ms) = http1_header_read_timeout_ms {
            builder
                .http1()
                .timer(TokioTimer::new())
                .header_read_timeout(Duration::from_millis(timeout_ms));
            info!("HTTP/1 header read timeout configured: {timeout_ms}ms");
        }

        let graceful = GracefulShutdown::new();

        loop {
            tokio::select! {
                result = listener.accept() => {
                    let (socket, remote_addr) = match result {
                        Ok(conn) => {
                            metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS, "stage" => "accept").increment(1);
                            conn
                        },
                        Err(e) => {
                            if is_connection_error(&e) {
                                metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                                    "err_type" => "connection",
                                    "stage" => "accept",
                                ).increment(1);
                                error!("Hyper accept loop: connection error: {e:#}");
                            } else {
                                metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                                    "err_type" => "resources",
                                    "stage" => "accept",
                                ).increment(1);
                                error!("Hyper accept loop: resource error: {e:#}");
                                tokio::time::sleep(Duration::from_secs(1)).await;
                            }
                            continue;
                        }
                    };

                    spawn_connection_handler(
                        socket,
                        remote_addr,
                        app.clone(),
                        &builder,
                        &graceful,
                        "accept",
                    );
                }
                _ = server_handle.shutdown_recv() => {
                    info!("Hyper accept loop: shutdown signal received");
                    break;
                }
            }
        }

        // Drain any connections already queued in the TCP accept backlog.
        // These connections are already established at the TCP level, so we should
        // serve them rather than let them see connection reset.
        info!("Hyper accept loop (draining): checking for queued connections...");
        let mut drained_count: u64 = 0;
        loop {
            if drained_count > MAX_DRAINABLE_CONNECTIONS {
                error!(
                    "Hyper accept loop (draining): reached loop limit of {} connections",
                    MAX_DRAINABLE_CONNECTIONS
                );
                break;
            }
            match tokio::time::timeout(Duration::from_millis(1), listener.accept()).await {
                Ok(Ok((socket, remote_addr))) => {
                    metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS, "stage" => "drain")
                        .increment(1);
                    drained_count += 1;

                    spawn_connection_handler(
                        socket,
                        remote_addr,
                        app.clone(),
                        &builder,
                        &graceful,
                        "drain",
                    );
                }
                Ok(Err(e)) => {
                    // Match axum::serve behavior:
                    // - Connection errors (reset, aborted, refused) are silently retried
                    // - Other errors (EMFILE, etc.) are logged; no backoff during drain
                    if is_connection_error(&e) {
                        metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                            "err_type" => "connection",
                            "stage" => "drain",
                        )
                        .increment(1);
                        error!(
                            error_type = "connection",
                            pause = "none",
                            "Hyper accept loop (draining): {e:#}"
                        );
                    } else {
                        metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                            "err_type" => "resources",
                            "stage" => "drain",
                        )
                        .increment(1);
                        error!(
                            error_type = "resources",
                            pause = "none",
                            "Hyper accept loop (draining): {e:#}"
                        );
                    }
                }
                Err(_) => {
                    break;
                }
            }
        }
        info!(
            drained_connections = drained_count,
            "Hyper accept loop (shutdown): drained queued connections"
        );

        info!(
            "Hyper accept loop (shutdown): waiting for in-flight request handlers to complete..."
        );
        graceful.shutdown().await;
        info!("Hyper accept loop (shutdown): graceful shutdown completed");

        // Flush the Kafka producer queue. Events from in-flight handlers may still
        // be in rdkafka's internal buffer. flush() blocks until the queue drains or
        // times out (default 30s from rdkafka config).
        info!("Flushing sink...");
        if let Err(e) = sink.flush() {
            error!("Sink flush failed: {e:#}");
        }
        info!("Sink flush complete");

        // _scope drops here -> ProcessScopeGuard signals WorkCompleted
    }
}
