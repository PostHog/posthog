use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use personhog_common::{spawn_pool_monitor, MonitoredPool};
use personhog_proto::personhog::identity::v1::person_hog_identity_server::PersonHogIdentityServer;
use tonic::codec::CompressionEncoding;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_common::client::RouterClient;
use personhog_identity::config::Config;
use personhog_identity::service::PersonHogIdentityService;
use personhog_identity::storage::postgres::PostgresIdentityStorage;

common_alloc::used!();

fn create_storage(config: &Config) -> Arc<PostgresIdentityStorage> {
    let primary_pool_config = PoolConfig {
        min_connections: config.min_pg_connections,
        max_connections: config.max_pg_connections,
        acquire_timeout: config.acquire_timeout(),
        idle_timeout: config.idle_timeout(),
        test_before_acquire: false,
        statement_timeout_ms: config.statement_timeout(),
        pool_name: Some("primary".to_string()),
    };

    let primary_pool = get_pool_with_config(&config.primary_database_url, primary_pool_config)
        .expect("Failed to create primary database pool");
    tracing::info!("Created primary database pool");

    Arc::new(PostgresIdentityStorage::new(primary_pool))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");

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

    tracing::info!("Starting personhog-identity service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("Router URL: {}", config.router_url);

    // Build lifecycle manager and register components
    let mut manager = Manager::builder("personhog-identity").build();

    let grpc_handle = manager.register(
        "grpc_server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().is_observability(true),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor = manager.monitor_background();

    // Metrics/health HTTP server (observability handle — stays alive during standard drain)
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
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    let storage = create_storage(&config);

    // Pre-warm the DB connection pool before accepting traffic.
    // connect_lazy() starts with zero connections; without this, the first
    // burst of requests after K8s routes traffic all pay the cold-start cost.
    // Warming here is safe because the gRPC server hasn't bound its port yet.
    if config.min_pg_connections > 0 {
        let warmup_count = config.min_pg_connections as usize;
        let server_warmup_count = (config.warmup_server_connections as usize).min(warmup_count);
        tracing::info!(
            count = warmup_count,
            server_warmup = server_warmup_count,
            "Warming database connection pool before accepting traffic"
        );
        let pool_start = std::time::Instant::now();
        let mut conns = Vec::with_capacity(warmup_count);
        for _ in 0..warmup_count {
            match storage.primary_pool.acquire().await {
                Ok(conn) => conns.push(conn),
                Err(e) => {
                    tracing::warn!(error = %e, "Failed to warm connection");
                    break;
                }
            }
        }
        // Run a query on a subset of held connections to warm PgBouncer → PG.
        // acquire() only establishes app → PgBouncer; in transaction pooling
        // mode PgBouncer doesn't open a server connection until a query runs.
        let mut server_warmed = 0u32;
        for conn in conns.iter_mut().take(server_warmup_count) {
            match sqlx::query("SELECT 1").execute(&mut **conn).await {
                Ok(_) => server_warmed += 1,
                Err(e) => {
                    tracing::warn!(error = %e, "Failed to warm server-side connection");
                }
            }
        }
        tracing::info!(
            client_conns = conns.len(),
            server_conns = server_warmed,
            elapsed_ms = pool_start.elapsed().as_millis() as u64,
            "Pool warmup complete"
        );
    }

    spawn_pool_monitor(
        vec![MonitoredPool {
            pool: storage.primary_pool.clone(),
            label: "primary".to_string(),
            max_connections: config.max_pg_connections,
        }],
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    let property_writer = Arc::new(
        RouterClient::new(&config.router_url, config.leader_request_timeout())
            .expect("Invalid router URL"),
    );
    let service = PersonHogIdentityService::new(storage, property_writer, config.request_limits());

    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_connection_age = config.grpc_max_connection_age();
    let max_send = config.grpc_max_send_message_size;
    let max_recv = config.grpc_max_recv_message_size;
    let max_concurrent_requests = config.max_concurrent_requests;
    if max_concurrent_requests > 0 {
        tracing::info!(
            limit = max_concurrent_requests,
            "gRPC load shedding enabled"
        );
    }
    tracing::info!("Starting gRPC server on {}", grpc_addr);

    tokio::spawn(async move {
        let _guard = grpc_handle.process_scope();
        let listener = match tokio::net::TcpListener::bind(grpc_addr).await {
            Ok(l) => l,
            Err(e) => {
                grpc_handle.signal_failure(format!("Failed to bind gRPC port: {e}"));
                return;
            }
        };
        let incoming = tracked_tcp_incoming(listener);
        let mut server = Server::builder()
            .http2_keepalive_interval(keepalive_interval)
            .http2_keepalive_timeout(keepalive_timeout);
        if let Some(age) = max_connection_age {
            server = server.max_connection_age(age);
        }
        // accept_compressed only decodes gzip request frames from opted-in
        // clients (never send_compressed — see the tonic entry in Cargo.toml).
        // Note max_decoding_message_size bounds the wire (compressed) size, so
        // a compressed request can decode larger than the limit; tonic 0.12
        // does not cap the decompressed size (0.14 does — bounding this means
        // upgrading the workspace tonic). Until then this trusts internal
        // callers not to send pathological frames, same as the replica.
        if let Err(e) = server
            .layer(GrpcMetricsLayer::default().with_processing_time_header())
            .layer(GrpcLoadShedLayer::new(max_concurrent_requests))
            .add_service(
                PersonHogIdentityServer::new(service)
                    .accept_compressed(CompressionEncoding::Gzip)
                    .max_encoding_message_size(max_send)
                    .max_decoding_message_size(max_recv),
            )
            .serve_with_incoming_shutdown(incoming, grpc_handle.shutdown_signal())
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor.wait().await?;

    Ok(())
}
