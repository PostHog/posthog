//! Serves `cymbal.path_resolution.v1`. See [`README.md`](./README.md) for the contract.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

use axum::{http::StatusCode, routing::get, Router};
use cymbal_proto::cymbal::path_resolution::v1::path_resolution_server::PathResolutionServer;
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tonic::transport::Server;
use tracing::{info, warn};

use crate::core::config::get_aws_config;
use crate::core::shutdown::wait_for_shutdown;
use crate::core::symbolication::symbol_store::{BlobClient, S3Client};

pub mod auth;
pub mod config;
pub mod file_index;
pub mod list_store;
pub mod matching;
pub mod service;

pub use config::PathResolutionConfig;

use auth::SharedSecretInterceptor;
use list_store::ListStore;
use service::PathResolutionService;

pub async fn serve(config: &PathResolutionConfig) -> Result<(), Box<dyn std::error::Error>> {
    let service_config = &config.service;
    info!("Starting cymbal-path-resolution service");
    info!("gRPC address: {}", service_config.grpc_address);
    info!("Metrics port: {}", service_config.metrics_port);

    let auth = SharedSecretInterceptor::from_list(&service_config.secrets);
    let s3 = aws_sdk_s3::Client::from_conf(get_aws_config(&config.resolver).await);
    let blob: Arc<dyn BlobClient> = Arc::new(S3Client::new(s3));
    blob.ping_bucket(&config.resolver.object_storage_bucket)
        .await?;
    let store = ListStore::new(blob, config.list_store());

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let draining = Arc::new(AtomicBool::new(false));
    let _shutdown_handle = spawn_shutdown_listener(
        shutdown_tx.clone(),
        draining.clone(),
        Duration::from_secs(service_config.drain_secs),
    );
    let metrics_handle =
        spawn_metrics_server(service_config.metrics_port, shutdown_rx.clone(), draining);

    let listener = tokio::net::TcpListener::bind(service_config.grpc_address).await?;
    let incoming = tracked_tcp_incoming(listener);
    info!("gRPC server listening on {}", service_config.grpc_address);

    let server_result = Server::builder()
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(20)))
        .layer(GrpcMetricsLayer::default().with_processing_time_header())
        .layer(GrpcLoadShedLayer::new(
            service_config.max_concurrent_requests,
        ))
        .add_service(PathResolutionServer::with_interceptor(
            PathResolutionService::new(store),
            move |request| auth.authenticate(request),
        ))
        .serve_with_incoming_shutdown(incoming, wait_for_shutdown(shutdown_rx))
        .await;

    let _ignored = shutdown_tx.send(true);
    if let Err(err) = metrics_handle.await {
        warn!(error = %err, "metrics server task failed during shutdown");
    }
    server_result?;
    Ok(())
}

fn spawn_metrics_server(
    port: u16,
    shutdown_rx: watch::Receiver<bool>,
    draining: Arc<AtomicBool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let router = Router::new()
            .route("/_liveness", get(|| async { "ok" }))
            .route("/_readiness", get(move || readiness(draining.clone())));
        let router =
            common_metrics::setup_metrics_routes_for_product(router, "cymbal-path-resolution");

        let bind = format!("0.0.0.0:{port}");
        info!("Metrics server listening on {}", bind);
        let listener = match tokio::net::TcpListener::bind(&bind).await {
            Ok(listener) => listener,
            Err(e) => {
                tracing::error!("Metrics server bind error: {e}");
                return;
            }
        };
        if let Err(e) = axum::serve(listener, router)
            .with_graceful_shutdown(wait_for_shutdown(shutdown_rx))
            .await
        {
            tracing::error!("Metrics server error: {e}");
        }
    })
}

fn spawn_shutdown_listener(
    shutdown_tx: watch::Sender<bool>,
    draining: Arc<AtomicBool>,
    drain_notice: Duration,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        shutdown_signal().await;
        info!(
            drain_notice_secs = drain_notice.as_secs(),
            "shutdown signal received, marking cymbal-path-resolution as draining",
        );
        // Failing readiness drops the pod from the headless service DNS, so callers stop picking
        // it before the server stops accepting requests.
        draining.store(true, Ordering::Relaxed);
        tokio::time::sleep(drain_notice).await;
        let _ignored = shutdown_tx.send(true);
    })
}

async fn readiness(draining: Arc<AtomicBool>) -> (StatusCode, &'static str) {
    if draining.load(Ordering::Relaxed) {
        return (StatusCode::SERVICE_UNAVAILABLE, "draining");
    }
    (StatusCode::OK, "ok")
}

#[cfg(unix)]
async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};

    let mut sigterm = signal(SignalKind::terminate()).expect("failed to listen for SIGTERM");
    tokio::select! {
        result = tokio::signal::ctrl_c() => {
            if let Err(err) = result {
                warn!(error = %err, "failed to listen for Ctrl+C");
            }
        }
        _ = sigterm.recv() => {}
    }
}

#[cfg(not(unix))]
async fn shutdown_signal() {
    if let Err(err) = tokio::signal::ctrl_c().await {
        warn!(error = %err, "failed to listen for Ctrl+C");
    }
}
