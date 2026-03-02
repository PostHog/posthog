use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplicaServer;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_replica::config::Config;
use personhog_replica::service::PersonHogReplicaService;
use personhog_replica::storage::postgres::PostgresStorage;

common_alloc::used!();

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

            // Create primary pool
            let primary_pool =
                get_pool_with_config(&config.primary_database_url, pool_config.clone())
                    .expect("Failed to create primary database pool");
            tracing::info!("Created primary database pool");

            // Create replica pool (uses primary URL if replica URL not configured)
            let replica_url = config.replica_database_url();
            let replica_pool = if replica_url == config.primary_database_url {
                tracing::info!("Replica URL not configured, using primary pool for both");
                primary_pool.clone()
            } else {
                let pool = get_pool_with_config(replica_url, pool_config)
                    .expect("Failed to create replica database pool");
                tracing::info!("Created separate replica database pool");
                pool
            };

            Arc::new(PostgresStorage::new(primary_pool, replica_pool))
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

    // Build lifecycle manager and register components
    let mut manager = Manager::builder("personhog-replica").build();

    let grpc_handle = manager.register(
        "grpc_server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let grpc_shutdown = manager.shutdown_signal();
    let metrics_shutdown = manager.shutdown_signal();

    let monitor = manager.monitor_background();

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
        let router = setup_metrics_routes(health_router);

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(metrics_shutdown)
            .await
            .expect("Metrics server error");
    });

    // gRPC server
    let storage = create_storage(&config).await;
    let service = PersonHogReplicaService::new(storage);
    let grpc_addr = config.grpc_address;

    tracing::info!("Starting gRPC server on {}", grpc_addr);

    tokio::spawn(async move {
        let _guard = grpc_handle.process_scope();
        if let Err(e) = Server::builder()
            .add_service(PersonHogReplicaServer::new(service))
            .serve_with_shutdown(grpc_addr, grpc_shutdown)
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor.wait().await?;

    Ok(())
}
