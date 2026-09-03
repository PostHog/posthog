use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::{setup_metrics_routes_with_overrides, Matcher};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::sync::mpsc;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_writer::config::Config;
use personhog_writer::consumer::ConsumerTask;
use personhog_writer::kafka::PersonConsumer;
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
    tracing::info!("Writer lanes: {}", config.writer_lanes);
    tracing::info!("Upsert concurrency: {}", config.upsert_concurrency);
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
    // All components must be registered before monitor_background() starts,
    // so writer lane handles are created up front.
    let lanes = config.writer_lanes.max(1);
    let mut writer_handles = Vec::with_capacity(lanes);
    for lane in 0..lanes {
        writer_handles.push(
            manager.register(
                &format!("writer-{lane}"),
                ComponentOptions::new()
                    .with_graceful_shutdown(Duration::from_secs(15))
                    .with_liveness_deadline(Duration::from_secs(30)),
            ),
        );
    }
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
        // E2E latency is a lag detector: healthy produce-to-commit lag is
        // seconds (the flush cadence), and the interesting tail is minutes
        // of writer lag. The default buckets cap at 10s, which would
        // collapse every lag excursion into +Inf.
        let metrics_router = setup_metrics_routes_with_overrides(
            health_router,
            &[(
                Matcher::Full("personhog_writer_e2e_latency_ms".into()),
                &[
                    250.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0, 60000.0, 120000.0, 300000.0,
                    600000.0,
                ],
            )],
        );

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

    // Kafka consumer
    let kafka_consumer = Arc::new(PersonConsumer::from_config(
        &config.kafka,
        &config.kafka_consumer_group,
        &config.kafka_consumer_offset_reset,
        config.kafka_topic.clone(),
    )?);
    tracing::info!("Subscribed to Kafka topic: {}", config.kafka_topic);

    // One statement-concurrency budget for the whole pod: every lane's
    // chunk and per-row statements draw from it, so lanes can overlap
    // writes without collectively oversubscribing the pool.
    let upsert_concurrency = config.upsert_concurrency.max(1);
    if upsert_concurrency > config.pg_max_connections as usize {
        tracing::warn!(
            upsert_concurrency,
            pg_max_connections = config.pg_max_connections,
            "UPSERT_CONCURRENCY exceeds PG_MAX_CONNECTIONS; excess statements \
             will queue on pool acquire instead of the semaphore"
        );
    }
    let upsert_permits = Arc::new(tokio::sync::Semaphore::new(upsert_concurrency));

    // Writer lanes: each lane gets its own channel, store, and task, and
    // commits offsets only for the partitions routed to it.
    let mut lane_txs = Vec::with_capacity(lanes);
    for writer_handle in writer_handles {
        let (flush_tx, flush_rx) = mpsc::channel(config.flush_channel_capacity);
        let store = PersonWriteStore::new(
            PgStore::new(pool.clone(), config.pg_target_table.clone()),
            personhog_writer::store::StoreConfig {
                chunk_size: config.upsert_batch_size,
                row_fallback_concurrency: config.row_fallback_concurrency,
            },
            Arc::clone(&upsert_permits),
        );
        let writer_task =
            WriterTask::new(Arc::clone(&kafka_consumer), store, flush_rx, writer_handle);
        tokio::spawn(async move {
            writer_task.run().await;
        });
        lane_txs.push(flush_tx);
    }

    // Consumer task
    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        lane_txs,
        (config.buffer_capacity / lanes).max(1),
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
