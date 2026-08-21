use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
use envconfig::Envconfig;
use health::HealthRegistry;
use metrics_exporter_prometheus::PrometheusBuilder;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};
use usage_ingestion::config::Config;
use usage_ingestion::resolver::PostgresOrganizationResolver;
use usage_ingestion::service::UsageIngestionService;
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_server::UsageIngestionServer;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let log_layer = {
        let base = tracing_subscriber::fmt::layer()
            .with_target(true)
            .with_thread_ids(true)
            .with_level(true);

        if std::env::var_os("DEBUG").is_some() {
            base.with_span_events(
                FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
            )
            .with_ansi(true)
            .boxed()
        } else {
            base.json()
                .flatten_event(true)
                .with_span_list(true)
                .with_current_span(true)
                .boxed()
        }
    };

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let config = Config::init_from_env()?;
    config.validate()?;

    let database = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 10,
            pool_name: Some("usage-ingestion".to_string()),
            ..Default::default()
        },
    )?;
    let resolver = Arc::new(PostgresOrganizationResolver::new(database));

    let kafka_config = KafkaConfig {
        kafka_hosts: config.kafka_hosts,
        kafka_tls: config.kafka_tls,
        kafka_client_id: "usage-ingestion".to_string(),
        ..Default::default()
    };
    let health = Arc::new(HealthRegistry::new("usage-ingestion"));
    let producer_liveness = health
        .register("kafka_producer".to_string(), Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&kafka_config, producer_liveness).await?;
    let service = UsageIngestionService::new(
        producer,
        resolver,
        config.max_batch_size,
        config.topic.clone(),
    );

    let metrics_handle = PrometheusBuilder::new().install_recorder()?;
    let metrics_address = config.metrics_address.clone();
    let health_for_routes = health.clone();
    tokio::spawn(async move {
        let router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let health = health_for_routes.clone();
                    async move { health.get_status() }
                }),
            )
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
    // This listener is limited to trusted in-cluster callers. Add authenticated caller identity
    // before exposing it beyond that boundary because records affect tenant billing.
    Server::builder()
        .add_service(UsageIngestionServer::new(service))
        .serve(config.grpc_address.parse()?)
        .await?;
    Ok(())
}
