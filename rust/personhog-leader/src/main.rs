use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use common_kafka::kafka_producer::create_kafka_producer;
use common_metrics::setup_metrics_routes;
use dashmap::DashMap;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use personhog_common::async_gzip::{AsyncGzipConfig, AsyncGzipLayer};
use personhog_common::grpc::{tracked_tcp_incoming, GrpcLoadShedLayer, GrpcMetricsLayer};
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::store::PersonhogStore;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use tonic::codec::CompressionEncoding;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_leader::cache::PartitionedCache;
use personhog_leader::config::Config;
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::service::{sweep_idle_locks, PersonHogLeaderService};

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

    tracing::info!("Starting personhog-leader service");
    tracing::info!("gRPC address: {}", config.grpc_address);
    tracing::info!(
        "Cache memory capacity: {} entries",
        config.cache_memory_capacity
    );
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("etcd endpoints: {}", config.etcd_endpoints);
    tracing::info!("etcd prefix: {}", config.etcd_prefix);
    tracing::info!("Pod name: {}", config.pod_name);
    tracing::info!("Kafka changelog topic: {}", config.kafka_person_state_topic);

    let mut manager = Manager::builder("personhog-leader")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();

    let grpc_handle = manager.register(
        "grpc-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let coordination_handle = manager.register(
        "coordination",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let kafka_handle = manager.register("kafka-producer", ComponentOptions::new());

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

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
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    // Initialize partitioned cache and Kafka producer
    let cache = Arc::new(PartitionedCache::new(config.cache_memory_capacity));

    let kafka_producer = match create_kafka_producer(&config.kafka, kafka_handle).await {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(error = %e, "failed to create Kafka producer");
            return Err(e.into());
        }
    };

    // PG fallback pool for cache misses (optional, disabled if URL is empty)
    let fallback_pool = if config.fallback_database_url.is_empty() {
        tracing::info!("PG fallback disabled (no FALLBACK_DATABASE_URL)");
        None
    } else {
        tracing::info!("PG fallback enabled");
        let pool_config = common_database::PoolConfig {
            max_connections: config.fallback_pg_max_connections,
            min_connections: config.fallback_pg_min_connections,
            pool_name: Some("personhog-leader-fallback".to_string()),
            statement_timeout_ms: Some(5_000),
            ..Default::default()
        };
        Some(common_database::get_pool_with_config(
            &config.fallback_database_url,
            pool_config,
        )?)
    };

    // Connect to etcd for coordination and the partition count
    let etcd_config = StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    };
    let etcd_store = EtcdStore::connect(etcd_config)
        .await
        .expect("Failed to connect to etcd");
    let store = Arc::new(PersonhogStore::new(etcd_store));

    // Read total_partitions from etcd (set by kafka-assigner) — the same
    // source the router hashes against, so partition validation can never
    // drift between the two.
    let num_partitions = store
        .get_total_partitions()
        .await
        .expect("Failed to read total_partitions from etcd");
    tracing::info!(num_partitions, "loaded partition count from etcd");

    let locks = Arc::new(DashMap::new());
    let inflight = Arc::new(personhog_leader::inflight::InflightTracker::new());
    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        config.kafka_person_state_topic.clone(),
        fallback_pool,
        Arc::clone(&locks),
        Arc::clone(&inflight),
        num_partitions,
    );

    let handler = LeaderHandoffHandler::new(
        Arc::clone(&cache),
        Arc::clone(&inflight),
        personhog_leader::warming::WarmingConfig {
            kafka: config.kafka.clone(),
            topic: config.kafka_person_state_topic.clone(),
            pod_name: config.pod_name.clone(),
            writer_consumer_group: config.writer_consumer_group.clone(),
            lookback_offsets: config.warm_lookback_offsets,
            committed_offsets_timeout: Duration::from_secs(
                config.warm_committed_offsets_timeout_secs,
            ),
            fetch_watermarks_timeout: Duration::from_secs(
                config.warm_fetch_watermarks_timeout_secs,
            ),
            recv_timeout: Duration::from_secs(config.warm_recv_timeout_secs),
            retry: personhog_leader::warming::WarmingRetryPolicy {
                max_attempts: config.warm_retry_max_attempts,
                initial_backoff: Duration::from_millis(config.warm_retry_initial_backoff_ms),
                max_backoff: Duration::from_millis(config.warm_retry_max_backoff_ms),
            },
        },
    );
    let pod = PodHandle::new(
        store,
        PodConfig {
            pod_name: config.pod_name.clone(),
            lease_ttl: config.lease_ttl,
            heartbeat_interval: config.heartbeat_interval(),
            ..Default::default()
        },
        Arc::new(handler),
        None,
    );

    tokio::spawn(async move {
        let _guard = coordination_handle.process_scope();
        if let Err(e) = pod.run(coordination_handle.shutdown_token()).await {
            coordination_handle.signal_failure(format!("Coordination error: {e}"));
        }
    });

    // Periodic sweep of idle per-key locks
    let sweep_locks = Arc::clone(&locks);
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            sweep_idle_locks(&sweep_locks);
        }
    });

    // gRPC server. Mirrors the replica's middleware stack so the router's
    // per-backend metrics (processing time, transport/network overhead) and
    // response compression behave identically on both backends. No tonic
    // codec compression: requests always arrive uncompressed (the router
    // rejects compressed leader requests before forwarding — it scans the
    // request bytes for the routing key), and response compression is
    // exclusively the gzip layer.
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
        if let Err(e) = server
            .layer(AsyncGzipLayer::new(gzip_config))
            .layer(GrpcMetricsLayer::default().with_processing_time_header())
            .layer(GrpcLoadShedLayer::new(max_concurrent_requests))
            .add_service(
                // accept_compressed only decodes gzip request frames from
                // opted-in clients; responses stay with the AsyncGzipLayer
                // (never send_compressed — see the tonic entry in Cargo.toml).
                PersonHogLeaderServer::new(service)
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

    monitor_guard.wait().await?;
    Ok(())
}
