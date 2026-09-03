use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_grpc::GrpcMetricsLayer;
use common_kafka::kafka_producer::create_kafka_producer;
use envconfig::Envconfig;
use health::HealthRegistry;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder};
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};
use usage_ingestion::config::Config;
use usage_ingestion::counters::{spawn_flush_task, CounterAccumulator};
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

    let kafka_config = config.kafka_config();
    let health = Arc::new(HealthRegistry::new("usage-ingestion"));
    let producer_liveness = health
        .register("kafka_producer".to_string(), Duration::from_secs(30))
        .await;
    let producer = create_kafka_producer(&kafka_config, producer_liveness).await?;
    let counters = (!config.redis_url.is_empty()).then(|| Arc::new(CounterAccumulator::default()));
    let service = UsageIngestionService::new(
        producer,
        resolver,
        config.max_batch_size,
        config.topic.clone(),
        counters.as_ref().map(Arc::clone),
    );

    // Buckets only for the shared gRPC histogram, so it renders the same way personhog's does
    // and quantiles aggregate across pods. Left global, these millisecond bounds would also
    // apply to kafka_delivery_seconds, which is in seconds and would land in one bucket.
    const GRPC_DURATION_BUCKETS_MS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];
    let metrics_handle = PrometheusBuilder::new()
        .set_buckets_for_metric(
            Matcher::Full("grpc_server_request_duration_ms".to_string()),
            GRPC_DURATION_BUCKETS_MS,
        )?
        .install_recorder()?;
    if let Some(accumulator) = counters {
        spawn_flush_task(
            accumulator,
            config.redis_url,
            Duration::from_secs(config.redis_flush_interval_seconds),
        );
    }
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
        .layer(GrpcMetricsLayer)
        .add_service(UsageIngestionServer::new(service))
        .serve(config.grpc_address.parse()?)
        .await?;
    Ok(())
}
