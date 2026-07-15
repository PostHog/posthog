//! Binary entry point: parses `Config`, builds the infra clients, and hands the wired orchestrator to
//! the `lifecycle::Manager`. Depends on `app`, `clickhouse`, `kafka`, `config`, and `observability` —
//! the composition root at the top of the stack.

use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_seeder::app::{
    OrchestratorSettings, SeederOrchestrator, ORCHESTRATOR_LIVENESS_DEADLINE,
};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::scanner::ChunkScanner;
use cohort_seeder::config::Config;
use cohort_seeder::kafka::pacing::TilePacer;
use cohort_seeder::kafka::producer::SeedTileProducer;
use cohort_seeder::observability;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-seeder";
const PARTITION_VERIFY_TIMEOUT: Duration = Duration::from_secs(10);

fn main() -> Result<()> {
    let config = Config::init_from_env().context("loading cohort-seeder configuration")?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    init_tracing();
    log_startup(&config);

    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();
    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    let seeder_handle = manager.register(
        "seeder",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(ORCHESTRATOR_LIVENESS_DEADLINE)
            .with_stall_threshold(3),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let recorder = config
        .export_prometheus
        .then(observability::metrics::install_recorder)
        .transpose()
        .context("installing Prometheus recorder")?;

    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating cohort-seeder PostgreSQL pool")?;
    let scanner = ChunkScanner::new(build_client(&config).context("building ClickHouse client")?);
    let producer = SeedTileProducer::new(
        &config.build_kafka_config(),
        config.seed_events_topic.clone(),
    )
    .await
    .context("creating seed tile producer")?;
    let verify_producer = producer.clone();
    let expected_partitions = config.cohort_partition_count;
    tokio::task::spawn_blocking(move || {
        verify_producer.verify_partition_count(expected_partitions, PARTITION_VERIFY_TIMEOUT)
    })
    .await
    .context("joining seed topic verification task")?
    .context("verifying seed topic partition count")?;
    let pacer = TilePacer::new(
        config
            .tiles_per_second()
            .context("validating seed tile rate")?,
    );
    let settings =
        OrchestratorSettings::try_from(&config).context("validating orchestrator settings")?;
    let claimed_by = format!("cohort-seeder:{}", uuid::Uuid::now_v7());
    let orchestrator = SeederOrchestrator::new(
        pool,
        scanner,
        producer,
        pacer,
        config.team_allowlist.clone(),
        settings,
        seeder_handle,
        claimed_by,
    );

    let guard = manager.monitor_background();
    tokio::spawn(orchestrator.process());

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder);
    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");
    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("binding observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("serving observability endpoints")?;
    metrics_handle.work_completed();

    guard.wait().await?;
    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        seed_topic = %config.seed_events_topic,
        partitioner = %config.kafka_producer_partitioner,
        partition_count = config.cohort_partition_count,
        team_allowlist = ?config.team_allowlist,
        run_poll_secs = config.seeder_run_poll_secs,
        max_concurrent_chunks = config.seeder_max_concurrent_chunks,
        max_lookback_days = config.seeder_max_lookback_days,
        bands_per_day = config.seeder_bands_per_day,
        tiles_per_second = config.seeder_tiles_per_sec,
        max_inflight_tiles = config.seeder_max_inflight_tiles,
        "starting cohort-seeder",
    );
}

fn init_tracing() {
    let is_debug = std::env::var("RUST_LOG").is_ok_and(|value| value.contains("debug"));
    let filter = || {
        EnvFilter::builder()
            .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
            .from_env_lossy()
    };
    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(filter())
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(filter())
            .boxed()
    };
    tracing_subscriber::registry().with(log_layer).init();
}
