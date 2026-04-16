use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use common_kafka::kafka_producer::create_kafka_producer;
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use personhog_coordination::pod::{PodConfig, PodHandle};
use personhog_coordination::store::PersonhogStore;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_leader::cache::PartitionedCache;
use personhog_leader::config::Config;
use personhog_leader::coordination::LeaderHandoffHandler;
use personhog_leader::service::PersonHogLeaderService;

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

    let service = PersonHogLeaderService::new(
        Arc::clone(&cache),
        kafka_producer,
        config.kafka_person_state_topic.clone(),
    );

    // Connect to etcd and start coordination
    let etcd_config = StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    };
    let etcd_store = EtcdStore::connect(etcd_config)
        .await
        .expect("Failed to connect to etcd");
    let store = Arc::new(PersonhogStore::new(etcd_store));

    let handler = LeaderHandoffHandler::new(Arc::clone(&cache));
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

    // gRPC server
    let grpc_addr = config.grpc_address;
    tracing::info!("Starting gRPC server on {}", grpc_addr);

    tokio::spawn(async move {
        let _guard = grpc_handle.process_scope();
        if let Err(e) = Server::builder()
            .add_service(PersonHogLeaderServer::new(service))
            .serve_with_shutdown(grpc_addr, grpc_handle.shutdown_signal())
            .await
        {
            grpc_handle.signal_failure(format!("gRPC server error: {e}"));
        }
    });

    monitor_guard.wait().await?;
    Ok(())
}
