use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use common_kafka::kafka_consumer::SingleTopicConsumer;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_event_shuffler::config::Config;
use cohort_event_shuffler::consumer::EventShuffler;
use cohort_event_shuffler::filter_team_index::{run_refresh_loop, TeamIndex};
use cohort_event_shuffler::observability;
use cohort_event_shuffler::producer::CohortStreamProducer;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-event-shuffler";

fn main() -> Result<()> {
    let config = Config::init_from_env()
        .context("Failed to load configuration from environment variables")?;

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("Failed to build tokio runtime")?;

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
    // The consumer owns the liveness deadline: no successful batch within deadline × stall_threshold
    // trips coordinated shutdown.
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );
    // No liveness deadline: a refresh outage must not kill the service (staleness is safe). An
    // unexpected exit still signals the manager via the process-scope guard.
    let team_index_handle = manager.register(
        "team-index",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    // Build infrastructure before starting the monitor: a failure here returns before the monitor
    // runs, so dropped handles are harmless no-ops and the process exits non-zero.
    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

    let team_index = Arc::new(TeamIndex::with_allowlist(config.team_allowlist.clone()));
    match team_index.refresh(&pool).await {
        Ok(count) => info!(active_teams = count, "initial team index loaded"),
        Err(err) => warn!(
            error = %err,
            "initial team index load failed; consumer forwards nothing until the refresh task succeeds",
        ),
    }

    let kafka_config = config.build_kafka_config();
    let producer = CohortStreamProducer::new(&kafka_config, config.output_topic.clone())
        .await
        .context("creating cohort_stream_events producer")?;
    let consumer = SingleTopicConsumer::new(kafka_config, config.build_consumer_config())
        .context("creating clickhouse_events_json consumer")?;

    let guard = manager.monitor_background();

    let refresh_index = team_index.clone();
    let refresh_pool = pool.clone();
    let refresh_interval = config.team_index_refresh_interval();
    let refresh_jitter = config.team_index_refresh_jitter();
    tokio::spawn(async move {
        run_refresh_loop(
            refresh_index,
            refresh_pool,
            refresh_interval,
            refresh_jitter,
            team_index_handle,
        )
        .await;
    });

    let shuffler = EventShuffler::new(
        consumer,
        producer,
        team_index,
        consumer_handle,
        config.recv_batch_size,
        config.recv_batch_timeout(),
    );
    tokio::spawn(async move {
        shuffler.process().await;
    });

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder_handle);
    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");

    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("failed to bind observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("observability server error")?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// Deliberately omits `database_url`, which carries credentials.
fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        input_topic = %config.input_topic,
        output_topic = %config.output_topic,
        consumer_group = %config.kafka_consumer_group,
        partitioner = %config.kafka_producer_partitioner,
        offset_reset = %config.kafka_consumer_offset_reset,
        recv_batch_size = config.recv_batch_size,
        team_index_refresh_secs = config.team_index_refresh_secs,
        team_allowlist = ?config.team_allowlist,
        "starting cohort-event-shuffler",
    );
}

/// JSON structured logging by default; human-readable when `RUST_LOG` contains `debug`.
fn init_tracing() {
    let is_debug = std::env::var("RUST_LOG")
        .map(|v| v.contains("debug"))
        .unwrap_or(false);

    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    };

    tracing_subscriber::registry().with(log_layer).init();
}
