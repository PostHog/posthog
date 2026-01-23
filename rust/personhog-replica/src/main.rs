use std::sync::Arc;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplicaServer;
use tokio::signal;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use health::readiness_handler;
use personhog_replica::config::Config;
use personhog_replica::service::PersonHogReplicaService;
use personhog_replica::storage::postgres::PostgresStorage;

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

async fn create_storage(config: &Config) -> Arc<PostgresStorage> {
    match config.storage_backend.as_str() {
        "postgres" => {
            let pool_config = PoolConfig {
                min_connections: config.min_pg_connections,
                max_connections: config.max_pg_connections,
                acquire_timeout: config.acquire_timeout(),
                idle_timeout: config.idle_timeout(),
                test_before_acquire: true,
                statement_timeout_ms: config.statement_timeout(),
            };

            let pool = get_pool_with_config(&config.database_url, pool_config)
                .await
                .expect("Failed to create database pool");

            tracing::info!("Created Postgres storage backend");
            Arc::new(PostgresStorage::new(pool))
        }
        other => {
            panic!("Unknown storage backend: {other}. Supported: postgres");
        }
    }
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

    tracing::info!("Starting personhog-replica service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("Storage backend: {}", config.storage_backend);

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

    let storage = create_storage(&config).await;
    let service = PersonHogReplicaService::new(storage);

    tracing::info!("Starting gRPC server on {}", config.grpc_address);

    Server::builder()
        .add_service(PersonHogReplicaServer::new(service))
        .serve_with_shutdown(config.grpc_address, shutdown_signal())
        .await?;

    Ok(())
}
