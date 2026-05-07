use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use clap::{Parser, Subcommand};
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

use flags_consumer::benchmark::BenchmarkArgs;
use flags_consumer::config::Config;
use flags_consumer::kafka::consumer::consume_loop;
use flags_consumer::kafka::messages::{DistinctIdMessage, PersonMessage};
use flags_consumer::pipeline::batch::batch_processor_loop;
use flags_consumer::storage::postgres::PostgresStorage;

common_alloc::used!();

const POOL_NAME: &str = "flags_read_store";
const SERVICE_NAME: &str = "flags-consumer";

#[derive(Parser)]
#[command(name = "flags-consumer")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Run the GIN index benchmark against the configured database
    Benchmark(BenchmarkArgs),
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Some(Command::Benchmark(args)) => {
            tracing_subscriber::fmt::init();
            flags_consumer::benchmark::run(args).await
        }
        None => {
            let config = Config::init_from_env().expect("Invalid configuration");
            init_tracing();
            log_startup_config(&config);
            run_consumer(config).await
        }
    }
}

async fn run_consumer(config: Config) -> anyhow::Result<()> {
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

    spawn_metrics_server(metrics_handle, readiness, liveness, config.metrics_port);

    let storage = create_storage(&config).await;
    storage
        .ping()
        .await
        .expect("Startup SELECT 1 against flags_read_store failed");
    tracing::info!("Startup SELECT 1 check succeeded");

    spawn_pool_monitor(
        vec![MonitoredPool {
            pool: storage.pool.clone(),
            label: POOL_NAME.to_string(),
            max_connections: config.max_pg_connections,
        }],
        Duration::from_secs(config.pool_monitor_interval_secs),
    );

    // Build Kafka consumers
    let kafka_config = config.build_kafka_config();
    let person_consumer =
        SingleTopicConsumer::new(kafka_config.clone(), config.build_person_consumer_config())
            .expect("Failed to create person Kafka consumer");
    let did_consumer =
        SingleTopicConsumer::new(kafka_config, config.build_distinct_id_consumer_config())
            .expect("Failed to create distinct_id Kafka consumer");

    let team_filter = config.parsed_team_filter();
    let config = Arc::new(config);
    let (tx, rx) = mpsc::channel(config.batch_size * 4);
    let shutdown = CancellationToken::new();

    // Spawn consumer tasks
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

    // Spawn batch processor
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
    shutdown.cancel();

    Ok(())
}

fn init_tracing() {
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
}

fn log_startup_config(config: &Config) {
    tracing::info!("Starting {SERVICE_NAME} service");
    tracing::info!(
        person_topic = config.kafka_person_topic,
        did_topic = config.kafka_person_distinct_id_topic,
        consumer_group = config.kafka_consumer_group,
        batch_size = config.batch_size,
        metrics_port = config.metrics_port,
        "CDC consumer configuration"
    );

    if !config.filtered_team_ids.is_empty() {
        tracing::info!(
            teams = config.filtered_team_ids,
            "Team filter active (only processing listed teams)"
        );
    }
}

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

fn spawn_metrics_server(
    handle: lifecycle::Handle,
    readiness: lifecycle::ReadinessHandler,
    liveness: lifecycle::LivenessHandler,
    port: u16,
) {
    tokio::spawn(async move {
        let _guard = handle.process_scope();

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

        let bind = format!("0.0.0.0:{port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });
}
