use std::sync::Arc;

use axum::{routing::get, Router};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use health::readiness_handler;
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogServiceServer;
use personhog_router::backend::ReplicaBackend;
use personhog_router::config::Config;
use personhog_router::middleware::GrpcMetricsLayer;
use personhog_router::router::PersonHogRouter;
use personhog_router::service::PersonHogRouterService;
use tokio::signal;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

async fn shutdown_signal() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");

    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    tracing::info!("Shutting down gracefully...");
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");

    // Initialize tracing
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

    tracing::info!("Starting personhog-router service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Replica URL: {}", config.replica_url);
    tracing::info!("Backend timeout: {}ms", config.backend_timeout_ms);
    tracing::info!("Metrics port: {}", config.metrics_port);

    // Start HTTP server for metrics and health checks
    let metrics_port = config.metrics_port;
    let health_router = Router::new()
        .route("/_readiness", get(readiness_handler))
        .route("/_liveness", get(|| async { "ok" }));
    let metrics_router = setup_metrics_routes(health_router);

    tokio::spawn(async move {
        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, metrics_router)
            .await
            .expect("Metrics server error");
    });

    // Create backend connection to personhog-replica
    let replica_backend = ReplicaBackend::new(&config.replica_url, config.backend_timeout())
        .expect("Failed to create replica backend");

    // Create the router with the replica backend
    let router = PersonHogRouter::new(Arc::new(replica_backend));
    let service = PersonHogRouterService::new(Arc::new(router));

    tracing::info!("Starting gRPC server on {}", config.grpc_address);

    Server::builder()
        .layer(GrpcMetricsLayer)
        .add_service(PersonHogServiceServer::new(service))
        .serve_with_shutdown(config.grpc_address, shutdown_signal())
        .await?;

    Ok(())
}
