use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;
use personhog_common::async_gzip::{AsyncGzipConfig, AsyncGzipLayer};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use personhog_proto::personhog::replica::v1::person_hog_replica_server::PersonHogReplicaServer;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_common::{spawn_pool_monitor, MonitoredPool};
use personhog_replica::config::Config;
use personhog_replica::service::PersonHogReplicaService;
use personhog_replica::storage::postgres::PostgresStorage;

common_alloc::used!();

async fn create_storage(config: &Config) -> Arc<PostgresStorage> {
    match config.storage_backend.as_str() {
        "postgres" => {
            let primary_pool_config = PoolConfig {
                min_connections: config.min_pg_connections,
                max_connections: config.max_pg_connections,
                acquire_timeout: config.acquire_timeout(),
                idle_timeout: config.idle_timeout(),
                test_before_acquire: false,
                statement_timeout_ms: config.statement_timeout(),
                pool_name: Some("primary".to_string()),
            };

            let replica_pool_config = PoolConfig {
                pool_name: Some("replica".to_string()),
                ..primary_pool_config.clone()
            };

            let bulk_primary_pool_config = PoolConfig {
                min_connections: config
                    .min_pg_connections
                    .min(config.bulk_max_pg_connections),
                max_connections: config.bulk_max_pg_connections,
                acquire_timeout: config.bulk_acquire_timeout(),
                statement_timeout_ms: config.bulk_statement_timeout(),
                pool_name: Some("bulk_primary".to_string()),
                ..primary_pool_config.clone()
            };

            let bulk_replica_pool_config = PoolConfig {
                pool_name: Some("bulk_replica".to_string()),
                ..bulk_primary_pool_config.clone()
            };

            // Create primary pool
            let primary_pool =
                get_pool_with_config(&config.primary_database_url, primary_pool_config)
                    .expect("Failed to create primary database pool");
            tracing::info!("Created primary database pool");

            // Create replica pool (uses primary URL if replica URL not configured)
            let replica_url = config.replica_database_url();
            let replica_pool = if replica_url == config.primary_database_url {
                tracing::info!("Replica URL not configured, using primary pool for both");
                primary_pool.clone()
            } else {
                let pool = get_pool_with_config(replica_url, replica_pool_config)
                    .expect("Failed to create replica database pool");
                tracing::info!("Created separate replica database pool");
                pool
            };

            // Create bulk pools (same URLs, smaller pool with longer timeouts)
            let bulk_primary_pool =
                get_pool_with_config(&config.primary_database_url, bulk_primary_pool_config)
                    .expect("Failed to create bulk primary database pool");

            let bulk_replica_pool = if replica_url == config.primary_database_url {
                bulk_primary_pool.clone()
            } else {
                get_pool_with_config(replica_url, bulk_replica_pool_config)
                    .expect("Failed to create bulk replica database pool")
            };
            tracing::info!(
                max_connections = config.bulk_max_pg_connections,
                statement_timeout_ms = config.bulk_statement_timeout_ms,
                "Created bulk database pools"
            );

            assert!(
                config.bulk_chunk_size >= 1,
                "BULK_CHUNK_SIZE must be at least 1"
            );
            assert!(
                config.bulk_max_concurrent_chunks >= 1,
                "BULK_MAX_CONCURRENT_CHUNKS must be at least 1"
            );
            assert!(
                config.bulk_max_concurrent_chunks <= config.bulk_max_pg_connections as usize,
                "BULK_MAX_CONCURRENT_CHUNKS ({}) must not exceed BULK_MAX_PG_CONNECTIONS ({})",
                config.bulk_max_concurrent_chunks,
                config.bulk_max_pg_connections
            );

            Arc::new(PostgresStorage::new(
                primary_pool,
                replica_pool,
                bulk_primary_pool,
                bulk_replica_pool,
                config.bulk_chunk_size,
                config.bulk_max_concurrent_chunks,
            ))
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
        const BUCKETS: &[f64] = &[
            1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
        ];
        let recorder_handle = PrometheusBuilder::new()
            .add_global_label("service", "personhog-replica")
            .set_buckets(BUCKETS)
            .unwrap()
            .install_recorder()
            .expect("Failed to install metrics recorder");

        let router = health_router.route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        );

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    // gRPC server
    let storage = create_storage(&config).await;

    // Pre-warm DB connection pools before accepting traffic.
    // connect_lazy() starts with zero connections; without this, the first
    // burst of requests after K8s routes traffic all pay the cold-start cost
    // (TCP + TLS + PgBouncer + SET statement_timeout). Warming here is safe
    // because the gRPC server hasn't bound its port yet — the startup probe
    // (TCP on 50051) can't pass until after this completes.
    if config.min_pg_connections > 0 {
        let warmup_count = config.min_pg_connections as usize;
        let server_warmup_count = (config.warmup_server_connections as usize).min(warmup_count);
        tracing::info!(
            count = warmup_count,
            server_warmup = server_warmup_count,
            "Warming database connection pools before accepting traffic"
        );
        let separate_replica = config.replica_database_url() != config.primary_database_url;
        let pools: Vec<(&sqlx::PgPool, &str)> = if separate_replica {
            vec![
                (&storage.primary_pool, "primary"),
                (&storage.replica_pool, "replica"),
            ]
        } else {
            vec![(&storage.primary_pool, "primary")]
        };

        for (pool, label) in &pools {
            let pool_start = std::time::Instant::now();
            let mut conns = Vec::with_capacity(warmup_count);
            for _ in 0..warmup_count {
                match pool.acquire().await {
                    Ok(conn) => conns.push(conn),
                    Err(e) => {
                        tracing::warn!(pool = label, error = %e, "Failed to warm connection");
                        break;
                    }
                }
            }
            // Run a query on a subset of held connections to warm PgBouncer → PG.
            // acquire() only establishes app → PgBouncer; in transaction pooling
            // mode PgBouncer doesn't open a server connection until a query runs.
            // We cap this to warmup_server_connections to avoid pinning too many
            // PgBouncer backend connections — the remaining client connections are
            // still warm (app → PgBouncer) and will get a server connection on
            // first real query.
            let mut server_warmed = 0u32;
            for conn in conns.iter_mut().take(server_warmup_count) {
                match sqlx::query("SELECT 1").execute(&mut **conn).await {
                    Ok(_) => server_warmed += 1,
                    Err(e) => {
                        tracing::warn!(pool = label, error = %e, "Failed to warm server-side connection");
                    }
                }
            }
            tracing::info!(
                pool = label,
                client_conns = conns.len(),
                server_conns = server_warmed,
                elapsed_ms = pool_start.elapsed().as_millis() as u64,
                "Pool warmup complete"
            );
            // Connections drop here, returning to the pool as idle
        }
    }

    // Spawn background pool health monitor
    let mut pools = vec![MonitoredPool {
        pool: storage.primary_pool.clone(),
        label: "primary".to_string(),
        max_connections: config.max_pg_connections,
    }];
    // Always monitor the replica pool so query metrics (pool="replica") can be
    // correlated with pool health gauges. When no separate replica URL is
    // configured, replica_pool is a clone of primary_pool — monitoring it under
    // both labels ensures the metrics align.
    pools.push(MonitoredPool {
        pool: storage.replica_pool.clone(),
        label: "replica".to_string(),
        max_connections: config.max_pg_connections,
    });
    pools.push(MonitoredPool {
        pool: storage.bulk_primary_pool.clone(),
        label: "bulk_primary".to_string(),
        max_connections: config.bulk_max_pg_connections,
    });
    pools.push(MonitoredPool {
        pool: storage.bulk_replica_pool.clone(),
        label: "bulk_replica".to_string(),
        max_connections: config.bulk_max_pg_connections,
    });
    spawn_pool_monitor(
        pools,
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    let service = PersonHogReplicaService::new(storage);
    let grpc_addr = config.grpc_address;
    let keepalive_interval = config.grpc_keepalive_interval();
    let keepalive_timeout = config.grpc_keepalive_timeout();
    let max_connection_age = config.grpc_max_connection_age();
    let max_send = config.grpc_max_send_message_size;
    let max_recv = config.grpc_max_recv_message_size;
    let max_concurrent_requests = config.max_concurrent_requests;
    let max_response_size = if config.gzip_max_response_size > 0 {
        Some(config.gzip_max_response_size)
    } else {
        None
    };
    let gzip_config = AsyncGzipConfig::new(
        config.gzip_response_compression,
        config.gzip_compression_level,
        config.gzip_min_payload_size,
    )
    .with_max_response_size(max_response_size, config.gzip_max_response_size_enforce);

    if gzip_config.enabled {
        tracing::info!(
            level = gzip_config.compression_level,
            min_payload_size = gzip_config.min_payload_size,
            "Async gzip response compression enabled"
        );
    }
    if let Some(limit) = gzip_config.max_response_size {
        tracing::info!(
            limit_bytes = limit,
            enforce = gzip_config.max_response_size_enforce,
            "Response size limit active"
        );
    }
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
        // No tonic codec compression: the zstd request/response codec served
        // the old typed router's client hop, which no longer exists. No
        // production client speaks zstd (grpcio and grpc-js cannot), so
        // response compression is exclusively the gzip layer above and
        // requests always arrive uncompressed.
        if let Err(e) = server
            .layer(AsyncGzipLayer::new(gzip_config))
            .layer(GrpcMetricsLayer::default().with_processing_time_header())
            .layer(GrpcLoadShedLayer::new(max_concurrent_requests))
            .add_service(
                PersonHogReplicaServer::new(service)
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
