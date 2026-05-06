use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::sync::mpsc;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use common_kafka::kafka_producer::create_kafka_producer;
use personhog_writer::buffer::PersonBuffer;
use personhog_writer::config::Config;
use personhog_writer::consumer::ConsumerTask;
use personhog_writer::kafka::{PersonConsumer, WarningsProducer};
use personhog_writer::pg::PgStore;
use personhog_writer::store::PersonWriteStore;
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

    // Sample pool state into Prometheus gauges every 5s. Useful for tuning
    // PG_MAX_CONNECTIONS against observed utilization during fallback.
    {
        let pool = pool.clone();
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(std::time::Duration::from_secs(5));
            loop {
                ticker.tick().await;
                metrics::gauge!("personhog_writer_pg_pool_size").set(pool.size() as f64);
                metrics::gauge!("personhog_writer_pg_pool_idle").set(pool.num_idle() as f64);
            }
        });
    }

    let (flush_tx, flush_rx) = mpsc::channel(config.flush_channel_capacity);

    // Kafka consumer
    let kafka_consumer = Arc::new(PersonConsumer::from_config(
        &config.kafka,
        &config.kafka_consumer_group,
        &config.kafka_consumer_offset_reset,
        config.kafka_topic.clone(),
    )?);
    tracing::info!("Subscribed to Kafka topic: {}", config.kafka_topic);

    // Ingestion warnings producer
    let warnings_producer = create_kafka_producer(&config.kafka, writer_handle.clone())
        .await
        .map(|producer| {
            WarningsProducer::new(producer, config.kafka_ingestion_warnings_topic.clone())
        })
        .ok();

    if warnings_producer.is_some() {
        tracing::info!(
            "Ingestion warnings enabled (topic: {})",
            config.kafka_ingestion_warnings_topic
        );
    } else {
        tracing::warn!("Ingestion warnings disabled (Kafka producer creation failed)");
    }

    // Writer task
    let pg_store = PgStore::new(pool, config.pg_target_table.clone());
    let store = PersonWriteStore::new(
        pg_store,
        personhog_writer::store::StoreConfig {
            chunk_size: config.upsert_batch_size,
            row_fallback_concurrency: config.row_fallback_concurrency,
            properties_size_threshold: config.properties_size_threshold,
            properties_trim_target: config.properties_trim_target,
        },
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        store,
        flush_rx,
        writer_handle,
        warnings_producer,
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
