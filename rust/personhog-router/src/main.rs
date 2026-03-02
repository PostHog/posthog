use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use personhog_proto::personhog::service::v1::person_hog_service_server::PersonHogServiceServer;
use personhog_router::backend::ReplicaBackend;
use personhog_router::config::Config;
use personhog_router::middleware::GrpcMetricsLayer;
use personhog_router::router::PersonHogRouter;
use personhog_router::service::PersonHogRouterService;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

common_alloc::used!();

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
    tracing::info!(
        "Retry config: max_retries={}, initial_backoff={}ms, max_backoff={}ms",
        config.max_retries,
        config.initial_backoff_ms,
        config.max_backoff_ms
    );

    let mut manager = Manager::builder("personhog-router")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();

    let grpc_handle = manager.register(
        "grpc-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let metrics_handle = manager.register("metrics-server", ComponentOptions::new());

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let grpc_shutdown = manager.shutdown_signal();
    let metrics_shutdown = manager.shutdown_signal();

    let monitor_guard = manager.monitor_background();

    // Metrics/health HTTP server
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));
        let metrics_router = setup_metrics_routes(health_router);

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, metrics_router)
            .with_graceful_shutdown(metrics_shutdown)
            .await
            .expect("Metrics server error");
    });

    // Create backend connection to personhog-replica
    let replica_backend = ReplicaBackend::new(
        &config.replica_url,
        config.backend_timeout(),
        config.retry_config(),
    )
    .expect("Failed to create replica backend");

    // Create the router with the replica backend
    let router = PersonHogRouter::new(Arc::new(replica_backend));
    let service = PersonHogRouterService::new(Arc::new(router));
    let grpc_addr = config.grpc_address;

    tracing::info!("Starting gRPC server on {}", grpc_addr);

    tokio::spawn(async move {
        let _guard = grpc_handle.process_scope();
        if let Err(e) = Server::builder()
            .layer(GrpcMetricsLayer)
            .add_service(PersonHogServiceServer::new(service))
            .serve_with_shutdown(grpc_addr, grpc_shutdown)
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor_guard.wait().await?;
    Ok(())
}
