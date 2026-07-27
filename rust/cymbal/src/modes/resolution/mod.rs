//! Resolution mode: serves `cymbal.resolution.v1` over gRPC, exposing cymbal's
//! symbol-resolution stack to the remote-resolution client
//! (`crate::stages::resolution::remote`). It starts only the symbol resolver
//! (Postgres + object storage) — no Kafka, Redis, issue cache, or signals.
//! See [`README.md`](./README.md) for the wire contract and operations guide.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

use axum::{http::StatusCode, routing::get, Router};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tonic::transport::Server;
use tracing::{info, warn};

use crate::core::{config::ResolverConfig, shutdown::wait_for_shutdown};

pub mod app_context;
pub mod auth;
pub mod config;
pub mod load_monitor;
pub mod service;

pub use config::{Config, ResolutionConfig};

use app_context::ResolutionAppContext;
use auth::InternalApiSecretInterceptor;
use load_monitor::LoadMonitor;
use service::{CymbalResolutionService, ServiceConfig};

/// Boot the gRPC resolution service plus its metrics/health server and run
/// until shutdown. The `internal_api_secret` and symbol-resolution concurrency
/// come from the shared resolver config; everything else from the resolution
/// service config.
pub async fn serve(
    resolver: &ResolverConfig,
    service: &Config,
) -> Result<(), Box<dyn std::error::Error>> {
    let res = service;
    info!("Starting cymbal-resolution service");
    info!("gRPC address: {}", res.grpc_address);
    info!("Metrics port: {}", res.metrics_port);
    info!("Max concurrent requests: {}", res.max_concurrent_requests);

    let app_context = ResolutionAppContext::from_config(resolver, service).await?;

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let draining = Arc::new(AtomicBool::new(false));
    let drain_notice = Duration::from_millis(res.subscribe_tick_interval_ms).saturating_mul(2);
    let _shutdown_handle = spawn_shutdown_listener(
        shutdown_tx.clone(),
        draining.clone(),
        app_context.load_monitor.clone(),
        drain_notice,
    );
    let metrics_handle =
        spawn_metrics_server(res.metrics_port, shutdown_rx.clone(), draining.clone());

    let service_config = ServiceConfig::from(res);
    let service = CymbalResolutionService::new(
        app_context.symbol_resolver.clone(),
        app_context.symbol_resolution_limiter.clone(),
        app_context.load_monitor.clone(),
        app_context.service_instance_id.clone(),
        service_config,
        draining,
    );
    let internal_api_secret_fallbacks = resolver
        .internal_api_secret_fallbacks
        .split(',')
        .map(str::to_string)
        .collect::<Vec<_>>();
    let auth_interceptor = InternalApiSecretInterceptor::new(
        resolver.internal_api_secret.clone(),
        internal_api_secret_fallbacks,
    );

    let listener = tokio::net::TcpListener::bind(res.grpc_address).await?;
    let incoming = tracked_tcp_incoming(listener);

    info!("gRPC server listening on {}", res.grpc_address);

    let server_result = Server::builder()
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(20)))
        .layer(GrpcMetricsLayer::default().with_processing_time_header())
        .layer(GrpcLoadShedLayer::new(res.max_concurrent_requests))
        // The cymbal client submits exception-level ResolveItems. The server
        // relies on tonic's 4 MiB per-message default; an oversized item
        // surfaces as `InvalidArgument`. Future: signal "send smaller" back
        // via `LoadEvent`.
        .add_service(CymbalResolutionServer::with_interceptor(
            service,
            move |request| auth_interceptor.authenticate(request),
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
        let readiness_draining = draining.clone();
        let router = Router::new()
            .route("/_liveness", get(|| async { "ok" }))
            .route(
                "/_readiness",
                get(move || readiness(readiness_draining.clone())),
            );
        let router = common_metrics::setup_metrics_routes_for_product(router, "cymbal-resolution");

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
    load_monitor: LoadMonitor,
    drain_notice: Duration,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        shutdown_signal().await;
        info!(
            drain_notice_ms = drain_notice.as_millis() as u64,
            "shutdown signal received, marking cymbal-resolution as draining",
        );
        draining.store(true, Ordering::Relaxed);
        load_monitor.set_draining(true);
        tokio::time::sleep(drain_notice).await;
        info!("drain notice elapsed, stopping cymbal-resolution");
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
