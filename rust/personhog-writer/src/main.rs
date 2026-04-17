use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::ClientConfig;
use tokio::sync::mpsc;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_writer::buffer::PersonBuffer;
use personhog_writer::config::Config;
use personhog_writer::consumer::ConsumerTask;
use personhog_writer::kafka::build_consumer;
use personhog_writer::pg::PgWriter;
use personhog_writer::writer::WriterTask;

common_alloc::used!();

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

    tracing::info!("Starting personhog-writer");
    tracing::info!("Kafka topic: {}", config.kafka_topic);
    tracing::info!("Consumer group: {}", config.kafka_consumer_group);
    tracing::info!("Flush interval: {}ms", config.flush_interval_ms);
    tracing::info!("Flush buffer size: {}", config.flush_buffer_size);
    tracing::info!("Buffer capacity: {}", config.buffer_capacity);
    tracing::info!("Metrics port: {}", config.metrics_port);

    let mut manager = Manager::builder("personhog-writer")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();

    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    let writer_handle = manager.register(
        "writer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );

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

    // Postgres pool
    let pool_config = PoolConfig {
        max_connections: config.pg_max_connections,
        pool_name: Some("personhog-writer".to_string()),
        statement_timeout_ms: Some(30_000),
        ..Default::default()
    };
    let pool = get_pool_with_config(&config.database_url, pool_config)?;

    let (flush_tx, flush_rx) = mpsc::channel(config.flush_channel_capacity);

    // Kafka consumer
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", &config.kafka.kafka_hosts)
        .set("group.id", &config.kafka_consumer_group)
        .set("auto.offset.reset", &config.kafka_consumer_offset_reset)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        // Cooperative-sticky: during scale events, only partitions that need
        // to move are revoked. Non-moving partitions keep being consumed.
        .set("partition.assignment.strategy", "cooperative-sticky");

    // Static group membership: the broker holds partition assignments for
    // session.timeout.ms after a pod disappears, so quick restarts
    // (deploys, OOM kills) don't trigger a rebalance at all.
    // Requires stable pod names (StatefulSet) so the same ID reconnects.
    if !config.kafka.kafka_client_id.is_empty() {
        client_config
            .set("client.id", &config.kafka.kafka_client_id)
            .set("group.instance.id", &config.kafka.kafka_client_id);
    }

    if config.kafka.kafka_tls {
        client_config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }

    if !config.kafka.kafka_client_rack.is_empty() {
        client_config.set("client.rack", &config.kafka.kafka_client_rack);
    }

    let kafka_consumer = Arc::new(match build_consumer(&client_config, &config.kafka_topic) {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "failed to create Kafka consumer");
            return Err(e.into());
        }
    });
    tracing::info!("Subscribed to Kafka topic: {}", config.kafka_topic);

    // Writer task
    let pg_writer = PgWriter::new(pool, config.upsert_batch_size);
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        pg_writer,
        flush_rx,
        writer_handle,
        config.kafka_topic.clone(),
    );

    tokio::spawn(async move {
        writer_task.run().await;
    });

    // Consumer task
    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        PersonBuffer::new(config.buffer_capacity),
        flush_tx,
        config.flush_interval(),
        config.flush_buffer_size,
        consumer_handle,
    );

    tokio::spawn(async move {
        consumer_task.run().await;
    });

    monitor_guard.wait().await?;
    Ok(())
}
