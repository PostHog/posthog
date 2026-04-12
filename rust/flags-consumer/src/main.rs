use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_kafka::kafka_consumer::SingleTopicConsumer;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_common::{spawn_pool_monitor, MonitoredPool};

use flags_consumer::config::Config;
use flags_consumer::consumer::{batch_processor_loop, consume_loop};
use flags_consumer::storage::postgres::PostgresStorage;
use flags_consumer::types::{DistinctIdMessage, PersonMessage};

common_alloc::used!();

const POOL_NAME: &str = "flags_read_store";
const SERVICE_NAME: &str = "flags-consumer";

async fn create_storage(config: &Config) -> Arc<PostgresStorage> {
    let pool_config = PoolConfig {
        min_connections: config.min_pg_connections,
        max_connections: config.max_pg_connections,
        acquire_timeout: config.acquire_timeout(),
        idle_timeout: config.idle_timeout(),
        test_before_acquire: true,
        statement_timeout_ms: config.statement_timeout(),
        pool_name: Some(POOL_NAME.to_string()),
    };

    let pool = get_pool_with_config(&config.flags_read_store_database_url, pool_config)
        .expect("Failed to create flags_read_store database pool");
    tracing::info!("Created flags_read_store database pool");

    Arc::new(PostgresStorage::new(pool))
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

    tracing::info!("Starting {SERVICE_NAME} service");
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!(
        person_topic = config.kafka_person_topic,
        did_topic = config.kafka_person_distinct_id_topic,
        consumer_group = config.kafka_consumer_group,
        batch_size = config.batch_size,
        "CDC consumer configuration"
    );

    if !config.filtered_team_ids.is_empty() {
        tracing::info!(
            teams = config.filtered_team_ids,
            "Team filter active (only processing listed teams)"
        );
    }

    // Build lifecycle manager and register components
    let mut manager = Manager::builder(SERVICE_NAME).build();

    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().is_observability(true),
    );
    let main_handle = manager.register(
        "main",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(30)),
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
            .add_global_label("service", SERVICE_NAME)
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

    // Create storage and verify connectivity before we report ready.
    let storage = create_storage(&config).await;
    storage
        .ping()
        .await
        .expect("Startup SELECT 1 against flags_read_store failed");
    tracing::info!("Startup SELECT 1 check succeeded");

    // Spawn background pool health monitor (reports personhog_db_pool_{size,idle,max} gauges)
    let pools = vec![MonitoredPool {
        pool: storage.pool.clone(),
        label: POOL_NAME.to_string(),
        max_connections: config.max_pg_connections,
    }];
    spawn_pool_monitor(
        pools,
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    // Build Kafka consumers
    let kafka_config = config.build_kafka_config();
    let person_consumer =
        SingleTopicConsumer::new(kafka_config.clone(), config.build_person_consumer_config())
            .expect("Failed to create person Kafka consumer");
    tracing::info!(topic = config.kafka_person_topic, "Person consumer created");

    let did_consumer =
        SingleTopicConsumer::new(kafka_config, config.build_distinct_id_consumer_config())
            .expect("Failed to create distinct_id Kafka consumer");
    tracing::info!(
        topic = config.kafka_person_distinct_id_topic,
        "Distinct-ID consumer created"
    );

    let team_filter = config.parsed_team_filter();
    let config = Arc::new(config);

    // Shared bounded channel: consumers -> batch processor.
    // Capacity = 4x batch size gives enough headroom for both consumers to
    // keep pushing while the processor flushes a batch.
    let (tx, rx) = mpsc::channel(config.batch_size * 4);

    // Shutdown coordination token shared across all consumer tasks.
    let shutdown = CancellationToken::new();

    // Spawn consumer tasks — one per topic, both using the generic loop
    // monomorphised over the message type.
    let person_tx = tx.clone();
    let person_shutdown = shutdown.clone();
    let person_filter = team_filter.clone();
    tokio::spawn(async move {
        consume_loop::<PersonMessage>(person_consumer, person_tx, person_filter, person_shutdown)
            .await;
    });

    let did_shutdown = shutdown.clone();
    let did_filter = team_filter;
    tokio::spawn(async move {
        consume_loop::<DistinctIdMessage>(did_consumer, tx, did_filter, did_shutdown).await;
    });

    // Run batch processor on the main component task.
    let processor_storage = storage.clone();
    let processor_config = config.clone();
    let processor_shutdown = shutdown.clone();
    tokio::spawn(async move {
        let _guard = main_handle.process_scope();
        batch_processor_loop(
            rx,
            processor_storage,
            processor_config,
            processor_shutdown,
            main_handle.clone(),
        )
        .await;
    });

    monitor.wait().await?;

    // Signal all consumer tasks to stop (they may already be stopped if the
    // lifecycle manager initiated shutdown, but this is idempotent).
    shutdown.cancel();

    Ok(())
}
