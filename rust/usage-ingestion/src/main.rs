use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use common_liveness::SyncLivenessReporter;
use common_redis::{CompressionConfig, RedisClient};
use envconfig::Envconfig;
use metrics_exporter_prometheus::PrometheusBuilder;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;
use usage_ingestion::config::Config;
use usage_ingestion::resolver::HyperCacheOrganizationResolver;
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_server::UsageIngestionServer;

#[derive(Clone)]
struct ProcessLiveness;

impl SyncLivenessReporter for ProcessLiveness {
    fn report_healthy(&self) {}

    fn report_unhealthy(&self) {}
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::registry()
        .with(tracing_subscriber::fmt::layer().json())
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let config = Config::init_from_env()?;
    config.validate()?;

    let redis_client = Arc::new(
        RedisClient::with_config(
            config.team_organization_redis_url.clone(),
            CompressionConfig::default(),
            common_redis::RedisValueFormat::default(),
            Some(Duration::from_millis(500)),
            Some(Duration::from_secs(5)),
        )
        .await?,
    );
    let mut hypercache_config = HyperCacheConfig::new(
        "usage_ingestion".to_string(),
        "organization_id.json".to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );
    hypercache_config.s3_endpoint = config
        .object_storage_endpoint
        .clone()
        .filter(|value| !value.is_empty());
    let cache = Arc::new(HyperCacheReader::new(redis_client, hypercache_config).await?);
    let database = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 10,
            pool_name: Some("usage-ingestion".to_string()),
            ..Default::default()
        },
    )?;
    let resolver = Arc::new(HyperCacheOrganizationResolver::new(cache, database));

    let kafka_config = KafkaConfig {
        kafka_hosts: config.kafka_hosts,
        kafka_tls: config.kafka_tls,
        kafka_client_id: "usage-ingestion".to_string(),
        ..Default::default()
    };
    let producer = create_kafka_producer(&kafka_config, ProcessLiveness).await?;
    let service = UsageIngestionService::new(
        producer,
        resolver,
        config.max_batch_size,
        config.topic.clone(),
    );

    let metrics_handle = PrometheusBuilder::new().install_recorder()?;
    let metrics_address = config.metrics_address.clone();
    tokio::spawn(async move {
        let router = Router::new()
            .route("/_readiness", get(|| async { "ok" }))
            .route("/_liveness", get(|| async { "ok" }))
            .route(
                "/metrics",
                get(move || std::future::ready(metrics_handle.render())),
            );
        let listener = tokio::net::TcpListener::bind(metrics_address)
            .await
            .expect("failed to bind usage-ingestion metrics listener");
        axum::serve(listener, router)
            .await
            .expect("usage-ingestion metrics server failed");
    });

    tracing::info!(address = %config.grpc_address, "Starting usage-ingestion gRPC service");
    Server::builder()
        .add_service(UsageIngestionServer::new(service))
        .serve(config.grpc_address.parse()?)
        .await?;
    Ok(())
}
