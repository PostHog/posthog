use std::time::Duration;

use axum::{routing::get, Router};
use cymbal::config::Config as CymbalConfig;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use cymbal_resolution::app_context::AppContext;
use cymbal_resolution::config::Config;
use cymbal_resolution::service::{CymbalResolutionService, ServiceConfig};
use envconfig::Envconfig;
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    init_tracing();

    let config = Config::init_from_env().expect("Invalid cymbal-resolution configuration");
    let cymbal_config = CymbalConfig::init_with_defaults().expect("Invalid cymbal configuration");

    tracing::info!("Starting cymbal-resolution service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Metrics port: {}", config.metrics_port);

    let app_context = AppContext::from_config(config.clone(), &cymbal_config)
        .await
        .expect("Failed to build cymbal-resolution app context");

    spawn_metrics_server(config.metrics_port);

    let service_config = ServiceConfig::from(&config);
    let service = CymbalResolutionService::new(
        app_context.symbol_resolver.clone(),
        app_context.symbol_resolution_limiter.clone(),
        app_context.item_limiter.clone(),
        app_context.service_instance_id.clone(),
        config.max_item_concurrency as u32,
        service_config,
    );

    let listener = tokio::net::TcpListener::bind(config.grpc_address).await?;
    let incoming = tracked_tcp_incoming(listener);

    tracing::info!("gRPC server listening on {}", config.grpc_address);

    Server::builder()
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(20)))
        .layer(GrpcMetricsLayer::default().with_processing_time_header())
        .layer(GrpcLoadShedLayer::new(config.max_concurrent_requests))
        // The cymbal client chunks grouped ResolveRequests by item count
        // (`CYMBAL_REMOTE_RESOLUTION_MAX_BATCH_ITEMS`). The server relies on
        // tonic's 4 MiB per-message default; an oversized chunk (single event
        // with many large exceptions) surfaces as `InvalidArgument`. Future:
        // signal "send smaller" back via `LoadEvent`.
        .add_service(CymbalResolutionServer::new(service))
        .serve_with_incoming(incoming)
        .await?;

    Ok(())
}

fn init_tracing() {
    let log_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true);

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
}

fn spawn_metrics_server(port: u16) {
    tokio::spawn(async move {
        let router = Router::new()
            .route("/_liveness", get(|| async { "ok" }))
            .route("/_readiness", get(|| async { "ok" }));
        let router = common_metrics::setup_metrics_routes_for_product(router, "cymbal-resolution");

        let bind = format!("0.0.0.0:{port}");
        tracing::info!("Metrics server listening on {}", bind);
        if let Err(e) = common_metrics::serve(router, &bind).await {
            tracing::error!("Metrics server error: {e}");
        }
    });
}
